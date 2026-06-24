package controller

import (
	"context"
	"fmt"
	"time"

	appsv1 "k8s.io/api/apps/v1"
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

func (r *CustomScalerControllerBase) reconcileWorkerPrototype(
	ctx context.Context,
	customScaler *autoscalingv1.CustomScaler,
	deployment *appsv1.Deployment,
	desiredReplicas int32,
	additionalWorkerTarget int32,
	now time.Time,
) (*workerPrototypePlan, workerTargetComputation, error) {
	spec := customScaler.Spec.WorkerPrototype
	if spec == nil {
		return nil, workerTargetComputation{}, nil
	}

	target, err := r.resolveWorkerTargetCount(ctx, customScaler, deployment, desiredReplicas)
	if err != nil {
		return nil, workerTargetComputation{}, err
	}
	// disable the node scaling bump
	// if additionalWorkerTarget > 0 {
	// 	target.RawTargetWorkerCount += additionalWorkerTarget
	// 	target.TargetWorkerCount += additionalWorkerTarget
	// 	target = applyWorkerTargetBounds(target, r.WorkerCapacityDefaults.normalized())
	// }

	effectiveSpec := spec.DeepCopy()
	effectiveSpec.TargetWorkerCount = &target.TargetWorkerCount

	observedReady, err := r.countReadyWorkerNodes(ctx, effectiveSpec)
	if err != nil {
		return nil, workerTargetComputation{}, err
	}

	plan := ensureWorkers(
		effectiveSpec,
		customScaler.Status.WorkerPrototype,
		observedReady,
		target.UnschedulablePods,
		r.WorkerExecutor.MaxConcurrentCreateOps,
		r.WorkerExecutor.MaxConcurrentDeleteOps,
		now,
	)
	return &plan, target, nil
}

func (r *CustomScalerControllerBase) countReadyWorkerNodes(ctx context.Context, spec *autoscalingv1.WorkerPrototypeSpec) (int32, error) {
	nodes, err := r.listManagedWorkerNodes(ctx, spec)
	if err != nil {
		return 0, err
	}

	var count int32
	for _, node := range nodes {
		if isNodeReady(&node) {
			count++
		}
	}

	return count, nil
}

func (r *CustomScalerControllerBase) listManagedWorkerNodes(ctx context.Context, spec *autoscalingv1.WorkerPrototypeSpec) ([]corev1.Node, error) {
	var nodeList corev1.NodeList
	if err := r.List(ctx, &nodeList); err != nil {
		return nil, err
	}

	nodes := make([]corev1.Node, 0, len(nodeList.Items))
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

		nodes = append(nodes, node)
	}

	return nodes, nil
}

