package controller

import (
	"context"
	"fmt"
	"time"

	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	autoscalingv1 "github.com/Boygioi15/predictive-autoscaling-k8s-test/api/v1"
)

const defaultWorkerPrototypeBatchSize int32 = 1

type workerPrototypePlan struct {
	Status          autoscalingv1.WorkerPrototypeStatus
	WorkersToCreate int32
	WorkersToDelete int32
}

func (r *CustomScalerReconciler) reconcileWorkerPrototype(
	ctx context.Context,
	customScaler *autoscalingv1.CustomScaler,
	now time.Time,
) (*workerPrototypePlan, error) {
	spec := customScaler.Spec.WorkerPrototype
	if spec == nil || spec.TargetWorkerCount == nil {
		return nil, nil
	}

	observedReady, err := r.countReadyWorkerNodes(ctx, spec)
	if err != nil {
		return nil, err
	}

	plan := ensureWorkers(spec, customScaler.Status.WorkerPrototype, observedReady, now)
	return &plan, nil
}

func (r *CustomScalerReconciler) countReadyWorkerNodes(ctx context.Context, spec *autoscalingv1.WorkerPrototypeSpec) (int32, error) {
	var nodeList corev1.NodeList
	if err := r.List(ctx, &nodeList); err != nil {
		return 0, err
	}

	var count int32
	for _, node := range nodeList.Items {
		if _, isControlPlane := node.Labels["node-role.kubernetes.io/control-plane"]; isControlPlane {
			continue
		}

		if spec.NodeLabelKey != "" {
			value, exists := node.Labels[spec.NodeLabelKey]
			if !exists {
				continue
			}
			if spec.NodeLabelValue != "" && value != spec.NodeLabelValue {
				continue
			}
		}

		if isNodeReady(&node) {
			count++
		}
	}

	return count, nil
}

func ensureWorkers(
	spec *autoscalingv1.WorkerPrototypeSpec,
	current *autoscalingv1.WorkerPrototypeStatus,
	observedReady int32,
	now time.Time,
) workerPrototypePlan {
	maxBatchSize := defaultWorkerPrototypeBatchSize
	if spec.MaxBatchSize != nil && *spec.MaxBatchSize > 0 {
		maxBatchSize = *spec.MaxBatchSize
	}

	targetWorkerCount := *spec.TargetWorkerCount
	status := autoscalingv1.WorkerPrototypeStatus{}
	if current != nil {
		status = *current
		if current.ActiveOperation != nil {
			activeOperationCopy := *current.ActiveOperation
			status.ActiveOperation = &activeOperationCopy
		}
	}

	pendingCreate := status.PendingCreateCount
	pendingDelete := status.PendingDeleteCount
	baseEffectiveWorkerCount := observedReady + pendingCreate - pendingDelete

	switch {
	case observedReady > status.ObservedReadyWorkerCount:
		completedCreates := minInt32(pendingCreate, observedReady-status.ObservedReadyWorkerCount)
		pendingCreate -= completedCreates
	case observedReady < status.ObservedReadyWorkerCount:
		completedDeletes := minInt32(pendingDelete, status.ObservedReadyWorkerCount-observedReady)
		pendingDelete -= completedDeletes
	}

	effectiveWorkerCount := observedReady + pendingCreate - pendingDelete
	workersToCreate := int32(0)
	workersToDelete := int32(0)
	lastAction := "stable"
	lastReason := "target-satisfied"

	delta := targetWorkerCount - effectiveWorkerCount
	switch {
	case delta > 0:
		workersToCreate = minInt32(delta, maxBatchSize)
		pendingCreate += workersToCreate
		effectiveWorkerCount += workersToCreate
		lastAction = "enqueue-create"
		lastReason = fmt.Sprintf("target=%d effective=%d missing=%d", targetWorkerCount, baseEffectiveWorkerCount, delta)
	case delta < 0:
		workersToDelete = minInt32(-delta, maxBatchSize)
		pendingDelete += workersToDelete
		effectiveWorkerCount -= workersToDelete
		lastAction = "enqueue-delete"
		lastReason = fmt.Sprintf("target=%d effective=%d excess=%d", targetWorkerCount, baseEffectiveWorkerCount, -delta)
	}

	ensureTime := metav1.NewTime(now)
	status.TargetWorkerCount = targetWorkerCount
	status.ObservedReadyWorkerCount = observedReady
	status.PendingCreateCount = pendingCreate
	status.PendingDeleteCount = pendingDelete
	status.EffectiveWorkerCount = effectiveWorkerCount
	status.LastAction = lastAction
	status.LastReason = lastReason
	status.LastEnsureTime = &ensureTime

	return workerPrototypePlan{
		Status:          status,
		WorkersToCreate: workersToCreate,
		WorkersToDelete: workersToDelete,
	}
}

func isNodeReady(node *corev1.Node) bool {
	for _, condition := range node.Status.Conditions {
		if condition.Type == corev1.NodeReady && condition.Status == corev1.ConditionTrue {
			return true
		}
	}

	return false
}

func minInt32(a, b int32) int32 {
	if a < b {
		return a
	}

	return b
}
