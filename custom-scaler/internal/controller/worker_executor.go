package controller

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"k8s.io/apimachinery/pkg/util/rand"

	autoscalingv1 "github.com/Boygioi15/predictive-autoscaling-k8s-test/api/v1"
)

const (
	workerOperationCreate               = "create"
	workerOperationDelete               = "delete"
	workerOperationPhaseRunning         = "Running"
	workerOperationPhaseWaitObservation = "WaitingForObservation"
	defaultWorkerExecutorNamespace      = "custom-scaler-system"
	defaultWorkerExecutorServiceAccount = "custom-scaler-controller-manager"
	defaultWorkerExecutorImage          = "docker.io/boygioi/vm-job:latest"
	defaultWorkerExecutorConfigMapName  = "custom-scaler-vm-job-config"
	defaultWorkerExecutorSecretName     = "custom-scaler-vm-job-secret"
	defaultWorkerExecutorSecretMount    = "/var/run/vm-job-secret"
	defaultWorkerExecutorTTLSeconds     = int32(3600)
)

type WorkerExecutorConfig struct {
	Namespace          string
	ServiceAccountName string
	Image              string
	CreateCommand      string
	DeleteCommand      string
	LoadBalancerID     string
	NodeNamePrefix     string
	ConfigMapName      string
	SecretName         string
	SecretMountPath    string
	TTLSecondsAfterRun int32
}

func LoadWorkerExecutorConfigFromEnv() WorkerExecutorConfig {
	return WorkerExecutorConfig{
		Namespace:          envOrDefault("SCALER_WORKER_EXECUTOR_NAMESPACE", defaultWorkerExecutorNamespace),
		ServiceAccountName: envOrDefault("SCALER_WORKER_EXECUTOR_SERVICE_ACCOUNT", defaultWorkerExecutorServiceAccount),
		Image:              envOrDefault("SCALER_WORKER_EXECUTOR_IMAGE", defaultWorkerExecutorImage),
		CreateCommand:      strings.TrimSpace(os.Getenv("SCALER_WORKER_CREATE_COMMAND")),
		DeleteCommand:      strings.TrimSpace(os.Getenv("SCALER_WORKER_DELETE_COMMAND")),
		LoadBalancerID:     strings.TrimSpace(os.Getenv("SCALER_WORKER_LOAD_BALANCER_ID")),
		NodeNamePrefix:     envOrDefault("SCALER_WORKER_NODE_NAME_PREFIX", "k3s-worker"),
		ConfigMapName:      envOrDefault("SCALER_WORKER_EXECUTOR_CONFIG_MAP_NAME", defaultWorkerExecutorConfigMapName),
		SecretName:         envOrDefault("SCALER_WORKER_EXECUTOR_SECRET_NAME", defaultWorkerExecutorSecretName),
		SecretMountPath:    envOrDefault("SCALER_WORKER_EXECUTOR_SECRET_MOUNT_PATH", defaultWorkerExecutorSecretMount),
		TTLSecondsAfterRun: envOrDefaultInt32("SCALER_WORKER_EXECUTOR_TTL_SECONDS", defaultWorkerExecutorTTLSeconds),
	}
}

func (c WorkerExecutorConfig) enabledFor(operationType string) bool {
	switch operationType {
	case workerOperationCreate:
		return c.CreateCommand != ""
	case workerOperationDelete:
		return c.DeleteCommand != ""
	default:
		return false
	}
}

func (r *CustomScalerReconciler) reconcileWorkerExecutor(
	ctx context.Context,
	customScaler *autoscalingv1.CustomScaler,
	plan *workerPrototypePlan,
	now time.Time,
) error {
	if plan == nil {
		return nil
	}

	active := plan.Status.ActiveOperation
	if active != nil {
		return r.reconcileActiveWorkerOperation(ctx, customScaler, plan, active, now)
	}

	switch {
	case plan.WorkersToCreate > 0:
		return r.startWorkerOperation(ctx, customScaler, plan, workerOperationCreate, now)
	case plan.WorkersToDelete > 0:
		return r.startWorkerOperation(ctx, customScaler, plan, workerOperationDelete, now)
	default:
		return nil
	}
}

