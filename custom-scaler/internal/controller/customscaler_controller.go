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
	ForecastDefaults       ForecastingDefaults
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
	Deployment     string                  `json:"deployment"`
	ContractID     string                  `json:"contract_id"`
	TargetMetric   string                  `json:"target_metric"`
	StepSeconds    int                     `json:"step_seconds"`
	Predictions    []float64               `json:"predictions"`
	PredictionRows []forecastPredictionRow `json:"prediction_rows"`
	Observed       map[string][]*float64   `json:"observed"`
}

type forecastPredictionRow struct {
	Datetime                     string  `json:"datetime"`
	TotalRequestsPerMinute       float64 `json:"total_requests_per_minute"`
	TotalCPUSecondsPerMinute     float64 `json:"total_cpu_seconds_per_minute"`
	TotalBandwidthBytesPerMinute float64 `json:"total_bandwidth_bytes_per_minute"`
}

type scalingPolicy struct {
	RequestsPerPod           float64
	CPUSecondsPerPod         float64
	SafetyFactor             float64
	SparePod                 int32
	MinReplicas              int32
	MaxReplicas              int32
	ScaleDownPolicy          string
	AppErrorRateThreshold    float64
	IngressP99ThresholdSec   float64
	IngressDeploymentName    string
	IngressDeploymentNS      string
	IngressReplicasPerWorker int32
	ReactiveRequiredPoints   int32
	ReactiveIncreaseStep     int32
	ReactiveDecreaseStep     int32
	ReactiveMaxBump          int32
	ReactiveReplicaStep      int32
}

