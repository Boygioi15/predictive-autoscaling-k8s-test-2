package controller

import (
	"fmt"
	"strings"

	autoscalingv1 "github.com/Boygioi15/predictive-autoscaling-k8s-test/api/v1"
)

func cloneActiveOperations(status *autoscalingv1.WorkerPrototypeStatus) []autoscalingv1.WorkerOperationStatus {
	if status == nil {
		return nil
	}

	if len(status.ActiveOperations) > 0 {
		cloned := make([]autoscalingv1.WorkerOperationStatus, 0, len(status.ActiveOperations))
		for _, operation := range status.ActiveOperations {
			cloned = append(cloned, *operation.DeepCopy())
		}
		return cloned
	}

	if status.ActiveOperation != nil {
		return []autoscalingv1.WorkerOperationStatus{*status.ActiveOperation.DeepCopy()}
	}

	return nil
}

func syncLegacyActiveOperation(status *autoscalingv1.WorkerPrototypeStatus) {
	if status == nil {
		return
	}

	if len(status.ActiveOperations) == 0 {
		status.ActiveOperation = nil
		return
	}

	legacyCopy := status.ActiveOperations[0]
	status.ActiveOperation = &legacyCopy
}

func activeOperationRequestedCount(operation autoscalingv1.WorkerOperationStatus) int32 {
	if operation.RequestedCount > 0 {
		return operation.RequestedCount
	}
	return 1
}

func sumActiveOperationCounts(operations []autoscalingv1.WorkerOperationStatus) (int32, int32) {
	var createCount int32
	var deleteCount int32

	for _, operation := range operations {
		requestedCount := activeOperationRequestedCount(operation)
		switch operation.OperationType {
		case workerOperationCreate:
			createCount += requestedCount
		case workerOperationDelete:
			deleteCount += requestedCount
		}
	}

	return createCount, deleteCount
}

func activeOperationSlicesChanged(current, next []autoscalingv1.WorkerOperationStatus) bool {
	if len(current) != len(next) {
		return true
	}

	for index := range current {
		if workerOperationChanged(&current[index], &next[index]) {
			return true
		}
	}

	return false
}

func formatActiveOperationSummary(operations []autoscalingv1.WorkerOperationStatus) string {
	if len(operations) == 0 {
		return "none"
	}

	parts := make([]string, 0, len(operations))
	for _, operation := range operations {
		parts = append(parts, fmt.Sprintf("%s:%s:%s", operation.OperationType, operation.TargetNodeName, operation.Phase))
	}

	return strings.Join(parts, ", ")
}