func (r *CustomScalerReconciler) reconcileActiveWorkerOperation(
	ctx context.Context,
	customScaler *autoscalingv1.CustomScaler,
	plan *workerPrototypePlan,
	active *autoscalingv1.WorkerOperationStatus,
	now time.Time,
) error {
	var job batchv1.Job
	if err := r.Get(ctx, types.NamespacedName{Namespace: active.JobNamespace, Name: active.JobName}, &job); err != nil {
		if apierrors.IsNotFound(err) {
			rollbackWorkerOperation(plan, active)
			plan.Status.LastAction = "executor-missing-job"
			plan.Status.LastReason = fmt.Sprintf("job %s/%s was not found", active.JobNamespace, active.JobName)
			plan.Status.ActiveOperation = nil
			return nil
		}
		return err
	}

	switch {
	case isJobFailed(&job):
		rollbackWorkerOperation(plan, active)
		plan.Status.LastAction = "executor-job-failed"
		plan.Status.LastReason = fmt.Sprintf("job %s/%s failed", active.JobNamespace, active.JobName)
		plan.Status.ActiveOperation = nil
		return nil
	case isJobSucceeded(&job) && active.Phase == workerOperationPhaseRunning:
		finishedAt := metav1.NewTime(now)
		active.Phase = workerOperationPhaseWaitObservation
		active.CommandFinishedAt = &finishedAt
		active.Message = "command completed; waiting for worker observation"
	}

	if active.Phase == workerOperationPhaseWaitObservation && workerObservationSatisfied(customScaler.Status.WorkerPrototype, &plan.Status, active.OperationType) {
		plan.Status.LastAction = "executor-observed"
		plan.Status.LastReason = fmt.Sprintf("%s operation reflected in observed worker count", active.OperationType)
		plan.Status.ActiveOperation = nil
	}

	return nil
}

func (r *CustomScalerReconciler) startWorkerOperation(
	ctx context.Context,
	customScaler *autoscalingv1.CustomScaler,
	plan *workerPrototypePlan,
	operationType string,
	now time.Time,
) error {
	if !r.WorkerExecutor.enabledFor(operationType) {
		if operationType == workerOperationCreate && plan.WorkersToCreate > 0 && plan.Status.PendingCreateCount >= plan.WorkersToCreate {
			plan.Status.PendingCreateCount -= plan.WorkersToCreate
		}
		if operationType == workerOperationDelete && plan.WorkersToDelete > 0 && plan.Status.PendingDeleteCount >= plan.WorkersToDelete {
			plan.Status.PendingDeleteCount -= plan.WorkersToDelete
		}
		plan.Status.EffectiveWorkerCount = plan.Status.ObservedReadyWorkerCount + plan.Status.PendingCreateCount - plan.Status.PendingDeleteCount
		plan.Status.LastAction = "executor-disabled"
		plan.Status.LastReason = fmt.Sprintf("%s command is not configured", operationType)
		return nil
	}

	job := buildWorkerOperationJob(customScaler, &plan.Status, operationType, r.WorkerExecutor, now)
	if err := r.Create(ctx, &job); err != nil {
		return err
	}

	startedAt := metav1.NewTime(now)
	plan.Status.ActiveOperation = &autoscalingv1.WorkerOperationStatus{
		OperationType:  operationType,
		Phase:          workerOperationPhaseRunning,
		JobNamespace:   job.Namespace,
		JobName:        job.Name,
		RequestedCount: 1,
		Message:        "executor job created",
		StartedAt:      &startedAt,
	}
	plan.Status.LastAction = "executor-started"
	plan.Status.LastReason = fmt.Sprintf("%s job %s/%s created", operationType, job.Namespace, job.Name)

	return nil
}

