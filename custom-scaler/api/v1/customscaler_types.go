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

package v1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// EDIT THIS FILE!  THIS IS SCAFFOLDING FOR YOU TO OWN!
// NOTE: json tags are required.  Any new fields you add must have json tags for the fields to be serialized.

// CustomScalerSpec defines the desired state of CustomScaler
type CustomScalerSpec struct {
	// The forecasting service endpoint to call.
	URL string `json:"url"`
	// Name of the Deployment to scale
	DeploymentName string `json:"deploymentName"`
	// Optional deployment key sent to the forecasting service.
	// When omitted, the controller derives it from DeploymentName.
	ForecastDeployment string `json:"forecastDeployment,omitempty"`
	// Polling interval in minutes. Defaults to 1 minute when omitted or invalid.
	IntervalMinutes int `json:"intervalMinutes,omitempty"`
	// Optional per-scaler override for the safe per-pod RPS capacity.
	SafeRPSPerPod *float64 `json:"safeRpsPerPod,omitempty"`
	// Optional per-scaler override for the forecast safety factor.
	SafetyFactor *float64 `json:"safetyFactor,omitempty"`
	// Optional per-scaler override for the number of spare pods to add.
	SparePod *int32 `json:"sparePod,omitempty"`
	// Optional per-scaler override for the minimum replica clamp.
	MinReplicas *int32 `json:"minReplicas,omitempty"`
	// Optional per-scaler override for the maximum replica clamp.
	MaxReplicas *int32 `json:"maxReplicas,omitempty"`
	// Optional prototype settings for durable worker-count planning.
	WorkerPrototype *WorkerPrototypeSpec `json:"workerPrototype,omitempty"`
}

type WorkerPrototypeSpec struct {
	// Optional manual override for the desired worker-node count.
	// When omitted, the controller computes it from desired replicas, safety pods,
	// unschedulable pods, node allocatable CPU, and app pod request CPU.
	TargetWorkerCount *int32 `json:"targetWorkerCount,omitempty"`
	// Maximum number of worker operations to enqueue in a single reconcile.
	MaxBatchSize *int32 `json:"maxBatchSize,omitempty"`
	// Optional node label key used to identify worker nodes.
	NodeLabelKey string `json:"nodeLabelKey,omitempty"`
	// Optional node label value used together with NodeLabelKey.
	NodeLabelValue string `json:"nodeLabelValue,omitempty"`
}

type CustomScalerStatus struct {
	// The latest forecast peak seen from the forecasting service.
	LastForecastPeak float64 `json:"lastForecastPeak"`
	// The latest buffered RPS value after applying operator safety logic.
	LastEffectiveRPS float64 `json:"lastEffectiveRps"`
	// The latest desired replica count computed by the operator.
	LastDesiredReplicas int32 `json:"lastDesiredReplicas"`
	// Current replica count
	CurrentReplicas int32 `json:"currentReplicas"`
	// Stateful reactive pressure level used to accumulate emergency scaling under sustained saturation.
	ReactivePressureBump int32 `json:"reactivePressureBump,omitempty"`
	// Human-readable reason for the latest reactive pressure bump transition.
	ReactivePressureReason string `json:"reactivePressureReason,omitempty"`
	// Latest detailed pod-scaling reconcile snapshot for UI/debugging.
	LastPodLoop *PodScalerLoopStatus `json:"lastPodLoop,omitempty"`
	// Latest detailed node-scaling reconcile snapshot for UI/debugging.
	LastNodeLoop *NodeScalerLoopStatus `json:"lastNodeLoop,omitempty"`
	// Durable worker-planning state for the prototype node scaler.
	WorkerPrototype *WorkerPrototypeStatus `json:"workerPrototype,omitempty"`
}

