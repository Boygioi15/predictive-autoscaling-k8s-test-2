package controller

import (
	"context"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	autoscalingv1 "github.com/Boygioi15/predictive-autoscaling-k8s-test/api/v1"
)

func TestResolveWorkerTargetCountDirectDivideUsesDesiredSafetyAndUnschedulablePods(t *testing.T) {
	reconciler, deployment := newWorkerCapacityTestReconciler(
		t,
		WorkerCapacityDefaults{
			NodeAllocatableMilliCPU: 1800,
			PodRequestMilliCPU:      600,
			SafetyPods:              1,
			CapacityStrategy:        "direct-divide",
			MinWorkerCount:          0,
			MaxWorkerCount:          0,
		},
		newUnschedulableAppPod("prime-a"),
		newUnschedulableAppPod("prime-b"),
		newScheduledAppPod("prime-running", "k3s-worker-1", 600),
	)

	customScaler := &autoscalingv1.CustomScaler{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "prime-scaler",
			Namespace: "default",
		},
		Spec: autoscalingv1.CustomScalerSpec{
			DeploymentName: "prime-service-deployment",
			WorkerPrototype: &autoscalingv1.WorkerPrototypeSpec{
				MaxBatchSize: int32Ptr(1),
			},
		},
	}

	target, err := reconciler.resolveWorkerTargetCount(context.Background(), customScaler, deployment, 4)
	if err != nil {
		t.Fatalf("resolveWorkerTargetCount returned error: %v", err)
	}

	if target.Mode != "auto" {
		t.Fatalf("expected auto mode, got %q", target.Mode)
	}
	if target.Strategy != "direct-divide" {
		t.Fatalf("expected direct-divide strategy, got %q", target.Strategy)
	}
	if target.UnschedulablePods != 2 {
		t.Fatalf("expected 2 unschedulable pods, got %d", target.UnschedulablePods)
	}
	if target.PodsPerWorker != 3 {
		t.Fatalf("expected 3 pods per worker, got %d", target.PodsPerWorker)
	}
	if target.DesiredPodsForCapacity != 7 {
		t.Fatalf("expected desired pods for capacity to be 7, got %d", target.DesiredPodsForCapacity)
	}
	if target.TargetWorkerCount != 3 {
		t.Fatalf("expected target worker count to be 3, got %d", target.TargetWorkerCount)
	}
	if target.RawTargetWorkerCount != 3 {
		t.Fatalf("expected raw target worker count to be 3, got %d", target.RawTargetWorkerCount)
	}
}

func TestResolveWorkerTargetCountFreeSlotsScalesUpWhenCurrentWorkersCannotFitDesiredPods(t *testing.T) {
	reconciler, deployment := newWorkerCapacityTestReconciler(
		t,
		WorkerCapacityDefaults{
			NodeAllocatableMilliCPU: 1800,
			PodRequestMilliCPU:      600,
			SafetyPods:              1,
			CapacityStrategy:        "free-slots",
			MinWorkerCount:          0,
			MaxWorkerCount:          0,
		},
		newReadyWorkerNode("k3s-worker-1", "1800m"),
		newReadyWorkerNode("k3s-worker-2", "1800m"),
		newScheduledAppPod("prime-1", "k3s-worker-1", 600),
		newScheduledAppPod("prime-2", "k3s-worker-2", 600),
		newScheduledSystemPod("ingress-a", "k3s-worker-1", 600),
		newScheduledSystemPod("ingress-b", "k3s-worker-2", 1200),
	)

	customScaler := &autoscalingv1.CustomScaler{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "prime-scaler",
			Namespace: "default",
		},
		Spec: autoscalingv1.CustomScalerSpec{
			DeploymentName: "prime-service-deployment",
			WorkerPrototype: &autoscalingv1.WorkerPrototypeSpec{
				MaxBatchSize: int32Ptr(1),
			},
		},
	}

	target, err := reconciler.resolveWorkerTargetCount(context.Background(), customScaler, deployment, 3)
	if err != nil {
		t.Fatalf("resolveWorkerTargetCount returned error: %v", err)
	}

	if target.Strategy != "free-slots" {
		t.Fatalf("expected free-slots strategy, got %q", target.Strategy)
	}
	if target.ReadyWorkerCount != 2 {
		t.Fatalf("expected 2 ready workers, got %d", target.ReadyWorkerCount)
	}
	if target.CurrentAppScheduledPods != 2 {
		t.Fatalf("expected 2 scheduled app pods, got %d", target.CurrentAppScheduledPods)
	}
	if target.TotalAppSlotCapacity != 3 {
		t.Fatalf("expected total app slot capacity 3, got %d", target.TotalAppSlotCapacity)
	}
	if target.MissingAppSlots != 1 {
		t.Fatalf("expected 1 missing app slot, got %d", target.MissingAppSlots)
	}
	if target.TargetWorkerCount != 3 {
		t.Fatalf("expected target worker count 3, got %d", target.TargetWorkerCount)
	}
}

