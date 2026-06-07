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
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"strings"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/predicate"

	autoscalingv1 "github.com/Boygioi15/predictive-autoscaling-k8s-test/api/v1"
)

// CustomScalerReconciler reconciles a CustomScaler object
type CustomScalerReconciler struct {
	client.Client
	Scheme         *runtime.Scheme
	PolicyDefaults ScalingDefaults
}

// +kubebuilder:rbac:groups=autoscaling.my.domain,resources=customscalers,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=autoscaling.my.domain,resources=customscalers/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=autoscaling.my.domain,resources=customscalers/finalizers,verbs=update
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;update;patch

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

	requeueAfter := pollingInterval(customScaler.Spec.IntervalMinutes)
	log.Info(
		"Starting forecast polling cycle",
		"url", customScaler.Spec.URL,
		"targetDeployment", customScaler.Spec.DeploymentName,
		"forecastDeployment", forecastDeploymentName(&customScaler),
		"interval", requeueAfter.String(),
	)

	// 2. Observe: Call the forecasting service endpoint
	body, err := buildForecastRequestBody(&customScaler)
	if err != nil {
		log.Error(err, "Failed to build forecasting request")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	log.Info(
		"Calling forecasting service",
		"url", customScaler.Spec.URL,
		"payload", string(body),
	)

	resp, err := http.Post(customScaler.Spec.URL, "application/json", bytes.NewReader(body))
	if err != nil {
		log.Error(err, "Failed to call forecasting service")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}
	defer resp.Body.Close()

	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		responseBody, _ := io.ReadAll(resp.Body)
		log.Error(nil, "Forecasting service returned non-success status", "statusCode", resp.StatusCode, "body", string(responseBody))
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	responseBody, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Error(err, "Failed to read forecasting service response")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	log.Info(
		"Forecasting service response received",
		"statusCode", resp.StatusCode,
		"body", string(responseBody),
	)

	forecast, err := parseForecastResponse(responseBody)
	if err != nil {
		log.Error(err, "Response was not a valid forecast payload")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	policy := r.scalingPolicyFor(&customScaler)
	normalizedPredictions, predictionUnit := normalizeForecastPredictions(forecast)
	desiredReplicas, peakRPS, effectiveRPS := calculateDesiredReplicas(normalizedPredictions, policy)
	log.Info(
		"Calculated desired replicas from forecast",
		"targetDeployment", customScaler.Spec.DeploymentName,
		"forecastDeployment", forecastDeploymentName(&customScaler),
		"rawPredictions", forecast.Predictions,
		"normalizedPredictions", normalizedPredictions,
		"predictionUnit", predictionUnit,
		"peakRPS", peakRPS,
		"effectiveRPS", effectiveRPS,
		"safeRPSPerPod", policy.SafeRPSPerPod,
		"safetyFactor", policy.SafetyFactor,
		"sparePod", policy.SparePod,
		"desiredReplicas", desiredReplicas,
	)

	// 3. Analyze & Act: Find the Target Deployment
	var deployment appsv1.Deployment
	depName := types.NamespacedName{Namespace: customScaler.Namespace, Name: customScaler.Spec.DeploymentName}

	if err := r.Get(ctx, depName, &deployment); err != nil {
		log.Error(err, "Failed to find target deployment")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	// Update replicas if they don't match the endpoint value
	currentReplicas := int32(1)
	if deployment.Spec.Replicas != nil {
		currentReplicas = *deployment.Spec.Replicas
	}

	scaleDownAllowed := true
	scaleDownReason := "not-applicable"
	if desiredReplicas < currentReplicas {
		scaleDownAllowed, scaleDownReason = allowScaleDown(forecast.Observed, policy)
		if !scaleDownAllowed {
			log.Info(
				"Skipping scale down because guardrails are not healthy",
				"targetDeployment", customScaler.Spec.DeploymentName,
				"forecastDeployment", forecastDeploymentName(&customScaler),
				"currentReplicas", currentReplicas,
				"desiredReplicas", desiredReplicas,
				"scaleDownPolicy", policy.ScaleDownPolicy,
				"scaleDownReason", scaleDownReason,
				"observed", forecast.Observed,
			)
			desiredReplicas = currentReplicas
		}
	}

	if currentReplicas != desiredReplicas {
		log.Info("Scaling deployment", "Old", currentReplicas, "New", desiredReplicas)
		deployment.Spec.Replicas = &desiredReplicas
		if err := r.Update(ctx, &deployment); err != nil {
			return ctrl.Result{}, err
		}
	}

	// Update status only when it actually changed, otherwise we create extra reconcile events.
	if customScaler.Status.LastForecastPeak != peakRPS ||
		customScaler.Status.LastEffectiveRPS != effectiveRPS ||
		customScaler.Status.LastDesiredReplicas != desiredReplicas ||
		customScaler.Status.CurrentReplicas != desiredReplicas {
		customScaler.Status.LastForecastPeak = peakRPS
		customScaler.Status.LastEffectiveRPS = effectiveRPS
		customScaler.Status.LastDesiredReplicas = desiredReplicas
		customScaler.Status.CurrentReplicas = desiredReplicas
		if err := r.Status().Update(ctx, &customScaler); err != nil {
			log.Error(err, "Failed to update custom scaler status")
			return ctrl.Result{RequeueAfter: requeueAfter}, nil
		}
	}

	//////Final check

	log.Info(
		"Forecast polling cycle completed",
		"deployment", customScaler.Spec.DeploymentName,
		"replica", desiredReplicas,
		"nextRunIn", requeueAfter.String(),
	)

	return ctrl.Result{RequeueAfter: requeueAfter}, nil
}

type forecastResponse struct {
	Deployment   string                `json:"deployment"`
	TargetMetric string                `json:"target_metric"`
	StepSeconds  int                   `json:"step_seconds"`
	Predictions  []float64             `json:"predictions"`
	Observed     map[string][]*float64 `json:"observed"`
}

type scalingPolicy struct {
	SafeRPSPerPod          float64
	SafetyFactor           float64
	SparePod               int32
	MinReplicas            int32
	MaxReplicas            int32
	ScaleDownPolicy        string
	AppP95ThresholdSeconds float64
	IngressP95ThresholdSec float64
}

func parseForecastResponse(body []byte) (forecastResponse, error) {
	var response forecastResponse
	if err := json.Unmarshal(body, &response); err != nil {
		return forecastResponse{}, err
	}

	if len(response.Predictions) == 0 {
		return forecastResponse{}, fmt.Errorf("forecast response did not include predictions")
	}

	return response, nil
}

func pollingInterval(intervalMinutes int) time.Duration {
	if intervalMinutes <= 0 {
		intervalMinutes = 1
	}

	return time.Duration(intervalMinutes) * time.Minute
}

func buildForecastRequestBody(customScaler *autoscalingv1.CustomScaler) ([]byte, error) {
	requestBody := map[string]any{
		"deployment": forecastDeploymentName(customScaler),
	}

	return json.Marshal(requestBody)
}

func forecastDeploymentName(customScaler *autoscalingv1.CustomScaler) string {
	if customScaler.Spec.ForecastDeployment != "" {
		return customScaler.Spec.ForecastDeployment
	}

	if trimmed := strings.TrimSuffix(customScaler.Spec.DeploymentName, "-deployment"); trimmed != "" {
		return trimmed
	}

	return customScaler.Spec.DeploymentName
}

func (r *CustomScalerReconciler) scalingPolicyFor(customScaler *autoscalingv1.CustomScaler) scalingPolicy {
	defaults := r.PolicyDefaults.normalized()

	policy := scalingPolicy{
		SafeRPSPerPod:          defaults.SafeRPSPerPod,
		SafetyFactor:           defaults.SafetyFactor,
		SparePod:               defaults.SparePod,
		MinReplicas:            defaults.MinReplicas,
		MaxReplicas:            defaults.MaxReplicas,
		ScaleDownPolicy:        defaults.ScaleDownPolicy,
		AppP95ThresholdSeconds: defaults.AppP95ThresholdSeconds,
		IngressP95ThresholdSec: defaults.IngressP95ThresholdSec,
	}

	if customScaler.Spec.SafeRPSPerPod != nil && *customScaler.Spec.SafeRPSPerPod > 0 {
		policy.SafeRPSPerPod = *customScaler.Spec.SafeRPSPerPod
	}
	if customScaler.Spec.SafetyFactor != nil && *customScaler.Spec.SafetyFactor > 0 {
		policy.SafetyFactor = *customScaler.Spec.SafetyFactor
	}
	if customScaler.Spec.SparePod != nil && *customScaler.Spec.SparePod >= 0 {
		policy.SparePod = *customScaler.Spec.SparePod
	}
	if customScaler.Spec.MinReplicas != nil && *customScaler.Spec.MinReplicas > 0 {
		policy.MinReplicas = *customScaler.Spec.MinReplicas
	}
	if customScaler.Spec.MaxReplicas != nil && *customScaler.Spec.MaxReplicas > 0 {
		policy.MaxReplicas = *customScaler.Spec.MaxReplicas
	}
	if policy.MaxReplicas < policy.MinReplicas {
		policy.MaxReplicas = policy.MinReplicas
	}

	return policy
}

func calculateDesiredReplicas(predictions []float64, policy scalingPolicy) (int32, float64, float64) {
	peakRPS := maxFloat64(predictions)
	effectiveRPS := peakRPS * policy.SafetyFactor
	baseReplicas := int32(math.Ceil(effectiveRPS / policy.SafeRPSPerPod))
	if baseReplicas < 0 {
		baseReplicas = 0
	}

	desiredReplicas := baseReplicas
	if baseReplicas > 0 {
		desiredReplicas += policy.SparePod
	}

	if desiredReplicas < policy.MinReplicas {
		desiredReplicas = policy.MinReplicas
	}
	if desiredReplicas > policy.MaxReplicas {
		desiredReplicas = policy.MaxReplicas
	}

	return desiredReplicas, peakRPS, effectiveRPS
}

func normalizeForecastPredictions(forecast forecastResponse) ([]float64, string) {
	normalized := make([]float64, len(forecast.Predictions))
	copy(normalized, forecast.Predictions)

	targetMetric := strings.ToLower(strings.TrimSpace(forecast.TargetMetric))
	switch targetMetric {
	case "rps_per_min", "requests_per_minute", "rpm":
		stepSeconds := forecast.StepSeconds
		if stepSeconds <= 0 {
			stepSeconds = 60
		}
		for i, value := range normalized {
			normalized[i] = value / float64(stepSeconds)
		}
		return normalized, "rps"
	default:
		return normalized, targetMetric
	}
}

func allowScaleDown(observed map[string][]*float64, policy scalingPolicy) (bool, string) {
	if policy.ScaleDownPolicy != "safe" {
		return true, "policy-dangerous"
	}

	appSeries := observed["app_p95_seconds"]
	ingressSeries := observed["ingress_p95_seconds"]
	if len(appSeries) == 0 || len(ingressSeries) == 0 {
		return false, "missing-guardrail-history"
	}

	validGuardrailPoint := false

	for _, value := range appSeries {
		if value == nil {
			continue
		}
		validGuardrailPoint = true
		if *value > policy.AppP95ThresholdSeconds {
			return false, fmt.Sprintf("app_p95_above_threshold: %.3f > %.3f", *value, policy.AppP95ThresholdSeconds)
		}
	}

	for _, value := range ingressSeries {
		if value == nil {
			continue
		}
		validGuardrailPoint = true
		if *value > policy.IngressP95ThresholdSec {
			return false, fmt.Sprintf("ingress_p95_above_threshold: %.3f > %.3f", *value, policy.IngressP95ThresholdSec)
		}
	}

	if !validGuardrailPoint {
		return true, "no-valid-guardrail-points"
	}

	return true, "all-guardrails-healthy"
}

func maxFloat64(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}

	maxValue := values[0]
	for _, value := range values[1:] {
		if value > maxValue {
			maxValue = value
		}
	}
	return maxValue
}

// SetupWithManager sets up the controller with the Manager.
func (r *CustomScalerReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&autoscalingv1.CustomScaler{}, builder.WithPredicates(predicate.GenerationChangedPredicate{})).
		Named("customscaler").
		Complete(r)
}