type PodScalerLoopStatus struct {
	// Time when the pod reconciler completed this snapshot.
	ObservedAt *metav1.Time `json:"observedAt,omitempty"`
	// Deployment the pod reconciler evaluated.
	TargetDeployment string `json:"targetDeployment,omitempty"`
	// Forecast contract id sent to the forecasting service.
	ForecastContractID string `json:"forecastContractId,omitempty"`
	// Forecast model name returned by the forecasting service.
	ForecastModelName string `json:"forecastModelName,omitempty"`
	// Forecast model version returned by the forecasting service.
	ForecastModelVersion string `json:"forecastModelVersion,omitempty"`
	// Remote forecasting contract used by the forecasting service.
	ForecastRemoteContract string `json:"forecastRemoteContract,omitempty"`
	// Remote forecasting endpoint used by the forecasting service.
	ForecastRemoteEndpoint string `json:"forecastRemoteEndpoint,omitempty"`
	// Feature metrics included in the selected forecast contract.
	ForecastFeatureMetrics []string `json:"forecastFeatureMetrics,omitempty"`
	// Forecasting step size in seconds.
	ForecastStepSeconds int32 `json:"forecastStepSeconds,omitempty"`
	// Timestamp string returned by the forecasting service for this forecast batch.
	ForecastGeneratedAt string `json:"forecastGeneratedAt,omitempty"`
	// Number of scalar predictions returned by the forecast.
	ForecastPredictionCount int32 `json:"forecastPredictionCount,omitempty"`
	// Number of per-metric prediction rows returned by the forecast.
	ForecastPredictionRowsCount int32 `json:"forecastPredictionRowsCount,omitempty"`
	// Context rows the remote model required for this forecast.
	ForecastRequiredHistoryRows int32 `json:"forecastRequiredHistoryRows,omitempty"`
	// Context rows the remote model received for this forecast.
	ForecastProvidedHistoryRows int32 `json:"forecastProvidedHistoryRows,omitempty"`
	// Buffered context rows reported by the remote model.
	ForecastBufferedHistoryRows int32 `json:"forecastBufferedHistoryRows,omitempty"`
	// Raw JSON body sent to the forecasting service.
	ForecastRequestPayload string `json:"forecastRequestPayload,omitempty"`
	// Raw JSON body returned by the forecasting service.
	ForecastResponseBody string `json:"forecastResponseBody,omitempty"`
	// Peak request forecast used for replica math.
	PeakRequestsPerMinute float64 `json:"peakRequestsPerMinute,omitempty"`
	// Safety-adjusted request forecast used for replica math.
	EffectiveRequestsPerMinute float64 `json:"effectiveRequestsPerMinute,omitempty"`
	// Peak CPU forecast used for replica math.
	PeakCPUSecondsPerMinute float64 `json:"peakCpuSecondsPerMinute,omitempty"`
	// Safety-adjusted CPU forecast used for replica math.
	EffectiveCPUSecondsPerMinute float64 `json:"effectiveCpuSecondsPerMinute,omitempty"`
	// Replica demand derived from requests.
	RequestReplicaDemand int32 `json:"requestReplicaDemand,omitempty"`
	// Replica demand derived from CPU.
	CPUReplicaDemand int32 `json:"cpuReplicaDemand,omitempty"`
	// Forecast-only replica demand before spare/reactive adjustments.
	BaseReplicaDemand int32 `json:"baseReplicaDemand,omitempty"`
	// Signal that dominated the base replica demand.
	DominantSignal string `json:"dominantSignal,omitempty"`
	// Reactive pressure level before this reconcile.
	CurrentReactivePressureBump int32 `json:"currentReactivePressureBump,omitempty"`
	// Reactive pressure level chosen by this reconcile.
	NextReactivePressureBump int32 `json:"nextReactivePressureBump,omitempty"`
	// Human-readable reason for the reactive pressure decision.
	ReactivePressureReason string `json:"reactivePressureReason,omitempty"`
	// Replica increment contributed by the reactive pressure bump.
	ReactivePressureReplicaBump int32 `json:"reactivePressureReplicaBump,omitempty"`
	// Replica count observed on the workload before this reconcile applied changes.
	CurrentReplicas int32 `json:"currentReplicas,omitempty"`
	// Proposed replica count before scale-down guardrails may clamp it.
	ProposedReplicas int32 `json:"proposedReplicas,omitempty"`
	// Final desired replica count after all guardrails.
	DesiredReplicas int32 `json:"desiredReplicas,omitempty"`
	// Whether the scale-down guardrail allowed a pending scale-down decision.
	ScaleDownAllowed bool `json:"scaleDownAllowed,omitempty"`
	// Human-readable reason for the latest scale-down decision.
	ScaleDownReason string `json:"scaleDownReason,omitempty"`
	// Whether this reconcile updated the Deployment replica count.
	AppliedScale bool `json:"appliedScale,omitempty"`
}