func buildWorkerOperationJob(
	customScaler *autoscalingv1.CustomScaler,
	status *autoscalingv1.WorkerPrototypeStatus,
	operationType string,
	config WorkerExecutorConfig,
	now time.Time,
) batchv1.Job {
	command := config.CreateCommand
	if operationType == workerOperationDelete {
		command = config.DeleteCommand
	}

	backoffLimit := int32(0)
	sshSecretDefaultMode := int32(0o400)
	namePrefix := fmt.Sprintf("%s-worker-%s-", customScaler.Name, operationType)
	jobName := sanitizeJobName(namePrefix + rand.String(5))

	container := corev1.Container{
		Name:    "executor",
		Image:   config.Image,
		Command: []string{"/bin/sh", "-c", command},
		Env: []corev1.EnvVar{
			{Name: "SCALER_NAME", Value: customScaler.Name},
			{Name: "SCALER_NAMESPACE", Value: customScaler.Namespace},
			{Name: "WORKER_OPERATION_TYPE", Value: operationType},
			{Name: "WORKER_TARGET_COUNT", Value: fmt.Sprintf("%d", status.TargetWorkerCount)},
			{Name: "WORKER_OBSERVED_READY_COUNT", Value: fmt.Sprintf("%d", status.ObservedReadyWorkerCount)},
			{Name: "WORKER_PENDING_CREATE_COUNT", Value: fmt.Sprintf("%d", status.PendingCreateCount)},
			{Name: "WORKER_PENDING_DELETE_COUNT", Value: fmt.Sprintf("%d", status.PendingDeleteCount)},
			{Name: "WORKER_EFFECTIVE_COUNT", Value: fmt.Sprintf("%d", status.EffectiveWorkerCount)},
			{Name: "WORKER_ENSURE_TIME", Value: now.UTC().Format(time.RFC3339)},
			{Name: "SCALER_WORKER_LOAD_BALANCER_ID", Value: config.LoadBalancerID},
			{Name: "SCALER_WORKER_NODE_NAME_PREFIX", Value: config.NodeNamePrefix},
		},
	}

	if config.ConfigMapName != "" {
		container.EnvFrom = append(container.EnvFrom, corev1.EnvFromSource{
			ConfigMapRef: &corev1.ConfigMapEnvSource{
				LocalObjectReference: corev1.LocalObjectReference{Name: config.ConfigMapName},
			},
		})
	}

	if config.SecretName != "" {
		container.Env = append(container.Env,
			corev1.EnvVar{
				Name: "VULTR_API_KEY",
				ValueFrom: &corev1.EnvVarSource{
					SecretKeyRef: &corev1.SecretKeySelector{
						LocalObjectReference: corev1.LocalObjectReference{Name: config.SecretName},
						Key:                  "VULTR_API_KEY",
					},
				},
			},
			corev1.EnvVar{
				Name: "K3S_TOKEN",
				ValueFrom: &corev1.EnvVarSource{
					SecretKeyRef: &corev1.SecretKeySelector{
						LocalObjectReference: corev1.LocalObjectReference{Name: config.SecretName},
						Key:                  "K3S_TOKEN",
					},
				},
			},
		)

		container.VolumeMounts = append(container.VolumeMounts, corev1.VolumeMount{
			Name:      "vm-job-secret",
			MountPath: config.SecretMountPath,
			ReadOnly:  true,
		})
	}

	podSpec := corev1.PodSpec{
		RestartPolicy:      corev1.RestartPolicyNever,
		ServiceAccountName: config.ServiceAccountName,
		Containers:         []corev1.Container{container},
	}

	if config.SecretName != "" {
		podSpec.Volumes = append(podSpec.Volumes, corev1.Volume{
			Name: "vm-job-secret",
			VolumeSource: corev1.VolumeSource{
				Secret: &corev1.SecretVolumeSource{
					SecretName:  config.SecretName,
					DefaultMode: &sshSecretDefaultMode,
				},
			},
		})
	}

	return batchv1.Job{
		ObjectMeta: metav1.ObjectMeta{
			Name:      jobName,
			Namespace: config.Namespace,
			Labels: map[string]string{
				"autoscaling.my.domain/customscaler":     customScaler.Name,
				"autoscaling.my.domain/worker-op":        operationType,
				"autoscaling.my.domain/scaler-namespace": customScaler.Namespace,
			},
		},
		Spec: batchv1.JobSpec{
			BackoffLimit:            &backoffLimit,
			TTLSecondsAfterFinished: &config.TTLSecondsAfterRun,
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{
					Labels: map[string]string{
						"autoscaling.my.domain/customscaler": customScaler.Name,
						"autoscaling.my.domain/worker-op":    operationType,
					},
				},
				Spec: corev1.PodSpec{
					RestartPolicy:      podSpec.RestartPolicy,
					ServiceAccountName: podSpec.ServiceAccountName,
					Containers:         podSpec.Containers,
					Volumes:            podSpec.Volumes,
				},
			},
		},
	}
}

func rollbackWorkerOperation(plan *workerPrototypePlan, active *autoscalingv1.WorkerOperationStatus) {
	switch active.OperationType {
	case workerOperationCreate:
		if plan.Status.PendingCreateCount > 0 {
			plan.Status.PendingCreateCount--
		}
	case workerOperationDelete:
		if plan.Status.PendingDeleteCount > 0 {
			plan.Status.PendingDeleteCount--
		}
	}

	plan.Status.EffectiveWorkerCount = plan.Status.ObservedReadyWorkerCount + plan.Status.PendingCreateCount - plan.Status.PendingDeleteCount
}

func workerObservationSatisfied(
	previous *autoscalingv1.WorkerPrototypeStatus,
	current *autoscalingv1.WorkerPrototypeStatus,
	operationType string,
) bool {
	if previous == nil || current == nil {
		return false
	}

	switch operationType {
	case workerOperationCreate:
		return current.PendingCreateCount < previous.PendingCreateCount || current.ObservedReadyWorkerCount > previous.ObservedReadyWorkerCount
	case workerOperationDelete:
		return current.PendingDeleteCount < previous.PendingDeleteCount || current.ObservedReadyWorkerCount < previous.ObservedReadyWorkerCount
	default:
		return false
	}
}

func isJobSucceeded(job *batchv1.Job) bool {
	for _, condition := range job.Status.Conditions {
		if condition.Type == batchv1.JobComplete && condition.Status == corev1.ConditionTrue {
			return true
		}
	}

	return false
}

func isJobFailed(job *batchv1.Job) bool {
	for _, condition := range job.Status.Conditions {
		if condition.Type == batchv1.JobFailed && condition.Status == corev1.ConditionTrue {
			return true
		}
	}

	return false
}

func sanitizeJobName(name string) string {
	name = strings.ToLower(name)
	if len(name) > 63 {
		name = name[:63]
	}
	name = strings.TrimRight(name, "-")
	if name == "" {
		return "worker-op"
	}
	return name
}

func envOrDefault(name, defaultValue string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}

	return defaultValue
}

func envOrDefaultInt32(name string, defaultValue int32) int32 {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		return defaultValue
	}

	var parsed int
	if _, err := fmt.Sscanf(value, "%d", &parsed); err != nil {
		return defaultValue
	}

	return int32(parsed)
}
