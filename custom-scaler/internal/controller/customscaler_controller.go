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
	"fmt"
	"math"
	"strings"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
	logf "sigs.k8s.io/controller-runtime/pkg/log"

	autoscalingv1 "github.com/Boygioi15/predictive-autoscaling-k8s-test/api/v1"
)

// CustomScalerControllerBase holds shared dependencies and helper methods used
// by the pod-scaling and node-scaling reconcilers.
type CustomScalerControllerBase struct {
	client.Client
	Scheme                 *runtime.Scheme
	PolicyDefaults         ScalingDefaults
	WorkerCapacityDefaults WorkerCapacityDefaults
	WorkerExecutor         WorkerExecutorConfig
}

// +kubebuilder:rbac:groups=autoscaling.my.domain,resources=customscalers,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups=autoscaling.my.domain,resources=customscalers/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=autoscaling.my.domain,resources=customscalers/finalizers,verbs=update
// +kubebuilder:rbac:groups=apps,resources=deployments;daemonsets,verbs=get;list;watch;update;patch
// +kubebuilder:rbac:groups="",resources=nodes,verbs=get;list;watch;patch;update;delete
// +kubebuilder:rbac:groups="",resources=pods,verbs=get;list;watch;delete
// +kubebuilder:rbac:groups="",resources=pods/eviction,verbs=create
// +kubebuilder:rbac:groups=policy,resources=pods/eviction,verbs=create
// +kubebuilder:rbac:groups=batch,resources=jobs,verbs=get;list;watch;create

type forecastResponse struct {
	Deployment   string                `json:"deployment"`
	TargetMetric string                `json:"target_metric"`
	StepSeconds  int                   `json:"step_seconds"`
	Predictions  []float64             `json:"predictions"`
	Observed     map[string][]*float64 `json:"observed"`
}

