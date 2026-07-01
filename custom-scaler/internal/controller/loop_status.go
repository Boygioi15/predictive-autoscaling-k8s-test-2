package controller

import (
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	autoscalingv1 "github.com/Boygioi15/predictive-autoscaling-k8s-test/api/v1"
)

func buildLastPodLoopStatus(
	customScaler *autoscalingv1.CustomScaler,
	forecast forecastResponse,
	requestBody string,
	responseBody string,
	summary replicaDemandSummary,
	currentReactivePressureBump int32,
	nextReactivePressureBump int32,
	reactivePressureReason string,
	reactivePressureReplicaBump int32,
	currentReplicas int32,
	proposedReplicas int32,
	desiredReplicas int32,
	scaleDownAllowed bool,
	scaleDownReason string,
	appliedScale bool,
) *autoscalingv1.PodScalerLoopStatus {
	observedAt := metav1.Now()

	return &autoscalingv1.PodScalerLoopStatus{
		ObservedAt:                   &observedAt,
		TargetDeployment:             customScaler.Spec.DeploymentName,
		ForecastContractID:           forecast.ContractID,
		ForecastModelName:            forecast.ModelName,
		ForecastModelVersion:         forecast.ModelVersion,
		ForecastRemoteContract:       forecast.RemoteContract,
		ForecastRemoteEndpoint:       forecast.RemoteEndpoint,
		ForecastFeatureMetrics:       append([]string(nil), forecast.FeatureMetrics...),
		ForecastStepSeconds:          int32(forecast.StepSeconds),
		ForecastGeneratedAt:          forecast.GeneratedAt,
		ForecastPredictionCount:      int32(len(forecast.Predictions)),
		ForecastPredictionRowsCount:  int32(len(forecast.PredictionRows)),
		ForecastRequiredHistoryRows:  int32(forecast.RequiredHistoryRows),
		ForecastProvidedHistoryRows:  int32(forecast.ProvidedHistoryRows),
		ForecastBufferedHistoryRows:  int32(forecast.BufferedHistoryRows),
		ForecastRequestPayload:       requestBody,
		ForecastResponseBody:         responseBody,
		PeakRequestsPerMinute:        summary.PeakRequestsPerMinute,
		EffectiveRequestsPerMinute:   summary.EffectiveRequestsPerMinute,
		PeakCPUSecondsPerMinute:      summary.PeakCPUSecondsPerMinute,
		EffectiveCPUSecondsPerMinute: summary.EffectiveCPUSecondsPerMinute,
		RequestReplicaDemand:         summary.RequestReplicaDemand,
		CPUReplicaDemand:             summary.CPUReplicaDemand,
		BaseReplicaDemand:            summary.BaseReplicaDemand,
		DominantSignal:               summary.DominantSignal,
		CurrentReactivePressureBump:  currentReactivePressureBump,
		NextReactivePressureBump:     nextReactivePressureBump,
		ReactivePressureReason:       reactivePressureReason,
		ReactivePressureReplicaBump:  reactivePressureReplicaBump,
		CurrentReplicas:              currentReplicas,
		ProposedReplicas:             proposedReplicas,
		DesiredReplicas:              desiredReplicas,
		ScaleDownAllowed:             scaleDownAllowed,
		ScaleDownReason:              scaleDownReason,
		AppliedScale:                 appliedScale,
	}
}

func buildLastNodeLoopStatus(
	customScaler *autoscalingv1.CustomScaler,
	plan *workerPrototypePlan,
	target workerTargetComputation,
	now time.Time,
) *autoscalingv1.NodeScalerLoopStatus {
	if plan == nil {
		return nil
	}

	observedAt := metav1.NewTime(now)

	return &autoscalingv1.NodeScalerLoopStatus{
		ObservedAt:              &observedAt,
		TargetDeployment:        customScaler.Spec.DeploymentName,
		DesiredReplicas:         target.DesiredReplicas,
		WorkerTargetMode:        target.Mode,
		WorkerCapacityStrategy:  target.Strategy,
		TargetWorkerCount:       plan.Status.TargetWorkerCount,
		RawTargetWorkerCount:    target.RawTargetWorkerCount,
		UnschedulablePods:       target.UnschedulablePods,
		SafetyPods:              target.SafetyPods,
		DesiredPodsForCapacity:  target.DesiredPodsForCapacity,
		NodeAllocatableMilliCPU: target.NodeAllocatableMilliCPU,
		PodRequestMilliCPU:      target.PodRequestMilliCPU,
		PodsPerWorker:           target.PodsPerWorker,
		MinWorkerCount:          target.MinWorkerCount,
		MaxWorkerCount:          target.MaxWorkerCount,
		ReadyWorkerCount:        target.ReadyWorkerCount,
		CurrentAppScheduledPods: target.CurrentAppScheduledPods,
		TotalAppSlotCapacity:    target.TotalAppSlotCapacity,
		MissingAppSlots:         target.MissingAppSlots,
		RequiredReadyWorkers:    target.RequiredReadyWorkers,
		ObservedReadyWorkers:    plan.Status.ObservedReadyWorkerCount,
		PendingCreateWorkers:    plan.Status.PendingCreateCount,
		PendingDeleteWorkers:    plan.Status.PendingDeleteCount,
		EffectiveWorkers:        plan.Status.EffectiveWorkerCount,
		WorkersToCreate:         plan.WorkersToCreate,
		WorkersToDelete:         plan.WorkersToDelete,
		LastAction:              plan.Status.LastAction,
		LastReason:              plan.Status.LastReason,
		ActiveOperations:        cloneActiveOperations(&plan.Status),
	}
}
