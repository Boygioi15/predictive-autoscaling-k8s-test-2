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

func TestEnsureWorkersEnqueuesCreateOnlyOnceAcrossReconciles(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	spec := &autoscalingv1.WorkerPrototypeSpec{
		TargetWorkerCount: int32Ptr(3),
		MaxBatchSize:      int32Ptr(2),
	}

	first := ensureWorkers(spec, nil, 1, now)
	if first.WorkersToCreate != 2 {
		t.Fatalf("expected first reconcile to enqueue 2 creates, got %d", first.WorkersToCreate)
	}
	if first.Status.PendingCreateCount != 2 {
		t.Fatalf("expected pending create count to be 2, got %d", first.Status.PendingCreateCount)
	}
	if first.Status.EffectiveWorkerCount != 3 {
		t.Fatalf("expected effective worker count to be 3, got %d", first.Status.EffectiveWorkerCount)
	}

	second := ensureWorkers(spec, &first.Status, 1, now.Add(time.Minute))
	if second.WorkersToCreate != 0 {
		t.Fatalf("expected second reconcile to enqueue 0 creates, got %d", second.WorkersToCreate)
	}
	if second.Status.PendingCreateCount != 2 {
		t.Fatalf("expected pending create count to remain 2, got %d", second.Status.PendingCreateCount)
	}
	if second.Status.LastAction != "stable" {
		t.Fatalf("expected second reconcile to be stable, got %s", second.Status.LastAction)
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

	plan := ensureWorkers(spec, current, 3, now.Add(time.Minute))
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

	plan := ensureWorkers(spec, current, 4, now.Add(time.Minute))
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

func ptrTime(value metav1.Time) *metav1.Time {
	return &value
}