type NodeScalerLoopStatus struct {
	// Time when the node reconciler completed this snapshot.
	ObservedAt *metav1.Time `json:"observedAt,omitempty"`
	// Deployment whose desired replica count fed node planning.
	TargetDeployment string `json:"targetDeployment,omitempty"`
	// Desired pod replicas observed by node scaling.
	DesiredReplicas int32 `json:"desiredReplicas,omitempty"`
	// Whether worker planning used a manual or automatic target.
	WorkerTargetMode string `json:"workerTargetMode,omitempty"`
	// Worker-capacity strategy used for target computation.
	WorkerCapacityStrategy string `json:"workerCapacityStrategy,omitempty"`
	// Final worker target after bounds are applied.
	TargetWorkerCount int32 `json:"targetWorkerCount,omitempty"`
	// Raw worker target before min/max bounds are applied.
	RawTargetWorkerCount int32 `json:"rawTargetWorkerCount,omitempty"`
	// Unschedulable workload pods observed during planning.
	UnschedulablePods int32 `json:"unschedulablePods,omitempty"`
	// Extra safety pods reserved by worker capacity policy.
	SafetyPods int32 `json:"safetyPods,omitempty"`
	// Pod count the worker planner tried to provide capacity for.
	DesiredPodsForCapacity int32 `json:"desiredPodsForCapacity,omitempty"`
	// Allocatable CPU assumed for each worker node.
	NodeAllocatableMilliCPU int32 `json:"nodeAllocatableMilliCpu,omitempty"`
	// Requested CPU assumed for each workload pod.
	PodRequestMilliCPU int32 `json:"podRequestMilliCpu,omitempty"`
	// Number of workload pods each worker can host.
	PodsPerWorker int32 `json:"podsPerWorker,omitempty"`
	// Minimum worker count allowed by policy.
	MinWorkerCount int32 `json:"minWorkerCount,omitempty"`
	// Maximum worker count allowed by policy.
	MaxWorkerCount int32 `json:"maxWorkerCount,omitempty"`
	// Ready workers counted during target computation.
	ReadyWorkerCount int32 `json:"readyWorkerCount,omitempty"`
	// App pods already scheduled on managed workers.
	CurrentAppScheduledPods int32 `json:"currentAppScheduledPods,omitempty"`
	// Total app slot capacity observed on ready workers.
	TotalAppSlotCapacity int32 `json:"totalAppSlotCapacity,omitempty"`
	// App slots still missing after using all ready workers.
	MissingAppSlots int32 `json:"missingAppSlots,omitempty"`
	// Ready workers required to satisfy current slot demand.
	RequiredReadyWorkers int32 `json:"requiredReadyWorkers,omitempty"`
	// Ready workers observed by ensure_worker state tracking.
	ObservedReadyWorkers int32 `json:"observedReadyWorkers,omitempty"`
	// Pending worker create operations tracked in status.
	PendingCreateWorkers int32 `json:"pendingCreateWorkers,omitempty"`
	// Pending worker delete operations tracked in status.
	PendingDeleteWorkers int32 `json:"pendingDeleteWorkers,omitempty"`
	// Effective worker count after pending create/delete adjustments.
	EffectiveWorkers int32 `json:"effectiveWorkers,omitempty"`
	// Worker creations enqueued by this reconcile.
	WorkersToCreate int32 `json:"workersToCreate,omitempty"`
	// Worker deletions enqueued by this reconcile.
	WorkersToDelete int32 `json:"workersToDelete,omitempty"`
	// Latest planner action label.
	LastAction string `json:"lastAction,omitempty"`
	// Human-readable explanation for the latest planner action.
	LastReason string `json:"lastReason,omitempty"`
	// Active worker operations after executor reconciliation.
	ActiveOperations []WorkerOperationStatus `json:"activeOperations,omitempty"`
}

