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
	// Desired number of worker nodes the prototype should converge toward.
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
	// Durable worker-planning state for the prototype node scaler.
	WorkerPrototype *WorkerPrototypeStatus `json:"workerPrototype,omitempty"`
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
	// Optional single in-flight worker operation managed by the prototype executor.
	ActiveOperation *WorkerOperationStatus `json:"activeOperation,omitempty"`
}

type WorkerOperationStatus struct {
	// Type of worker operation: create or delete.
	OperationType string `json:"operationType,omitempty"`
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
