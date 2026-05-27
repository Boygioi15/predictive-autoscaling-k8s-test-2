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
	// Polling interval in minutes. Defaults to 1 minute when omitted or invalid.
	IntervalMinutes int `json:"intervalMinutes,omitempty"`
	// Optional Prometheus query override forwarded to the forecasting service.
	PrometheusQuery string `json:"prometheusQuery,omitempty"`
	// Optional metric name forwarded to the forecasting service.
	TargetMetricName string `json:"targetMetricName,omitempty"`
}

type CustomScalerStatus struct {
	// The last value received from the endpoint
	LastValue int `json:"lastValue"`
	// Current replica count
	CurrentReplicas int32 `json:"currentReplicas"`
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