type WorkerPrototypeStatus struct {
	// Latest desired worker count requested by the prototype.
	TargetWorkerCount int32 `json:"targetWorkerCount,omitempty"`
	// Latest observed count of Ready worker nodes.
	ObservedReadyWorkerCount int32 `json:"observedReadyWorkerCount,omitempty"`
	// Number of worker creations that have been planned but not yet observed as Ready.
	PendingCreateCount int32 `json:"pendingCreateCount,omitempty"`
	// Number of worker deletions that have been planned but not yet observed as gone.
	PendingDeleteCount int32 `json:"pendingDeleteCount,omitempty"`
	// Effective worker count used by ensure_worker = ready + pendingCreate - pendingDelete.
	EffectiveWorkerCount int32 `json:"effectiveWorkerCount,omitempty"`
	// Last prototype action taken: enqueue-create, enqueue-delete, or stable.
	LastAction string `json:"lastAction,omitempty"`
	// Human-readable explanation for the last prototype action.
	LastReason string `json:"lastReason,omitempty"`
	// Last time the prototype worker planner ran.
	LastEnsureTime *metav1.Time `json:"lastEnsureTime,omitempty"`
	// In-flight worker operations managed by the prototype executor.
	ActiveOperations []WorkerOperationStatus `json:"activeOperations,omitempty"`
	// Legacy single-operation mirror kept for backwards-compatible status transitions.
	// New logic should use ActiveOperations.
	ActiveOperation *WorkerOperationStatus `json:"activeOperation,omitempty"`
}

type WorkerOperationStatus struct {
	// Type of worker operation: create or delete.
	OperationType string `json:"operationType,omitempty"`
	// Concrete node name passed to the executor. For create, this is the planned new node name.
	// For delete, this is the node selected for eviction and teardown.
	TargetNodeName string `json:"targetNodeName,omitempty"`
	// Current executor phase: Running or WaitingForObservation.
	Phase string `json:"phase,omitempty"`
	// Namespace of the Kubernetes Job executing the operation.
	JobNamespace string `json:"jobNamespace,omitempty"`
	// Name of the Kubernetes Job executing the operation.
	JobName string `json:"jobName,omitempty"`
	// Number of workers requested by this operation. The prototype uses 1.
	RequestedCount int32 `json:"requestedCount,omitempty"`
	// Last executor message for humans.
	Message string `json:"message,omitempty"`
	// When the executor started the operation.
	StartedAt *metav1.Time `json:"startedAt,omitempty"`
	// When the executor observed the command job complete.
	CommandFinishedAt *metav1.Time `json:"commandFinishedAt,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status

// CustomScaler is the Schema for the customscalers API
type CustomScaler struct {
	metav1.TypeMeta `json:",inline"`

	// metadata is a standard object metadata
	// +optional
	metav1.ObjectMeta `json:"metadata,omitzero"`

	// spec defines the desired state of CustomScaler
	// +required
	Spec CustomScalerSpec `json:"spec"`

	// status defines the observed state of CustomScaler
	// +optional
	Status CustomScalerStatus `json:"status,omitzero"`
}

// +kubebuilder:object:root=true

// CustomScalerList contains a list of CustomScaler
type CustomScalerList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitzero"`
	Items           []CustomScaler `json:"items"`
}

func init() {
	SchemeBuilder.Register(&CustomScaler{}, &CustomScalerList{})
}
