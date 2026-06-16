package controller

import (
	"context"
	"fmt"
	"math"
	"sort"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/labels"
	"sigs.k8s.io/controller-runtime/pkg/client"

	autoscalingv1 "github.com/Boygioi15/predictive-autoscaling-k8s-test/api/v1"
)

type workerTargetComputation struct {
	Mode                    string
	Strategy                string
	TargetWorkerCount       int32
	RawTargetWorkerCount    int32
	DesiredReplicas         int32
	UnschedulablePods       int32
	SafetyPods              int32
	DesiredPodsForCapacity  int32
	NodeAllocatableMilliCPU int32
	PodRequestMilliCPU      int32
	PodsPerWorker           int32
	MinWorkerCount          int32
	MaxWorkerCount          int32
	ReadyWorkerCount        int32
	CurrentAppScheduledPods int32
	TotalAppSlotCapacity    int32
	MissingAppSlots         int32
	RequiredReadyWorkers    int32
}

type workerNodeCapacitySnapshot struct {
	NodeName            string
	AllocatableMilliCPU int32
	ReservedMilliCPU    int32
	AppSlots            int32
}

func (r *CustomScalerReconciler) resolveWorkerTargetCount(
	ctx context.Context,
	customScaler *autoscalingv1.CustomScaler,
	deployment *appsv1.Deployment,
	desiredReplicas int32,
) (workerTargetComputation, error) {
	spec := customScaler.Spec.WorkerPrototype
	if spec == nil {
		return workerTargetComputation{}, fmt.Errorf("worker prototype spec is nil")
	}

	if spec.TargetWorkerCount != nil {
		target := workerTargetComputation{
			Mode:                 "manual",
			Strategy:             "manual-override",
			TargetWorkerCount:    *spec.TargetWorkerCount,
			RawTargetWorkerCount: *spec.TargetWorkerCount,
			DesiredReplicas:      desiredReplicas,
		}
		return applyWorkerTargetBounds(target, r.WorkerCapacityDefaults.normalized()), nil
	}

	defaults := r.WorkerCapacityDefaults.normalized()
	unschedulablePods, err := r.countUnschedulableDeploymentPods(ctx, deployment)
	if err != nil {
		return workerTargetComputation{}, err
	}

	podsPerWorker := defaults.NodeAllocatableMilliCPU / defaults.PodRequestMilliCPU
	if podsPerWorker <= 0 {
		podsPerWorker = 1
	}

	desiredPodsForCapacity := max(desiredReplicas+defaults.SafetyPods+unschedulablePods, 0)

	base := workerTargetComputation{
		Mode:                    "auto",
		Strategy:                defaults.CapacityStrategy,
		DesiredReplicas:         desiredReplicas,
		UnschedulablePods:       unschedulablePods,
		SafetyPods:              defaults.SafetyPods,
		DesiredPodsForCapacity:  desiredPodsForCapacity,
		NodeAllocatableMilliCPU: defaults.NodeAllocatableMilliCPU,
		PodRequestMilliCPU:      defaults.PodRequestMilliCPU,
		PodsPerWorker:           podsPerWorker,
		MinWorkerCount:          defaults.MinWorkerCount,
		MaxWorkerCount:          defaults.MaxWorkerCount,
	}

	switch defaults.CapacityStrategy {
	case "free-slots":
		target, err := r.resolveWorkerTargetCountByFreeSlots(ctx, spec, deployment, base)
		if err != nil {
			return workerTargetComputation{}, err
		}
		return applyWorkerTargetBounds(target, defaults), nil
	case "direct-divide":
		fallthrough
	default:
		return applyWorkerTargetBounds(resolveWorkerTargetCountByDirectDivide(base), defaults), nil
	}
}

func resolveWorkerTargetCountByDirectDivide(base workerTargetComputation) workerTargetComputation {
	if base.DesiredPodsForCapacity > 0 {
		base.TargetWorkerCount = int32(math.Ceil(float64(base.DesiredPodsForCapacity) / float64(base.PodsPerWorker)))
	}
	base.RawTargetWorkerCount = base.TargetWorkerCount

	return base
}

func (r *CustomScalerReconciler) resolveWorkerTargetCountByFreeSlots(
	ctx context.Context,
	spec *autoscalingv1.WorkerPrototypeSpec,
	deployment *appsv1.Deployment,
	base workerTargetComputation,
) (workerTargetComputation, error) {
	selector, err := metav1.LabelSelectorAsSelector(deployment.Spec.Selector)
	if err != nil {
		return workerTargetComputation{}, err
	}

	nodes, err := r.listManagedWorkerNodes(ctx, spec)
	if err != nil {
		return workerTargetComputation{}, err
	}

	var podList corev1.PodList
	if err := r.List(ctx, &podList); err != nil {
		return workerTargetComputation{}, err
	}

	snapshots, currentAppScheduledPods := buildWorkerNodeCapacitySnapshots(
		nodes,
		podList.Items,
		selector,
		base.NodeAllocatableMilliCPU,
		base.PodRequestMilliCPU,
	)

	base.CurrentAppScheduledPods = currentAppScheduledPods
	base.ReadyWorkerCount = int32(len(snapshots))

	for _, snapshot := range snapshots {
		base.TotalAppSlotCapacity += snapshot.AppSlots
	}

	if base.DesiredPodsForCapacity <= 0 {
		return base, nil
	}

	sort.Slice(snapshots, func(i, j int) bool {
		if snapshots[i].AppSlots != snapshots[j].AppSlots {
			return snapshots[i].AppSlots > snapshots[j].AppSlots
		}
		return snapshots[i].NodeName < snapshots[j].NodeName
	})

	remaining := base.DesiredPodsForCapacity
	requiredReadyWorkers := int32(0)
	for _, snapshot := range snapshots {
		if remaining <= 0 {
			break
		}
		if snapshot.AppSlots <= 0 {
			continue
		}
		requiredReadyWorkers++
		remaining -= snapshot.AppSlots
	}

	if remaining <= 0 {
		base.RequiredReadyWorkers = requiredReadyWorkers
		base.TargetWorkerCount = requiredReadyWorkers
		base.RawTargetWorkerCount = base.TargetWorkerCount
		return base, nil
	}

	base.RequiredReadyWorkers = base.ReadyWorkerCount
	base.MissingAppSlots = remaining
	base.TargetWorkerCount = base.ReadyWorkerCount + int32(math.Ceil(float64(remaining)/float64(base.PodsPerWorker)))
	base.RawTargetWorkerCount = base.TargetWorkerCount
	return base, nil
}

