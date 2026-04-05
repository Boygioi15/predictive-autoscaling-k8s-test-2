/*
Copyright 2026.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

package controller

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	logf "sigs.k8s.io/controller-runtime/pkg/log"

	autoscalingv1 "github.com/Boygioi15/predictive-autoscaling-k8s-test/api/v1"
)

// CustomScalerReconciler reconciles a CustomScaler object
type CustomScalerReconciler struct {
	client.Client
	Scheme *runtime.Scheme
}

// +kubebuilder:rbac:groups=autoscaling.my.domain,resources=customscalers,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=autoscaling.my.domain,resources=customscalers/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=autoscaling.my.domain,resources=customscalers/finalizers,verbs=update

// Reconcile is part of the main kubernetes reconciliation loop which aims to
// move the current state of the cluster closer to the desired state.
// TODO(user): Modify the Reconcile function to compare the state specified by
// the CustomScaler object against the actual cluster state, and then
// perform operations to make the cluster state reflect the state specified by
// the user.
//
// For more details, check Reconcile and its Result here:
// - https://pkg.go.dev/sigs.k8s.io/controller-runtime@v0.23.3/pkg/reconcile
func (r *CustomScalerReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := logf.FromContext(ctx)

	// 1. Fetch the CustomScaler instance
	var customScaler autoscalingv1.CustomScaler
	if err := r.Get(ctx, req.NamespacedName, &customScaler); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	// 2. Observe: Call the HTTP Endpoint
	resp, err := http.Get(customScaler.Spec.URL)
	if err != nil {
		log.Error(err, "Failed to fetch value from endpoint")
		return ctrl.Result{RequeueAfter: time.Second * 30}, nil
	}
	defer resp.Body.Close()

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Error(err, "Failed to read response body")
		return ctrl.Result{RequeueAfter: time.Second * 30}, nil
	}

	// Convert response to integer, allowing either a plain number or JSON payload.
	val, err := parseReplicaValue(body)
	if err != nil {
		log.Error(err, "Response was not a valid replica count")
		return ctrl.Result{RequeueAfter: time.Second * 30}, nil
	}

	// 3. Analyze & Act: Find the Target Deployment
	var deployment appsv1.Deployment
	depName := types.NamespacedName{Namespace: customScaler.Namespace, Name: customScaler.Spec.DeploymentName}

	if err := r.Get(ctx, depName, &deployment); err != nil {
		log.Error(err, "Failed to find target deployment")
		return ctrl.Result{RequeueAfter: time.Second * 30}, nil
	}

	// Update replicas if they don't match the endpoint value
	desiredReplicas := int32(val)
	if *deployment.Spec.Replicas != desiredReplicas {
		log.Info("Scaling deployment", "Old", *deployment.Spec.Replicas, "New", desiredReplicas)
		deployment.Spec.Replicas = &desiredReplicas
		if err := r.Update(ctx, &deployment); err != nil {
			return ctrl.Result{}, err
		}
	}

	// Update Status with the last value we saw
	customScaler.Status.LastValue = val
	r.Status().Update(ctx, &customScaler)

	// Requeue every 15 seconds to check the endpoint again
	return ctrl.Result{RequeueAfter: time.Second * 15}, nil
}
func parseReplicaValue(body []byte) (int, error) {
	var response struct {
		Replica *int `json:"replica"`
	}

	if err := json.Unmarshal(body, &response); err == nil && response.Replica != nil {
		return *response.Replica, nil
	}

	trimmed := strings.TrimSpace(string(body))
	return strconv.Atoi(trimmed)
}

// SetupWithManager sets up the controller with the Manager.
func (r *CustomScalerReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&autoscalingv1.CustomScaler{}).
		Named("customscaler").
		Complete(r)
}