func ensureWorkers(
	spec *autoscalingv1.WorkerPrototypeSpec,
	current *autoscalingv1.WorkerPrototypeStatus,
	observedReady int32,
	unschedulablePods int32,
	maxConcurrentCreateOps int32,
	maxConcurrentDeleteOps int32,
	now time.Time,
) workerPrototypePlan {
	if maxConcurrentCreateOps <= 0 {
		maxConcurrentCreateOps = 1
	}
	if maxConcurrentDeleteOps <= 0 {
		maxConcurrentDeleteOps = 1
	}

	maxBatchSize := maxConcurrentCreateOps
	if maxConcurrentDeleteOps > maxBatchSize {
		maxBatchSize = maxConcurrentDeleteOps
	}
	if spec.MaxBatchSize != nil && *spec.MaxBatchSize > 0 {
		maxBatchSize = *spec.MaxBatchSize
	}

	targetWorkerCount := *spec.TargetWorkerCount
	status := autoscalingv1.WorkerPrototypeStatus{}
	if current != nil {
		status = *current
		status.ActiveOperations = cloneActiveOperations(current)
	}

	rawActiveCreateCount, rawActiveDeleteCount := sumActiveOperationCounts(status.ActiveOperations)
	pendingCreate := rawActiveCreateCount
	pendingDelete := rawActiveDeleteCount

	previousObservedReady := int32(0)
	if current != nil {
		previousObservedReady = current.ObservedReadyWorkerCount
	}

	completedCreateObservations := int32(0)
	completedDeleteObservations := int32(0)
	switch {
	case observedReady > previousObservedReady:
		completedCreateObservations = minInt32(pendingCreate, observedReady-previousObservedReady)
		pendingCreate -= completedCreateObservations
	case observedReady < previousObservedReady:
		completedDeleteObservations = minInt32(pendingDelete, previousObservedReady-observedReady)
		pendingDelete -= completedDeleteObservations
	}

	activeCreateSlotsUsed := maxInt32(rawActiveCreateCount-completedCreateObservations, 0)
	activeDeleteSlotsUsed := maxInt32(rawActiveDeleteCount-completedDeleteObservations, 0)

	effectiveWorkerCount := observedReady + pendingCreate - pendingDelete
	workersToCreate := int32(0)
	workersToDelete := int32(0)
	lastAction := "stable"
	lastReason := "target-satisfied"
	baseEffectiveWorkerCount := effectiveWorkerCount

	if len(status.ActiveOperations) > 0 {
		lastAction = "waiting-active-operation"
		lastReason = fmt.Sprintf(
			"waiting for active worker operations to finish observation: %s",
			formatActiveOperationSummary(status.ActiveOperations),
		)
	}

	delta := targetWorkerCount - effectiveWorkerCount
	switch {
	case delta > 0:
		if activeDeleteSlotsUsed > 0 {
			lastAction = "waiting-active-operation"
			lastReason = fmt.Sprintf("delete operations in flight block new creates: activeDelete=%d", activeDeleteSlotsUsed)
			break
		}

		availableCreateSlots := maxInt32(maxConcurrentCreateOps-activeCreateSlotsUsed, 0)
		if availableCreateSlots <= 0 {
			lastAction = "waiting-active-operation"
			lastReason = fmt.Sprintf("create slots saturated: activeCreate=%d limit=%d target=%d effective=%d missing=%d", activeCreateSlotsUsed, maxConcurrentCreateOps, targetWorkerCount, baseEffectiveWorkerCount, delta)
			break
		}

		workersToCreate = minInt32(delta, minInt32(maxBatchSize, availableCreateSlots))
		if workersToCreate > 0 {
			pendingCreate += workersToCreate
			effectiveWorkerCount += workersToCreate
			lastAction = "enqueue-create"
			lastReason = fmt.Sprintf("target=%d effective=%d missing=%d", targetWorkerCount, baseEffectiveWorkerCount, delta)
		}
	case delta < 0:
		if activeCreateSlotsUsed > 0 {
			lastAction = "waiting-active-operation"
			lastReason = fmt.Sprintf("create operations in flight block new deletes: activeCreate=%d", activeCreateSlotsUsed)
			break
		}
		if unschedulablePods > 0 {
			lastAction = "blocked-unschedulable-pods"
			lastReason = fmt.Sprintf("unschedulable pods present block deletes: unschedulablePods=%d", unschedulablePods)
			break
		}

		availableDeleteSlots := maxInt32(maxConcurrentDeleteOps-activeDeleteSlotsUsed, 0)
		if availableDeleteSlots <= 0 {
			lastAction = "waiting-active-operation"
			lastReason = fmt.Sprintf("delete slots saturated: activeDelete=%d limit=%d target=%d effective=%d excess=%d", activeDeleteSlotsUsed, maxConcurrentDeleteOps, targetWorkerCount, baseEffectiveWorkerCount, -delta)
			break
		}

		workersToDelete = minInt32(-delta, minInt32(maxBatchSize, availableDeleteSlots))
		if workersToDelete > 0 {
			pendingDelete += workersToDelete
			effectiveWorkerCount -= workersToDelete
			lastAction = "enqueue-delete"
			lastReason = fmt.Sprintf("target=%d effective=%d excess=%d", targetWorkerCount, baseEffectiveWorkerCount, -delta)
		}
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
	syncLegacyActiveOperation(&status)

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

func maxInt32(a, b int32) int32 {
	if a > b {
		return a
	}

	return b
}

func minInt32(a, b int32) int32 {
	if a < b {
		return a
	}

	return b
}