func applyWorkerTargetBounds(target workerTargetComputation, defaults WorkerCapacityDefaults) workerTargetComputation {
	target.MinWorkerCount = defaults.MinWorkerCount
	target.MaxWorkerCount = defaults.MaxWorkerCount

	if target.TargetWorkerCount < defaults.MinWorkerCount {
		target.TargetWorkerCount = defaults.MinWorkerCount
	}
	if defaults.MaxWorkerCount > 0 && target.TargetWorkerCount > defaults.MaxWorkerCount {
		target.TargetWorkerCount = defaults.MaxWorkerCount
	}

	return target
}

func buildWorkerNodeCapacitySnapshots(
	nodes []corev1.Node,
	pods []corev1.Pod,
	deploymentSelector labels.Selector,
	defaultNodeAllocatableMilliCPU int32,
	appPodRequestMilliCPU int32,
) ([]workerNodeCapacitySnapshot, int32) {
	if appPodRequestMilliCPU <= 0 {
		appPodRequestMilliCPU = 1
	}

	snapshotsByNode := make(map[string]*workerNodeCapacitySnapshot, len(nodes))
	snapshots := make([]workerNodeCapacitySnapshot, 0, len(nodes))

	for _, node := range nodes {
		if !isNodeReady(&node) {
			continue
		}

		allocatableMilliCPU := defaultNodeAllocatableMilliCPU
		if quantity, exists := node.Status.Allocatable[corev1.ResourceCPU]; exists {
			if milliValue := quantity.MilliValue(); milliValue > 0 {
				allocatableMilliCPU = int32(milliValue)
			}
		}

		snapshots = append(snapshots, workerNodeCapacitySnapshot{
			NodeName:            node.Name,
			AllocatableMilliCPU: allocatableMilliCPU,
		})
		snapshotsByNode[node.Name] = &snapshots[len(snapshots)-1]
	}

	var currentAppScheduledPods int32
	for _, pod := range pods {
		if pod.DeletionTimestamp != nil {
			continue
		}
		if pod.Spec.NodeName == "" {
			continue
		}
		if pod.Status.Phase == corev1.PodSucceeded || pod.Status.Phase == corev1.PodFailed {
			continue
		}

		snapshot := snapshotsByNode[pod.Spec.NodeName]
		if snapshot == nil {
			continue
		}

		if deploymentSelector.Matches(labels.Set(pod.Labels)) {
			currentAppScheduledPods++
			continue
		}

		snapshot.ReservedMilliCPU += podRequestedMilliCPU(&pod)
	}

	for i := range snapshots {
		freeMilliCPU := snapshots[i].AllocatableMilliCPU - snapshots[i].ReservedMilliCPU
		if freeMilliCPU < 0 {
			freeMilliCPU = 0
		}
		snapshots[i].AppSlots = freeMilliCPU / appPodRequestMilliCPU
	}

	return snapshots, currentAppScheduledPods
}

func podRequestedMilliCPU(pod *corev1.Pod) int32 {
	if pod == nil {
		return 0
	}

	var total int64
	for _, container := range pod.Spec.Containers {
		total += container.Resources.Requests.Cpu().MilliValue()
	}

	return int32(total)
}

func (r *CustomScalerReconciler) countUnschedulableDeploymentPods(
	ctx context.Context,
	deployment *appsv1.Deployment,
) (int32, error) {
	selector, err := metav1.LabelSelectorAsSelector(deployment.Spec.Selector)
	if err != nil {
		return 0, err
	}

	var podList corev1.PodList
	if err := r.List(
		ctx,
		&podList,
		client.InNamespace(deployment.Namespace),
		client.MatchingLabelsSelector{Selector: selector},
	); err != nil {
		return 0, err
	}

	return countUnschedulablePods(podList.Items), nil
}

func countUnschedulablePods(pods []corev1.Pod) int32 {
	var count int32

	for _, pod := range pods {
		if pod.DeletionTimestamp != nil {
			continue
		}
		if isPodUnschedulable(&pod) {
			count++
		}
	}

	return count
}

func isPodUnschedulable(pod *corev1.Pod) bool {
	if pod == nil {
		return false
	}

	if pod.Spec.NodeName != "" {
		return false
	}

	if pod.Status.Phase != corev1.PodPending {
		return false
	}

	for _, condition := range pod.Status.Conditions {
		if condition.Type == corev1.PodScheduled &&
			condition.Status == corev1.ConditionFalse &&
			condition.Reason == corev1.PodReasonUnschedulable {
			return true
		}
	}

	return false
}
