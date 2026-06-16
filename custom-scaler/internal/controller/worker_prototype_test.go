package controller

import (
	"testing"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	autoscalingv1 "github.com/Boygioi15/predictive-autoscaling-k8s-test/api/v1"
)

func int32Ptr(value int32) *int32 {
	return &value
}

const (
	testMaxConcurrentCreateOps int32 = 1
	testMaxConcurrentDeleteOps int32 = 1
)

func TestEnsureWorkersEnqueuesCreateOnlyOnceAcrossReconciles(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	spec := &autoscalingv1.WorkerPrototypeSpec{
		TargetWorkerCount: int32Ptr(3),
		MaxBatchSize:      int32Ptr(2),
	}

	first := ensureWorkers(spec, nil, 1, 0, testMaxConcurrentCreateOps, testMaxConcurrentDeleteOps, now)
	if first.WorkersToCreate != 1 {
		t.Fatalf("expected first reconcile to enqueue 1 create, got %d", first.WorkersToCreate)
	}
	if first.Status.PendingCreateCount != 1 {
		t.Fatalf("expected pending create count to be 1, got %d", first.Status.PendingCreateCount)
	}
	if first.Status.EffectiveWorkerCount != 2 {
		t.Fatalf("expected effective worker count to be 2, got %d", first.Status.EffectiveWorkerCount)
	}

	first.Status.ActiveOperation = &autoscalingv1.WorkerOperationStatus{
		OperationType:  "create",
		TargetNodeName: "k3s-worker-5",
		Phase:          "Running",
		RequestedCount: 1,
	}

	second := ensureWorkers(spec, &first.Status, 1, 0, testMaxConcurrentCreateOps, testMaxConcurrentDeleteOps, now.Add(time.Minute))
	if second.WorkersToCreate != 0 {
		t.Fatalf("expected second reconcile to enqueue 0 creates, got %d", second.WorkersToCreate)
	}
	if second.Status.PendingCreateCount != 1 {
		t.Fatalf("expected pending create count to remain 1, got %d", second.Status.PendingCreateCount)
	}
	if second.Status.LastAction != "waiting-active-operation" {
		t.Fatalf("expected second reconcile to wait for the active operation, got %s", second.Status.LastAction)
	}
}

func TestEnsureWorkersAcknowledgesCompletedCreateWhenReadyCountRises(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	spec := &autoscalingv1.WorkerPrototypeSpec{
		TargetWorkerCount: int32Ptr(3),
		MaxBatchSize:      int32Ptr(2),
	}

	current := &autoscalingv1.WorkerPrototypeStatus{
		TargetWorkerCount:        3,
		ObservedReadyWorkerCount: 1,
		PendingCreateCount:       2,
		PendingDeleteCount:       0,
		EffectiveWorkerCount:     3,
		LastAction:               "enqueue-create",
		LastReason:               "bootstrap",
		LastEnsureTime:           ptrTime(metav1.NewTime(now)),
	}

	plan := ensureWorkers(spec, current, 3, 0, testMaxConcurrentCreateOps, testMaxConcurrentDeleteOps, now.Add(time.Minute))
	if plan.Status.PendingCreateCount != 0 {
		t.Fatalf("expected pending create count to drop to 0, got %d", plan.Status.PendingCreateCount)
	}
	if plan.Status.EffectiveWorkerCount != 3 {
		t.Fatalf("expected effective worker count to stay 3, got %d", plan.Status.EffectiveWorkerCount)
	}
	if plan.WorkersToCreate != 0 {
		t.Fatalf("expected no new create request, got %d", plan.WorkersToCreate)
	}
}

func TestEnsureWorkersEnqueuesDeleteWhenTargetDrops(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	spec := &autoscalingv1.WorkerPrototypeSpec{
		TargetWorkerCount: int32Ptr(2),
		MaxBatchSize:      int32Ptr(1),
	}

	current := &autoscalingv1.WorkerPrototypeStatus{
		TargetWorkerCount:        4,
		ObservedReadyWorkerCount: 4,
		PendingCreateCount:       0,
		PendingDeleteCount:       0,
		EffectiveWorkerCount:     4,
		LastAction:               "stable",
		LastReason:               "target-satisfied",
		LastEnsureTime:           ptrTime(metav1.NewTime(now)),
	}

	plan := ensureWorkers(spec, current, 4, 0, testMaxConcurrentCreateOps, testMaxConcurrentDeleteOps, now.Add(time.Minute))
	if plan.WorkersToDelete != 1 {
		t.Fatalf("expected one delete to be enqueued, got %d", plan.WorkersToDelete)
	}
	if plan.Status.PendingDeleteCount != 1 {
		t.Fatalf("expected pending delete count to be 1, got %d", plan.Status.PendingDeleteCount)
	}
	if plan.Status.LastAction != "enqueue-delete" {
		t.Fatalf("expected enqueue-delete action, got %s", plan.Status.LastAction)
	}
}