type scalingPolicy struct {
	SafeRPSPerPod                 float64
	SafetyFactor                  float64
	SparePod                      int32
	MinReplicas                   int32
	MaxReplicas                   int32
	ScaleDownPolicy               string
	AppP95ThresholdSeconds        float64
	IngressP95ThresholdSec        float64
	IngressDeploymentName         string
	IngressDeploymentNS           string
	IngressReplicasPerWorker      int32
	IngressPressureRequiredPoints int32
	IngressPressureIncreaseStep   int32
	IngressPressureDecreaseStep   int32
	IngressPressureMaxBump        int32
	IngressPressureWorkerStep     int32
	IngressPressureReplicaStep    int32
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

func (r *CustomScalerControllerBase) scalingPolicyFor(customScaler *autoscalingv1.CustomScaler) scalingPolicy {
	defaults := r.PolicyDefaults.normalized()

	policy := scalingPolicy{
		SafeRPSPerPod:                 defaults.SafeRPSPerPod,
		SafetyFactor:                  defaults.SafetyFactor,
		SparePod:                      defaults.SparePod,
		MinReplicas:                   defaults.MinReplicas,
		MaxReplicas:                   defaults.MaxReplicas,
		ScaleDownPolicy:               defaults.ScaleDownPolicy,
		AppP95ThresholdSeconds:        defaults.AppP95ThresholdSeconds,
		IngressP95ThresholdSec:        defaults.IngressP95ThresholdSec,
		IngressDeploymentName:         defaults.IngressDeploymentName,
		IngressDeploymentNS:           defaults.IngressDeploymentNS,
		IngressReplicasPerWorker:      defaults.IngressReplicasPerWorker,
		IngressPressureRequiredPoints: defaults.IngressPressureRequiredPoints,
		IngressPressureIncreaseStep:   defaults.IngressPressureIncreaseStep,
		IngressPressureDecreaseStep:   defaults.IngressPressureDecreaseStep,
		IngressPressureMaxBump:        defaults.IngressPressureMaxBump,
		IngressPressureWorkerStep:     defaults.IngressPressureWorkerStep,
		IngressPressureReplicaStep:    defaults.IngressPressureReplicaStep,
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

func (r *CustomScalerControllerBase) reconcileIngressDeployment(
	ctx context.Context,
	observed map[string][]*float64,
	policy scalingPolicy,
	observedReadyWorkers int32,
) error {
	if policy.IngressDeploymentName == "" || policy.IngressReplicasPerWorker <= 0 {
		return nil
	}

	var ingressDeployment appsv1.Deployment
	deploymentName := types.NamespacedName{
		Namespace: policy.IngressDeploymentNS,
		Name:      policy.IngressDeploymentName,
	}
	if err := r.Get(ctx, deploymentName, &ingressDeployment); err != nil {
		return err
	}

	desiredReplicas := observedReadyWorkers * policy.IngressReplicasPerWorker
	currentReplicas := int32(1)
	if ingressDeployment.Spec.Replicas != nil {
		currentReplicas = *ingressDeployment.Spec.Replicas
	}

	if desiredReplicas < currentReplicas {
		allowed, reason := allowIngressScaleDown(observed, policy)
		if !allowed {
			logf.FromContext(ctx).Info(
				"Skipping ingress scale down because recent ingress latency is not healthy enough",
				"deployment", deploymentName.String(),
				"currentReplicas", currentReplicas,
				"desiredReplicas", desiredReplicas,
				"scaleDownReason", reason,
			)
			return nil
		}
	}

	if desiredReplicas == currentReplicas {
		return nil
	}

	logf.FromContext(ctx).Info(
		"Scaling ingress deployment",
		"deployment", deploymentName.String(),
		"oldReplicas", currentReplicas,
		"newReplicas", desiredReplicas,
		"observedReadyWorkers", observedReadyWorkers,
		"replicasPerWorker", policy.IngressReplicasPerWorker,
	)

	ingressDeployment.Spec.Replicas = &desiredReplicas
	return r.Update(ctx, &ingressDeployment)
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

func allowIngressScaleDown(observed map[string][]*float64, policy scalingPolicy) (bool, string) {
	requiredRecentPoints := int(policy.IngressPressureRequiredPoints)
	if requiredRecentPoints <= 0 {
		requiredRecentPoints = 1
	}

	ingressSeries := observed["ingress_p95_seconds"]
	if len(ingressSeries) == 0 {
		return false, "missing-ingress-history"
	}

	recentValues := make([]float64, 0, requiredRecentPoints)
	for index := len(ingressSeries) - 1; index >= 0 && len(recentValues) < requiredRecentPoints; index-- {
		value := ingressSeries[index]
		if value == nil {
			continue
		}
		recentValues = append(recentValues, *value)
	}

	if len(recentValues) < requiredRecentPoints {
		return false, "insufficient-ingress-history"
	}

	for _, value := range recentValues {
		if value >= policy.IngressP95ThresholdSec {
			return false, fmt.Sprintf("recent-ingress-p95-not-all-below-threshold: %.3f >= %.3f", value, policy.IngressP95ThresholdSec)
		}
	}

	return true, "recent-ingress-p95-all-below-threshold"
}

func nextIngressPressureBump(currentBump int32, observed map[string][]*float64, policy scalingPolicy) (int32, string) {
	underPressure, reason := hasSustainedIngressPressure(observed, policy)
	if underPressure {
		next := currentBump + policy.IngressPressureIncreaseStep
		if policy.IngressPressureMaxBump > 0 && next > policy.IngressPressureMaxBump {
			next = policy.IngressPressureMaxBump
		}
		return next, reason
	}

	next := currentBump - policy.IngressPressureDecreaseStep
	if next < 0 {
		next = 0
	}
	return next, reason
}

func hasSustainedIngressPressure(observed map[string][]*float64, policy scalingPolicy) (bool, string) {
	requiredRecentPoints := int(policy.IngressPressureRequiredPoints)
	if requiredRecentPoints <= 0 {
		requiredRecentPoints = 1
	}

	ingressSeries := observed["ingress_p95_seconds"]
	if len(ingressSeries) == 0 {
		return false, "missing-ingress-history"
	}

	recentValues := make([]float64, 0, requiredRecentPoints)
	for index := len(ingressSeries) - 1; index >= 0 && len(recentValues) < requiredRecentPoints; index-- {
		value := ingressSeries[index]
		if value == nil {
			continue
		}
		recentValues = append(recentValues, *value)
	}

	if len(recentValues) < requiredRecentPoints {
		return false, "insufficient-ingress-history"
	}

	for _, value := range recentValues {
		if value <= policy.IngressP95ThresholdSec {
			return false, "recent-ingress-p95-not-all-above-threshold"
		}
	}

	return true, "recent-ingress-p95-all-above-threshold"
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

func workerPrototypeStatusChanged(
	current *autoscalingv1.WorkerPrototypeStatus,
	plan *workerPrototypePlan,
) bool {
	if plan == nil {
		return false
	}

	if current == nil {
		return true
	}

	return current.TargetWorkerCount != plan.Status.TargetWorkerCount ||
		current.ObservedReadyWorkerCount != plan.Status.ObservedReadyWorkerCount ||
		current.PendingCreateCount != plan.Status.PendingCreateCount ||
		current.PendingDeleteCount != plan.Status.PendingDeleteCount ||
		current.EffectiveWorkerCount != plan.Status.EffectiveWorkerCount ||
		current.LastAction != plan.Status.LastAction ||
		current.LastReason != plan.Status.LastReason ||
		activeOperationSlicesChanged(cloneActiveOperations(current), cloneActiveOperations(&plan.Status))
}

func workerOperationChanged(current, next *autoscalingv1.WorkerOperationStatus) bool {
	if current == nil && next == nil {
		return false
	}
	if current == nil || next == nil {
		return true
	}

	return current.OperationType != next.OperationType ||
		current.TargetNodeName != next.TargetNodeName ||
		current.Phase != next.Phase ||
		current.JobNamespace != next.JobNamespace ||
		current.JobName != next.JobName ||
		current.RequestedCount != next.RequestedCount ||
		current.Message != next.Message
}