func TestResolveWorkerTargetCountFreeSlotsScalesDownUsingNodeAwareCapacity(t *testing.T) {
	reconciler, deployment := newWorkerCapacityTestReconciler(
		t,
		WorkerCapacityDefaults{
			NodeAllocatableMilliCPU: 1800,
			PodRequestMilliCPU:      600,
			SafetyPods:              1,
			CapacityStrategy:        "free-slots",
			MinWorkerCount:          0,
			MaxWorkerCount:          0,
		},
		newReadyWorkerNode("k3s-worker-1", "1800m"),
		newReadyWorkerNode("k3s-worker-2", "1800m"),
		newReadyWorkerNode("k3s-worker-3", "1800m"),
		newScheduledAppPod("prime-1", "k3s-worker-1", 600),
		newScheduledAppPod("prime-2", "k3s-worker-2", 600),
		newScheduledSystemPod("ingress-a", "k3s-worker-1", 0),
		newScheduledSystemPod("ingress-b", "k3s-worker-2", 600),
		newScheduledSystemPod("ingress-c", "k3s-worker-3", 1200),
	)

	customScaler := &autoscalingv1.CustomScaler{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "prime-scaler",
			Namespace: "default",
		},
		Spec: autoscalingv1.CustomScalerSpec{
			DeploymentName: "prime-service-deployment",
			WorkerPrototype: &autoscalingv1.WorkerPrototypeSpec{
				MaxBatchSize: int32Ptr(1),
			},
		},
	}

	target, err := reconciler.resolveWorkerTargetCount(context.Background(), customScaler, deployment, 3)
	if err != nil {
		t.Fatalf("resolveWorkerTargetCount returned error: %v", err)
	}

	if target.TotalAppSlotCapacity != 6 {
		t.Fatalf("expected total app slot capacity 6, got %d", target.TotalAppSlotCapacity)
	}
	if target.RequiredReadyWorkers != 2 {
		t.Fatalf("expected 2 required ready workers, got %d", target.RequiredReadyWorkers)
	}
	if target.MissingAppSlots != 0 {
		t.Fatalf("expected 0 missing app slots, got %d", target.MissingAppSlots)
	}
	if target.TargetWorkerCount != 2 {
		t.Fatalf("expected target worker count 2, got %d", target.TargetWorkerCount)
	}
}

func TestResolveWorkerTargetCountManualModeWinsOverAutoComputation(t *testing.T) {
	reconciler := &CustomScalerControllerBase{
		WorkerCapacityDefaults: WorkerCapacityDefaults{
			NodeAllocatableMilliCPU: 1800,
			PodRequestMilliCPU:      600,
			SafetyPods:              1,
			CapacityStrategy:        "free-slots",
			MinWorkerCount:          0,
			MaxWorkerCount:          0,
		},
	}

	customScaler := &autoscalingv1.CustomScaler{
		Spec: autoscalingv1.CustomScalerSpec{
			WorkerPrototype: &autoscalingv1.WorkerPrototypeSpec{
				TargetWorkerCount: int32Ptr(5),
			},
		},
	}

	target, err := reconciler.resolveWorkerTargetCount(context.Background(), customScaler, &appsv1.Deployment{}, 4)
	if err != nil {
		t.Fatalf("resolveWorkerTargetCount returned error: %v", err)
	}

	if target.Mode != "manual" {
		t.Fatalf("expected manual mode, got %q", target.Mode)
	}
	if target.TargetWorkerCount != 5 {
		t.Fatalf("expected manual target worker count 5, got %d", target.TargetWorkerCount)
	}
	if target.RawTargetWorkerCount != 5 {
		t.Fatalf("expected raw manual target worker count 5, got %d", target.RawTargetWorkerCount)
	}
}

func TestResolveWorkerTargetCountDirectDivideHonorsMinWorkerCount(t *testing.T) {
	reconciler, deployment := newWorkerCapacityTestReconciler(
		t,
		WorkerCapacityDefaults{
			NodeAllocatableMilliCPU: 1800,
			PodRequestMilliCPU:      600,
			SafetyPods:              0,
			CapacityStrategy:        "direct-divide",
			MinWorkerCount:          2,
			MaxWorkerCount:          0,
		},
	)

	customScaler := &autoscalingv1.CustomScaler{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "prime-scaler",
			Namespace: "default",
		},
		Spec: autoscalingv1.CustomScalerSpec{
			DeploymentName: "prime-service-deployment",
			WorkerPrototype: &autoscalingv1.WorkerPrototypeSpec{
				MaxBatchSize: int32Ptr(1),
			},
		},
	}

	target, err := reconciler.resolveWorkerTargetCount(context.Background(), customScaler, deployment, 1)
	if err != nil {
		t.Fatalf("resolveWorkerTargetCount returned error: %v", err)
	}

	if target.RawTargetWorkerCount != 1 {
		t.Fatalf("expected raw target worker count 1, got %d", target.RawTargetWorkerCount)
	}
	if target.TargetWorkerCount != 2 {
		t.Fatalf("expected clamped target worker count 2, got %d", target.TargetWorkerCount)
	}
}

