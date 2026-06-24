package controller

import (
	"context"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/predicate"

	autoscalingv1 "github.com/Boygioi15/predictive-autoscaling-k8s-test/api/v1"
)

// NodeScalingReconciler owns worker/node planning and executor actions for
// CustomScaler resources.
type NodeScalingReconciler struct {
	*CustomScalerControllerBase
}

// Reconcile is part of the main kubernetes reconciliation loop for node scaling.
func (r *NodeScalingReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := logf.FromContext(ctx)

	var customScaler autoscalingv1.CustomScaler
	if err := r.Get(ctx, req.NamespacedName, &customScaler); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	requeueAfter := pollingInterval(customScaler.Spec.IntervalMinutes)
	if customScaler.Spec.WorkerPrototype == nil {
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	var deployment appsv1.Deployment
	depName := types.NamespacedName{Namespace: customScaler.Namespace, Name: customScaler.Spec.DeploymentName}
	if err := r.Get(ctx, depName, &deployment); err != nil {
		log.Error(err, "Failed to find target deployment for node scaling")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	desiredReplicas := customScaler.Status.LastDesiredReplicas
	if desiredReplicas == 0 && deployment.Spec.Replicas != nil {
		desiredReplicas = *deployment.Spec.Replicas
	}

	workerNow := time.Now()
	workerPlan, workerTarget, err := r.reconcileWorkerPrototype(
		ctx,
		&customScaler,
		&deployment,
		desiredReplicas,
		0,
		workerNow,
	)
	if err != nil {
		log.Error(err, "Failed to reconcile worker prototype state")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}
	if err := r.reconcileWorkerExecutor(ctx, &customScaler, workerPlan, workerNow); err != nil {
		log.Error(err, "Failed to reconcile worker prototype executor")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	if workerPlan != nil {
		log.Info(
			"Worker prototype ensure_worker evaluated",
			"workerTargetMode", workerTarget.Mode,
			"workerCapacityStrategy", workerTarget.Strategy,
			"targetWorkers", workerPlan.Status.TargetWorkerCount,
			"rawTargetWorkers", workerTarget.RawTargetWorkerCount,
			"desiredReplicas", workerTarget.DesiredReplicas,
			"unschedulablePods", workerTarget.UnschedulablePods,
			"safetyPods", workerTarget.SafetyPods,
			"desiredPodsForCapacity", workerTarget.DesiredPodsForCapacity,
			"nodeAllocatableMilliCPU", workerTarget.NodeAllocatableMilliCPU,
			"podRequestMilliCPU", workerTarget.PodRequestMilliCPU,
			"podsPerWorker", workerTarget.PodsPerWorker,
			"minWorkerCount", workerTarget.MinWorkerCount,
			"maxWorkerCount", workerTarget.MaxWorkerCount,
			"readyWorkerCount", workerTarget.ReadyWorkerCount,
			"currentAppScheduledPods", workerTarget.CurrentAppScheduledPods,
			"totalAppSlotCapacity", workerTarget.TotalAppSlotCapacity,
			"missingAppSlots", workerTarget.MissingAppSlots,
			"requiredReadyWorkers", workerTarget.RequiredReadyWorkers,
			"observedReadyWorkers", workerPlan.Status.ObservedReadyWorkerCount,
			"pendingCreateWorkers", workerPlan.Status.PendingCreateCount,
			"pendingDeleteWorkers", workerPlan.Status.PendingDeleteCount,
			"effectiveWorkers", workerPlan.Status.EffectiveWorkerCount,
			"workersToCreate", workerPlan.WorkersToCreate,
			"workersToDelete", workerPlan.WorkersToDelete,
			"lastAction", workerPlan.Status.LastAction,
			"lastReason", workerPlan.Status.LastReason,
		)
	}

	if err := r.patchWorkerPrototypeStatus(ctx, &customScaler, workerPlan); err != nil {
		log.Error(err, "Failed to update node scaling status")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	log.Info(
		"Node scaling cycle completed",
		"deployment", customScaler.Spec.DeploymentName,
		"desiredReplicas", desiredReplicas,
		"nextRunIn", requeueAfter.String(),
	)

	return ctrl.Result{RequeueAfter: requeueAfter}, nil
}

func (r *CustomScalerControllerBase) patchWorkerPrototypeStatus(
	ctx context.Context,
	customScaler *autoscalingv1.CustomScaler,
	plan *workerPrototypePlan,
) error {
	if plan == nil || !workerPrototypeStatusChanged(customScaler.Status.WorkerPrototype, plan) {
		return nil
	}

	base := customScaler.DeepCopy()
	updated := customScaler.DeepCopy()
	updated.Status.WorkerPrototype = &plan.Status

	return r.Status().Patch(ctx, updated, client.MergeFrom(base))
}

// SetupWithManager sets up the node-scaling controller with the Manager.
func (r *NodeScalingReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&autoscalingv1.CustomScaler{}, builder.WithPredicates(predicate.GenerationChangedPredicate{})).
		Named("customscaler-node").
		Complete(r)
}