func TestEnsureWorkersReenqueuesCreateWhenPendingCreateIsStale(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	spec := &autoscalingv1.WorkerPrototypeSpec{
		TargetWorkerCount: int32Ptr(3),
		MaxBatchSize:      int32Ptr(2),
	}

	current := &autoscalingv1.WorkerPrototypeStatus{
		TargetWorkerCount:        3,
		ObservedReadyWorkerCount: 1,
		PendingCreateCount:       2,
		PendingDeleteCount:       0,
		EffectiveWorkerCount:     3,
		LastAction:               "stable",
		LastReason:               "target-satisfied",
		LastEnsureTime:           ptrTime(metav1.NewTime(now)),
		ActiveOperation:          nil,
	}

	plan := ensureWorkers(spec, current, 1, 0, testMaxConcurrentCreateOps, testMaxConcurrentDeleteOps, now.Add(time.Minute))
	if plan.WorkersToCreate != 1 {
		t.Fatalf("expected create to be re-enqueued as a single worker, got %d", plan.WorkersToCreate)
	}
	if plan.Status.PendingCreateCount != 1 {
		t.Fatalf("expected pending create count to be normalized back to 1, got %d", plan.Status.PendingCreateCount)
	}
	if plan.Status.EffectiveWorkerCount != 2 {
		t.Fatalf("expected effective worker count to be 2 after re-enqueue, got %d", plan.Status.EffectiveWorkerCount)
	}
	if plan.Status.LastAction != "enqueue-create" {
		t.Fatalf("expected enqueue-create action, got %s", plan.Status.LastAction)
	}
}

func TestEnsureWorkersReenqueuesDeleteWhenPendingDeleteIsStale(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	spec := &autoscalingv1.WorkerPrototypeSpec{
		TargetWorkerCount: int32Ptr(4),
		MaxBatchSize:      int32Ptr(1),
	}

	current := &autoscalingv1.WorkerPrototypeStatus{
		TargetWorkerCount:        4,
		ObservedReadyWorkerCount: 5,
		PendingCreateCount:       0,
		PendingDeleteCount:       1,
		EffectiveWorkerCount:     4,
		LastAction:               "stable",
		LastReason:               "target-satisfied",
		LastEnsureTime:           ptrTime(metav1.NewTime(now)),
		ActiveOperation:          nil,
	}

	plan := ensureWorkers(spec, current, 5, 0, testMaxConcurrentCreateOps, testMaxConcurrentDeleteOps, now.Add(time.Minute))
	if plan.WorkersToDelete != 1 {
		t.Fatalf("expected one delete to be re-enqueued, got %d", plan.WorkersToDelete)
	}
	if plan.Status.PendingDeleteCount != 1 {
		t.Fatalf("expected pending delete count to be normalized back to 1, got %d", plan.Status.PendingDeleteCount)
	}
	if plan.Status.EffectiveWorkerCount != 4 {
		t.Fatalf("expected effective worker count to be 4 after re-enqueue, got %d", plan.Status.EffectiveWorkerCount)
	}
	if plan.Status.LastAction != "enqueue-delete" {
		t.Fatalf("expected enqueue-delete action, got %s", plan.Status.LastAction)
	}
}

func TestEnsureWorkersKeepsPendingDeleteWhenDeleteOperationIsActive(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	spec := &autoscalingv1.WorkerPrototypeSpec{
		TargetWorkerCount: int32Ptr(4),
		MaxBatchSize:      int32Ptr(1),
	}

	current := &autoscalingv1.WorkerPrototypeStatus{
		TargetWorkerCount:        4,
		ObservedReadyWorkerCount: 5,
		PendingCreateCount:       0,
		PendingDeleteCount:       1,
		EffectiveWorkerCount:     4,
		LastAction:               "executor-started",
		LastReason:               "delete job running",
		LastEnsureTime:           ptrTime(metav1.NewTime(now)),
		ActiveOperation: &autoscalingv1.WorkerOperationStatus{
			OperationType:  "delete",
			TargetNodeName: "k3s-worker-5",
			Phase:          "Running",
			RequestedCount: 1,
		},
	}

	plan := ensureWorkers(spec, current, 5, 0, testMaxConcurrentCreateOps, testMaxConcurrentDeleteOps, now.Add(time.Minute))
	if plan.WorkersToDelete != 0 {
		t.Fatalf("expected no additional delete to be enqueued while active delete exists, got %d", plan.WorkersToDelete)
	}
	if plan.Status.PendingDeleteCount != 1 {
		t.Fatalf("expected pending delete count to remain 1, got %d", plan.Status.PendingDeleteCount)
	}
	if plan.Status.EffectiveWorkerCount != 4 {
		t.Fatalf("expected effective worker count to remain 4, got %d", plan.Status.EffectiveWorkerCount)
	}
	if plan.Status.LastAction != "waiting-active-operation" {
		t.Fatalf("expected waiting-active-operation while active delete exists, got %s", plan.Status.LastAction)
	}
}