func TestResolveWorkerTargetCountManualModeHonorsMaxWorkerCount(t *testing.T) {
	reconciler := &CustomScalerControllerBase{
		WorkerCapacityDefaults: WorkerCapacityDefaults{
			NodeAllocatableMilliCPU: 1800,
			PodRequestMilliCPU:      600,
			SafetyPods:              1,
			CapacityStrategy:        "free-slots",
			MinWorkerCount:          0,
			MaxWorkerCount:          4,
		},
	}

	customScaler := &autoscalingv1.CustomScaler{
		Spec: autoscalingv1.CustomScalerSpec{
			WorkerPrototype: &autoscalingv1.WorkerPrototypeSpec{
				TargetWorkerCount: int32Ptr(6),
			},
		},
	}

	target, err := reconciler.resolveWorkerTargetCount(context.Background(), customScaler, &appsv1.Deployment{}, 4)
	if err != nil {
		t.Fatalf("resolveWorkerTargetCount returned error: %v", err)
	}

	if target.RawTargetWorkerCount != 6 {
		t.Fatalf("expected raw manual target worker count 6, got %d", target.RawTargetWorkerCount)
	}
	if target.TargetWorkerCount != 4 {
		t.Fatalf("expected clamped manual target worker count 4, got %d", target.TargetWorkerCount)
	}
}

func newWorkerCapacityTestReconciler(
	t *testing.T,
	defaults WorkerCapacityDefaults,
	objects ...runtime.Object,
) (*CustomScalerControllerBase, *appsv1.Deployment) {
	t.Helper()

	scheme := runtime.NewScheme()
	if err := clientgoscheme.AddToScheme(scheme); err != nil {
		t.Fatalf("failed to add core scheme: %v", err)
	}
	if err := autoscalingv1.AddToScheme(scheme); err != nil {
		t.Fatalf("failed to add autoscaling scheme: %v", err)
	}

	deployment := newTestDeployment()
	allObjects := append([]runtime.Object{deployment}, objects...)

	reconciler := &CustomScalerControllerBase{
		Client: fake.NewClientBuilder().
			WithScheme(scheme).
			WithRuntimeObjects(allObjects...).
			Build(),
		WorkerCapacityDefaults: defaults,
	}

	return reconciler, deployment
}

func newTestDeployment() *appsv1.Deployment {
	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "prime-service-deployment",
			Namespace: "default",
		},
		Spec: appsv1.DeploymentSpec{
			Selector: &metav1.LabelSelector{
				MatchLabels: map[string]string{"app": "prime-service"},
			},
		},
	}
}

func newReadyWorkerNode(name string, allocatableCPU string) *corev1.Node {
	return &corev1.Node{
		ObjectMeta: metav1.ObjectMeta{
			Name: name,
		},
		Status: corev1.NodeStatus{
			Allocatable: corev1.ResourceList{
				corev1.ResourceCPU: resource.MustParse(allocatableCPU),
			},
			Conditions: []corev1.NodeCondition{
				{
					Type:   corev1.NodeReady,
					Status: corev1.ConditionTrue,
				},
			},
		},
	}
}

func newUnschedulableAppPod(name string) *corev1.Pod {
	return &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: "default",
			Labels:    map[string]string{"app": "prime-service"},
		},
		Status: corev1.PodStatus{
			Phase: corev1.PodPending,
			Conditions: []corev1.PodCondition{
				{
					Type:   corev1.PodScheduled,
					Status: corev1.ConditionFalse,
					Reason: corev1.PodReasonUnschedulable,
				},
			},
		},
	}
}

func newScheduledAppPod(name, nodeName string, requestMilliCPU int32) *corev1.Pod {
	pod := newScheduledSystemPod(name, nodeName, requestMilliCPU)
	pod.Namespace = "default"
	pod.Labels = map[string]string{"app": "prime-service"}
	return pod
}

func newScheduledSystemPod(name, nodeName string, requestMilliCPU int32) *corev1.Pod {
	pod := &corev1.Pod{
		ObjectMeta: metav1.ObjectMeta{
			Name:      name,
			Namespace: "kube-system",
			Labels:    map[string]string{"app": "system"},
		},
		Spec: corev1.PodSpec{
			NodeName: nodeName,
			Containers: []corev1.Container{
				{
					Name: "main",
					Resources: corev1.ResourceRequirements{
						Requests: corev1.ResourceList{
							corev1.ResourceCPU: *resource.NewMilliQuantity(int64(requestMilliCPU), resource.DecimalSI),
						},
					},
				},
			},
		},
		Status: corev1.PodStatus{
			Phase: corev1.PodRunning,
		},
	}

	return pod
}