type replicaDemandSummary struct {
	PeakRequestsPerMinute        float64
	EffectiveRequestsPerMinute   float64
	PeakCPUSecondsPerMinute      float64
	EffectiveCPUSecondsPerMinute float64
	RequestReplicaDemand         int32
	CPUReplicaDemand             int32
	BaseReplicaDemand            int32
	DominantSignal               string
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

func (r *CustomScalerControllerBase) buildForecastRequestBody() ([]byte, error) {
	contractID := strings.TrimSpace(r.ForecastDefaults.ContractID)
	if contractID == "" {
		return nil, fmt.Errorf("forecast contract id is empty")
	}

	requestBody := map[string]any{
		"contract_id": contractID,
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
		RequestsPerPod:           defaults.RequestsPerPod,
		CPUSecondsPerPod:         defaults.CPUSecondsPerPod,
		SafetyFactor:             defaults.SafetyFactor,
		SparePod:                 defaults.SparePod,
		MinReplicas:              defaults.MinReplicas,
		MaxReplicas:              defaults.MaxReplicas,
		ScaleDownPolicy:          defaults.ScaleDownPolicy,
		AppErrorRateThreshold:    defaults.AppErrorRateThreshold,
		IngressP99ThresholdSec:   defaults.IngressP99ThresholdSec,
		IngressDeploymentName:    defaults.IngressDeploymentName,
		IngressDeploymentNS:      defaults.IngressDeploymentNS,
		IngressReplicasPerWorker: defaults.IngressReplicasPerWorker,
		ReactiveRequiredPoints:   defaults.ReactiveRequiredPoints,
		ReactiveIncreaseStep:     defaults.ReactiveIncreaseStep,
		ReactiveDecreaseStep:     defaults.ReactiveDecreaseStep,
		ReactiveMaxBump:          defaults.ReactiveMaxBump,
		ReactiveReplicaStep:      defaults.ReactiveReplicaStep,
	}

	// Keep the legacy CR field as a request-capacity override for now.
	if customScaler.Spec.SafeRPSPerPod != nil && *customScaler.Spec.SafeRPSPerPod > 0 {
		policy.RequestsPerPod = *customScaler.Spec.SafeRPSPerPod
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

func calculateDesiredReplicas(forecast forecastResponse, policy scalingPolicy) (int32, replicaDemandSummary) {
	requestPredictions := forecast.Predictions
	summary := replicaDemandSummary{
		DominantSignal: "requests_per_minute",
	}

	if len(requestPredictions) > 0 {
		summary.PeakRequestsPerMinute = maxFloat64(requestPredictions)
		summary.EffectiveRequestsPerMinute = summary.PeakRequestsPerMinute * policy.SafetyFactor
		if policy.RequestsPerPod > 0 {
			summary.RequestReplicaDemand = int32(math.Ceil(summary.EffectiveRequestsPerMinute / policy.RequestsPerPod))
		}
	}

	if len(forecast.PredictionRows) > 0 {
		cpuPredictions := make([]float64, 0, len(forecast.PredictionRows))
		for _, row := range forecast.PredictionRows {
			cpuPredictions = append(cpuPredictions, row.TotalCPUSecondsPerMinute)
		}
		summary.PeakCPUSecondsPerMinute = maxFloat64(cpuPredictions)
		summary.EffectiveCPUSecondsPerMinute = summary.PeakCPUSecondsPerMinute * policy.SafetyFactor
		if policy.CPUSecondsPerPod > 0 {
			summary.CPUReplicaDemand = int32(math.Ceil(summary.EffectiveCPUSecondsPerMinute / policy.CPUSecondsPerPod))
		}
	}

	summary.BaseReplicaDemand = summary.RequestReplicaDemand
	if summary.CPUReplicaDemand > summary.BaseReplicaDemand {
		summary.BaseReplicaDemand = summary.CPUReplicaDemand
		summary.DominantSignal = "cpu_seconds_per_minute"
	}

	if summary.BaseReplicaDemand < 0 {
		summary.BaseReplicaDemand = 0
	}

	desiredReplicas := summary.BaseReplicaDemand
	if summary.BaseReplicaDemand > 0 {
		desiredReplicas += policy.SparePod
	}

	if desiredReplicas < policy.MinReplicas {
		desiredReplicas = policy.MinReplicas
	}
	if desiredReplicas > policy.MaxReplicas {
		desiredReplicas = policy.MaxReplicas
	}

	return desiredReplicas, summary
}

func allowScaleDown(observed map[string][]*float64, policy scalingPolicy) (bool, string) {
	if policy.ScaleDownPolicy != "safe" {
		return true, "policy-dangerous"
	}

	errorRateSeries := observed["app_error_rate"]
	ingressSeries := observed["ingress_p99_seconds"]
	if len(errorRateSeries) == 0 || len(ingressSeries) == 0 {
		return false, "missing-guardrail-history"
	}

	requiredRecentPoints := int(policy.ReactiveRequiredPoints)
	if requiredRecentPoints <= 0 {
		requiredRecentPoints = 1
	}

	recentErrorRateValues := recentNonNilValues(errorRateSeries, requiredRecentPoints)
	recentIngressValues := recentNonNilValues(ingressSeries, requiredRecentPoints)
	if len(recentErrorRateValues) < requiredRecentPoints || len(recentIngressValues) < requiredRecentPoints {
		return false, "insufficient-guardrail-history"
	}

	for _, value := range recentErrorRateValues {
		if *value > policy.AppErrorRateThreshold {
			return false, fmt.Sprintf("app_error_rate_above_threshold: %.3f > %.3f", *value, policy.AppErrorRateThreshold)
		}
	}

	for _, value := range recentIngressValues {
		if *value > policy.IngressP99ThresholdSec {
			return false, fmt.Sprintf("ingress_p99_above_threshold: %.3f > %.3f", *value, policy.IngressP99ThresholdSec)
		}
	}

	return true, "recent-guardrails-healthy"
}

func allowIngressScaleDown(observed map[string][]*float64, policy scalingPolicy) (bool, string) {
	requiredRecentPoints := int(policy.ReactiveRequiredPoints)
	if requiredRecentPoints <= 0 {
		requiredRecentPoints = 1
	}

	ingressSeries := observed["ingress_p99_seconds"]
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
		if value >= policy.IngressP99ThresholdSec {
			return false, fmt.Sprintf("recent-ingress-p99-not-all-below-threshold: %.3f >= %.3f", value, policy.IngressP99ThresholdSec)
		}
	}

	return true, "recent-ingress-p99-all-below-threshold"
}

func nextReactivePressureBump(currentBump int32, observed map[string][]*float64, policy scalingPolicy) (int32, string) {
	underPressure, reason := hasSustainedReactivePressure(observed, policy)
	if underPressure {
		next := currentBump + policy.ReactiveIncreaseStep
		if policy.ReactiveMaxBump > 0 && next > policy.ReactiveMaxBump {
			next = policy.ReactiveMaxBump
		}
		return next, reason
	}

	next := currentBump - policy.ReactiveDecreaseStep
	if next < 0 {
		next = 0
	}
	return next, reason
}

func hasSustainedReactivePressure(observed map[string][]*float64, policy scalingPolicy) (bool, string) {
	requiredRecentPoints := int(policy.ReactiveRequiredPoints)
	if requiredRecentPoints <= 0 {
		requiredRecentPoints = 1
	}

	ingressSeries := observed["ingress_p99_seconds"]
	errorRateSeries := observed["app_error_rate"]
	maxSeriesLength := len(ingressSeries)
	if len(errorRateSeries) > maxSeriesLength {
		maxSeriesLength = len(errorRateSeries)
	}
	if maxSeriesLength == 0 {
		return false, "missing-reactive-history"
	}

	collectedPoints := 0
	for offset := 0; offset < maxSeriesLength && collectedPoints < requiredRecentPoints; offset++ {
		index := maxSeriesLength - 1 - offset

		var ingressValue *float64
		if index >= 0 && index < len(ingressSeries) {
			ingressValue = ingressSeries[index]
		}

		var errorRateValue *float64
		if index >= 0 && index < len(errorRateSeries) {
			errorRateValue = errorRateSeries[index]
		}

		if ingressValue == nil && errorRateValue == nil {
			continue
		}

		collectedPoints++

		ingressTriggered := ingressValue != nil && *ingressValue > policy.IngressP99ThresholdSec
		errorRateTriggered := errorRateValue != nil && *errorRateValue > policy.AppErrorRateThreshold
		if !ingressTriggered && !errorRateTriggered {
			return false, "recent-reactive-pressure-not-triggered"
		}
	}

	if collectedPoints < requiredRecentPoints {
		return false, "insufficient-reactive-history"
	}

	return true, "recent-reactive-pressure-all-triggered"
}

func recentNonNilValues(series []*float64, limit int) []*float64 {
	if limit <= 0 || len(series) == 0 {
		return nil
	}

	values := make([]*float64, 0, limit)
	for index := len(series) - 1; index >= 0 && len(values) < limit; index-- {
		if series[index] == nil {
			continue
		}
		values = append(values, series[index])
	}

	return values
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