func TestEnsureWorkersNormalizesActiveCreateBacklogToRealInFlightOperation(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	spec := &autoscalingv1.WorkerPrototypeSpec{
		TargetWorkerCount: int32Ptr(12),
		MaxBatchSize:      int32Ptr(4),
	}

	current := &autoscalingv1.WorkerPrototypeStatus{
		TargetWorkerCount:        12,
		ObservedReadyWorkerCount: 5,
		PendingCreateCount:       7,
		PendingDeleteCount:       0,
		EffectiveWorkerCount:     12,
		LastAction:               "enqueue-create",
		LastReason:               "target=12 effective=5 missing=7",
		LastEnsureTime:           ptrTime(metav1.NewTime(now)),
		ActiveOperation: &autoscalingv1.WorkerOperationStatus{
			OperationType:  "create",
			TargetNodeName: "k3s-worker-6",
			Phase:          "WaitingForObservation",
			RequestedCount: 1,
		},
	}

	plan := ensureWorkers(spec, current, 5, 0, testMaxConcurrentCreateOps, testMaxConcurrentDeleteOps, now.Add(time.Minute))
	if plan.WorkersToCreate != 0 {
		t.Fatalf("expected no extra create while one worker create is active, got %d", plan.WorkersToCreate)
	}
	if plan.Status.PendingCreateCount != 1 {
		t.Fatalf("expected pending create count to be normalized to the real in-flight create, got %d", plan.Status.PendingCreateCount)
	}
	if plan.Status.EffectiveWorkerCount != 6 {
		t.Fatalf("expected effective worker count to reflect one real in-flight create, got %d", plan.Status.EffectiveWorkerCount)
	}
	if plan.Status.LastAction != "waiting-active-operation" {
		t.Fatalf("expected waiting-active-operation, got %s", plan.Status.LastAction)
	}
}

func TestEnsureWorkersAllowsParallelCreatesUpToConfiguredLimit(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	spec := &autoscalingv1.WorkerPrototypeSpec{
		TargetWorkerCount: int32Ptr(5),
		MaxBatchSize:      int32Ptr(3),
	}

	plan := ensureWorkers(spec, nil, 1, 0, 2, 1, now)
	if plan.WorkersToCreate != 2 {
		t.Fatalf("expected two create jobs to be enqueued, got %d", plan.WorkersToCreate)
	}
	if plan.Status.PendingCreateCount != 2 {
		t.Fatalf("expected pending create count to be 2, got %d", plan.Status.PendingCreateCount)
	}
	if plan.Status.EffectiveWorkerCount != 3 {
		t.Fatalf("expected effective worker count to be 3, got %d", plan.Status.EffectiveWorkerCount)
	}
}

func TestEnsureWorkersBlocksDeleteWhenUnschedulablePodsExist(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	spec := &autoscalingv1.WorkerPrototypeSpec{
		TargetWorkerCount: int32Ptr(2),
		MaxBatchSize:      int32Ptr(1),
	}

	current := &autoscalingv1.WorkerPrototypeStatus{
		TargetWorkerCount:        4,
		ObservedReadyWorkerCount: 4,
		PendingCreateCount:       0,
		PendingDeleteCount:       0,
		EffectiveWorkerCount:     4,
		LastAction:               "stable",
		LastReason:               "target-satisfied",
		LastEnsureTime:           ptrTime(metav1.NewTime(now)),
	}

	plan := ensureWorkers(spec, current, 4, 1, testMaxConcurrentCreateOps, testMaxConcurrentDeleteOps, now.Add(time.Minute))
	if plan.WorkersToDelete != 0 {
		t.Fatalf("expected delete to be blocked while unschedulable pods exist, got %d", plan.WorkersToDelete)
	}
	if plan.Status.PendingDeleteCount != 0 {
		t.Fatalf("expected pending delete count to remain 0, got %d", plan.Status.PendingDeleteCount)
	}
	if plan.Status.LastAction != "blocked-unschedulable-pods" {
		t.Fatalf("expected blocked-unschedulable-pods action, got %s", plan.Status.LastAction)
	}
}

func ptrTime(value metav1.Time) *metav1.Time {
	return &value
}
