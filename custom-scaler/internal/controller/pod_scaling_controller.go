package controller

import (
	"bytes"
	"context"
	"io"
	"net/http"

	appsv1 "k8s.io/api/apps/v1"
	"k8s.io/apimachinery/pkg/types"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/builder"
	"sigs.k8s.io/controller-runtime/pkg/client"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/predicate"

	autoscalingv1 "github.com/Boygioi15/predictive-autoscaling-k8s-test/api/v1"
)

// PodScalingReconciler owns forecast evaluation, pod replica calculation, and
// pod-related status updates for CustomScaler resources.
type PodScalingReconciler struct {
	*CustomScalerControllerBase
}

// Reconcile is part of the main kubernetes reconciliation loop for pod scaling.
func (r *PodScalingReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := logf.FromContext(ctx)

	var customScaler autoscalingv1.CustomScaler
	if err := r.Get(ctx, req.NamespacedName, &customScaler); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	requeueAfter := pollingInterval(customScaler.Spec.IntervalMinutes)
	log.Info(
		"Starting pod scaling cycle",
		"url", customScaler.Spec.URL,
		"targetDeployment", customScaler.Spec.DeploymentName,
		"forecastContractID", r.ForecastDefaults.ContractID,
		"interval", requeueAfter.String(),
	)

	body, err := r.buildForecastRequestBody()
	if err != nil {
		log.Error(err, "Failed to build forecasting request")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	log.Info(
		"Calling forecasting service",
		"url", customScaler.Spec.URL,
		"payload", string(body),
	)

	resp, err := http.Post(customScaler.Spec.URL, "application/json", bytes.NewReader(body))
	if err != nil {
		log.Error(err, "Failed to call forecasting service")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}
	defer resp.Body.Close()

	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		responseBody, _ := io.ReadAll(resp.Body)
		log.Error(nil, "Forecasting service returned non-success status", "statusCode", resp.StatusCode, "body", string(responseBody))
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	responseBody, err := io.ReadAll(resp.Body)
	if err != nil {
		log.Error(err, "Failed to read forecasting service response")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	log.Info(
		"Forecasting service response received",
		"statusCode", resp.StatusCode,
		"body", string(responseBody),
	)

	forecast, err := parseForecastResponse(responseBody)
	if err != nil {
		log.Error(err, "Response was not a valid forecast payload")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	policy := r.scalingPolicyFor(&customScaler)
	currentReactivePressureBump := customScaler.Status.ReactivePressureBump
	nextPressureBump, pressureReason := nextReactivePressureBump(currentReactivePressureBump, forecast.Observed, policy)
	desiredReplicas, demandSummary := calculateDesiredReplicas(forecast, policy)
	pressureReplicaBump := nextPressureBump * policy.ReactiveReplicaStep
	if pressureReplicaBump > 0 {
		desiredReplicas += pressureReplicaBump
		if desiredReplicas > policy.MaxReplicas {
			desiredReplicas = policy.MaxReplicas
		}
	}

	log.Info(
		"Calculated desired replicas from forecast",
		"targetDeployment", customScaler.Spec.DeploymentName,
		"forecastContractID", r.ForecastDefaults.ContractID,
		"rawPredictions", forecast.Predictions,
		"predictionRowsCount", len(forecast.PredictionRows),
		"peakRequestsPerMinute", demandSummary.PeakRequestsPerMinute,
		"effectiveRequestsPerMinute", demandSummary.EffectiveRequestsPerMinute,
		"peakCPUSecondsPerMinute", demandSummary.PeakCPUSecondsPerMinute,
		"effectiveCPUSecondsPerMinute", demandSummary.EffectiveCPUSecondsPerMinute,
		"requestReplicaDemand", demandSummary.RequestReplicaDemand,
		"cpuReplicaDemand", demandSummary.CPUReplicaDemand,
		"baseReplicaDemand", demandSummary.BaseReplicaDemand,
		"dominantSignal", demandSummary.DominantSignal,
		"requestsPerPod", policy.RequestsPerPod,
		"cpuSecondsPerPod", policy.CPUSecondsPerPod,
		"safetyFactor", policy.SafetyFactor,
		"sparePod", policy.SparePod,
		"maxReplicas", policy.MaxReplicas,
		"minReplicas", policy.MinReplicas,
		"appErrorRateThreshold", policy.AppErrorRateThreshold,
		"ingressP99ThresholdSec", policy.IngressP99ThresholdSec,
		"reactiveRequiredPoints", policy.ReactiveRequiredPoints,
		"desiredReplicas", desiredReplicas,
		"currentReactivePressureBump", currentReactivePressureBump,
		"nextReactivePressureBump", nextPressureBump,
		"reactivePressureBumpReason", pressureReason,
		"reactivePressureReplicaBump", pressureReplicaBump,
	)

	var deployment appsv1.Deployment
	depName := types.NamespacedName{Namespace: customScaler.Namespace, Name: customScaler.Spec.DeploymentName}
	if err := r.Get(ctx, depName, &deployment); err != nil {
		log.Error(err, "Failed to find target deployment")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	currentReplicas := int32(1)
	if deployment.Spec.Replicas != nil {
		currentReplicas = *deployment.Spec.Replicas
	}

	if desiredReplicas < currentReplicas {
		scaleDownAllowed, scaleDownReason := allowScaleDown(forecast.Observed, policy)
		if !scaleDownAllowed {
			log.Info(
				"Skipping scale down because guardrails are not healthy",
				"targetDeployment", customScaler.Spec.DeploymentName,
				"forecastContractID", r.ForecastDefaults.ContractID,
				"currentReplicas", currentReplicas,
				"desiredReplicas", desiredReplicas,
				"currentReactivePressureBump", currentReactivePressureBump,
				"nextReactivePressureBump", nextPressureBump,
				"reactivePressureReplicaBump", pressureReplicaBump,
				"scaleDownPolicy", policy.ScaleDownPolicy,
				"scaleDownReason", scaleDownReason,
				"observed", forecast.Observed,
			)
			desiredReplicas = currentReplicas
		}
	}

	if currentReplicas != desiredReplicas {
		log.Info("Scaling deployment", "Old", currentReplicas, "New", desiredReplicas)
		deployment.Spec.Replicas = &desiredReplicas
		if err := r.Update(ctx, &deployment); err != nil {
			return ctrl.Result{}, err
		}
	}

	if err := r.patchPodScalingStatus(
		ctx,
		&customScaler,
		demandSummary.PeakRequestsPerMinute,
		demandSummary.EffectiveRequestsPerMinute,
		desiredReplicas,
		nextPressureBump,
		pressureReason,
	); err != nil {
		log.Error(err, "Failed to update pod scaling status")
		return ctrl.Result{RequeueAfter: requeueAfter}, nil
	}

	log.Info(
		"Pod scaling cycle completed",
		"deployment", customScaler.Spec.DeploymentName,
		"replica", desiredReplicas,
		"nextRunIn", requeueAfter.String(),
	)

	return ctrl.Result{RequeueAfter: requeueAfter}, nil
}

func (r *CustomScalerControllerBase) patchPodScalingStatus(
	ctx context.Context,
	customScaler *autoscalingv1.CustomScaler,
	peakRPS float64,
	effectiveRPS float64,
	desiredReplicas int32,
	reactivePressureBump int32,
	reactivePressureReason string,
) error {
	statusChanged := customScaler.Status.LastForecastPeak != peakRPS ||
		customScaler.Status.LastEffectiveRPS != effectiveRPS ||
		customScaler.Status.LastDesiredReplicas != desiredReplicas ||
		customScaler.Status.CurrentReplicas != desiredReplicas ||
		customScaler.Status.ReactivePressureBump != reactivePressureBump ||
		customScaler.Status.ReactivePressureReason != reactivePressureReason
	if !statusChanged {
		return nil
	}

	base := customScaler.DeepCopy()
	updated := customScaler.DeepCopy()
	updated.Status.LastForecastPeak = peakRPS
	updated.Status.LastEffectiveRPS = effectiveRPS
	updated.Status.LastDesiredReplicas = desiredReplicas
	updated.Status.CurrentReplicas = desiredReplicas
	updated.Status.ReactivePressureBump = reactivePressureBump
	updated.Status.ReactivePressureReason = reactivePressureReason

	return r.Status().Patch(ctx, updated, client.MergeFrom(base))
}

// SetupWithManager sets up the pod-scaling controller with the Manager.
func (r *PodScalingReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&autoscalingv1.CustomScaler{}, builder.WithPredicates(predicate.GenerationChangedPredicate{})).
		Named("customscaler-pod").
		Complete(r)
}
