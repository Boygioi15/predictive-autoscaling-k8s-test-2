package controller

import (
	"context"
	"fmt"
	"os"
	"sort"
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
	defaultWorkerObservationTimeout     = 10 * time.Minute
)

type WorkerExecutorConfig struct {
	Namespace              string
	ServiceAccountName     string
	Image                  string
	CreateCommand          string
	DeleteCommand          string
	NodeNamePrefix         string
	ConfigMapName          string
	SecretName             string
	SecretMountPath        string
	TTLSecondsAfterRun     int32
	ObservationTimeout     time.Duration
	MaxConcurrentCreateOps int32
	MaxConcurrentDeleteOps int32
}

type workerOperationExecution struct {
	Command        string
	TargetNodeName string
}

func controlPlaneAffinity() *corev1.Affinity {
	return &corev1.Affinity{
		NodeAffinity: &corev1.NodeAffinity{
			RequiredDuringSchedulingIgnoredDuringExecution: &corev1.NodeSelector{
				NodeSelectorTerms: []corev1.NodeSelectorTerm{
					{
						MatchExpressions: []corev1.NodeSelectorRequirement{
							{
								Key:      "node-role.kubernetes.io/control-plane",
								Operator: corev1.NodeSelectorOpExists,
							},
						},
					},
					{
						MatchExpressions: []corev1.NodeSelectorRequirement{
							{
								Key:      "node-role.kubernetes.io/master",
								Operator: corev1.NodeSelectorOpExists,
							},
						},
					},
				},
			},
		},
	}
}

func controlPlaneTolerations() []corev1.Toleration {
	return []corev1.Toleration{
		{
			Key:      "node-role.kubernetes.io/control-plane",
			Operator: corev1.TolerationOpExists,
			Effect:   corev1.TaintEffectNoSchedule,
		},
		{
			Key:      "node-role.kubernetes.io/master",
			Operator: corev1.TolerationOpExists,
			Effect:   corev1.TaintEffectNoSchedule,
		},
		{
			Key:      "role",
			Operator: corev1.TolerationOpEqual,
			Value:    "infra",
			Effect:   corev1.TaintEffectNoSchedule,
		},
	}
}

func LoadWorkerExecutorConfigFromEnv() WorkerExecutorConfig {
	return WorkerExecutorConfig{
		Namespace:              envOrDefault("SCALER_WORKER_EXECUTOR_NAMESPACE", defaultWorkerExecutorNamespace),
		ServiceAccountName:     envOrDefault("SCALER_WORKER_EXECUTOR_SERVICE_ACCOUNT", defaultWorkerExecutorServiceAccount),
		Image:                  envOrDefault("SCALER_WORKER_EXECUTOR_IMAGE", defaultWorkerExecutorImage),
		CreateCommand:          strings.TrimSpace(os.Getenv("SCALER_WORKER_CREATE_COMMAND")),
		DeleteCommand:          strings.TrimSpace(os.Getenv("SCALER_WORKER_DELETE_COMMAND")),
		NodeNamePrefix:         envOrDefault("SCALER_WORKER_NODE_NAME_PREFIX", "k3s-worker"),
		ConfigMapName:          envOrDefault("SCALER_WORKER_EXECUTOR_CONFIG_MAP_NAME", defaultWorkerExecutorConfigMapName),
		SecretName:             envOrDefault("SCALER_WORKER_EXECUTOR_SECRET_NAME", defaultWorkerExecutorSecretName),
		SecretMountPath:        envOrDefault("SCALER_WORKER_EXECUTOR_SECRET_MOUNT_PATH", defaultWorkerExecutorSecretMount),
		TTLSecondsAfterRun:     envOrDefaultInt32("SCALER_WORKER_EXECUTOR_TTL_SECONDS", defaultWorkerExecutorTTLSeconds),
		ObservationTimeout:     time.Duration(envOrDefaultInt32("SCALER_WORKER_OBSERVATION_TIMEOUT_SECONDS", int32(defaultWorkerObservationTimeout/time.Second))) * time.Second,
		MaxConcurrentCreateOps: normalizePositiveInt32(envOrDefaultInt32("SCALER_WORKER_MAX_CONCURRENT_CREATE_OPS", 1), 1),
		MaxConcurrentDeleteOps: normalizePositiveInt32(envOrDefaultInt32("SCALER_WORKER_MAX_CONCURRENT_DELETE_OPS", 1), 1),
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

func (r *CustomScalerControllerBase) reconcileWorkerExecutor(
	ctx context.Context,
	customScaler *autoscalingv1.CustomScaler,
	plan *workerPrototypePlan,
	now time.Time,
) error {
	if plan == nil {
		return nil
	}

	if err := r.reconcileActiveWorkerOperations(ctx, customScaler, plan, now); err != nil {
		return err
	}

	switch {
	case plan.WorkersToCreate > 0:
		return r.startWorkerOperations(ctx, customScaler, plan, workerOperationCreate, plan.WorkersToCreate, now)
	case plan.WorkersToDelete > 0:
		return r.startWorkerOperations(ctx, customScaler, plan, workerOperationDelete, plan.WorkersToDelete, now)
	default:
		return nil
	}
}

func (r *CustomScalerControllerBase) reconcileActiveWorkerOperations(
	ctx context.Context,
	customScaler *autoscalingv1.CustomScaler,
	plan *workerPrototypePlan,
	now time.Time,
) error {
	operations := cloneActiveOperations(&plan.Status)
	if len(operations) == 0 {
		syncLegacyActiveOperation(&plan.Status)
		return nil
	}

	previousObservedReady := int32(0)
	if customScaler.Status.WorkerPrototype != nil {
		previousObservedReady = customScaler.Status.WorkerPrototype.ObservedReadyWorkerCount
	}

	createObservationBudget := maxInt32(plan.Status.ObservedReadyWorkerCount-previousObservedReady, 0)
	deleteObservationBudget := maxInt32(previousObservedReady-plan.Status.ObservedReadyWorkerCount, 0)

	remainingOperations := make([]autoscalingv1.WorkerOperationStatus, 0, len(operations))
	for index := range operations {
		active := operations[index]
		var job batchv1.Job
		if err := r.Get(ctx, types.NamespacedName{Namespace: active.JobNamespace, Name: active.JobName}, &job); err != nil {
			if apierrors.IsNotFound(err) {
				rollbackWorkerOperation(plan, &active)
				plan.Status.LastAction = "executor-missing-job"
				plan.Status.LastReason = fmt.Sprintf("job %s/%s was not found", active.JobNamespace, active.JobName)
				continue
			}
			return err
		}

		switch {
		case isJobFailed(&job):
			rollbackWorkerOperation(plan, &active)
			plan.Status.LastAction = "executor-job-failed"
			plan.Status.LastReason = fmt.Sprintf("job %s/%s failed", active.JobNamespace, active.JobName)
			continue
		case isJobSucceeded(&job) && active.Phase == workerOperationPhaseRunning:
			finishedAt := metav1.NewTime(now)
			active.Phase = workerOperationPhaseWaitObservation
			active.CommandFinishedAt = &finishedAt
			active.Message = "command completed; waiting for worker observation"
		}

		if active.Phase == workerOperationPhaseWaitObservation {
			switch active.OperationType {
			case workerOperationCreate:
				if createObservationBudget > 0 {
					createObservationBudget -= activeOperationRequestedCount(active)
					plan.Status.LastAction = "executor-observed"
					plan.Status.LastReason = fmt.Sprintf("%s operation reflected in observed worker count", active.OperationType)
					continue
				}
			case workerOperationDelete:
				if deleteObservationBudget > 0 {
					deleteObservationBudget -= activeOperationRequestedCount(active)
					plan.Status.LastAction = "executor-observed"
					plan.Status.LastReason = fmt.Sprintf("%s operation reflected in observed worker count", active.OperationType)
					continue
				}
			}
		}

		if active.Phase == workerOperationPhaseWaitObservation && workerOperationTimedOut(&active, now, r.WorkerExecutor.ObservationTimeout) {
			rollbackWorkerOperation(plan, &active)
			plan.Status.LastAction = "executor-observation-timeout"
			plan.Status.LastReason = fmt.Sprintf("%s operation for node %s timed out waiting for worker observation", active.OperationType, active.TargetNodeName)
			continue
		}

		remainingOperations = append(remainingOperations, active)
	}

	plan.Status.ActiveOperations = remainingOperations
	syncLegacyActiveOperation(&plan.Status)
	return nil
}

func (r *CustomScalerControllerBase) startWorkerOperations(
	ctx context.Context,
	customScaler *autoscalingv1.CustomScaler,
	plan *workerPrototypePlan,
	operationType string,
	requestedCount int32,
	now time.Time,
) error {
	startedCount := int32(0)
	for startedCount < requestedCount {
		if err := r.startWorkerOperation(ctx, customScaler, plan, operationType, now); err != nil {
			if startedCount == 0 {
				return err
			}
			rollbackUnstartedWorkerOperations(plan, operationType, requestedCount-startedCount)
			plan.Status.LastAction = "executor-partial-start"
			plan.Status.LastReason = fmt.Sprintf("started %d/%d %s jobs; last error: %v", startedCount, requestedCount, operationType, err)
			syncLegacyActiveOperation(&plan.Status)
			return nil
		}
		startedCount++
	}

	if startedCount > 1 {
		plan.Status.LastAction = "executor-started"
		plan.Status.LastReason = fmt.Sprintf("%s jobs started: %d", operationType, startedCount)
	}
	syncLegacyActiveOperation(&plan.Status)
	return nil
}

func (r *CustomScalerControllerBase) startWorkerOperation(
	ctx context.Context,
	customScaler *autoscalingv1.CustomScaler,
	plan *workerPrototypePlan,
	operationType string,
	now time.Time,
) error {
	if !r.WorkerExecutor.enabledFor(operationType) {
		if operationType == workerOperationCreate && plan.Status.PendingCreateCount > 0 {
			plan.Status.PendingCreateCount--
		}
		if operationType == workerOperationDelete && plan.Status.PendingDeleteCount > 0 {
			plan.Status.PendingDeleteCount--
		}
		plan.Status.EffectiveWorkerCount = plan.Status.ObservedReadyWorkerCount + plan.Status.PendingCreateCount - plan.Status.PendingDeleteCount
		plan.Status.LastAction = "executor-disabled"
		plan.Status.LastReason = fmt.Sprintf("%s command is not configured", operationType)
		return nil
	}

	execution, err := r.prepareWorkerOperationExecution(ctx, customScaler, operationType, now)
	if err != nil {
		return err
	}
	if execution == nil {
		switch operationType {
		case workerOperationDelete:
			if plan.Status.PendingDeleteCount > 0 {
				plan.Status.PendingDeleteCount--
			}
		case workerOperationCreate:
			if plan.Status.PendingCreateCount > 0 {
				plan.Status.PendingCreateCount--
			}
		}
		plan.Status.EffectiveWorkerCount = plan.Status.ObservedReadyWorkerCount + plan.Status.PendingCreateCount - plan.Status.PendingDeleteCount
		plan.Status.LastAction = "executor-no-target"
		plan.Status.LastReason = fmt.Sprintf("no target node available for %s operation", operationType)
		return nil
	}

	job := buildWorkerOperationJob(customScaler, &plan.Status, operationType, r.WorkerExecutor, *execution, now)
	if err := r.Create(ctx, &job); err != nil {
		return err
	}

	startedAt := metav1.NewTime(now)
	plan.Status.ActiveOperations = append(plan.Status.ActiveOperations, autoscalingv1.WorkerOperationStatus{
		OperationType:  operationType,
		TargetNodeName: execution.TargetNodeName,
		Phase:          workerOperationPhaseRunning,
		JobNamespace:   job.Namespace,
		JobName:        job.Name,
		RequestedCount: 1,
		Message:        "executor job created",
		StartedAt:      &startedAt,
	})
	syncLegacyActiveOperation(&plan.Status)
	plan.Status.LastAction = "executor-started"
	plan.Status.LastReason = fmt.Sprintf("%s job %s/%s created for node %s", operationType, job.Namespace, job.Name, execution.TargetNodeName)

	return nil
}

func (r *CustomScalerControllerBase) prepareWorkerOperationExecution(
	ctx context.Context,
	customScaler *autoscalingv1.CustomScaler,
	operationType string,
	now time.Time,
) (*workerOperationExecution, error) {
	baseCommand := r.WorkerExecutor.CreateCommand
	switch operationType {
	case workerOperationCreate:
		targetNodeName := generateWorkerNodeName(r.WorkerExecutor.NodeNamePrefix, customScaler.Name, now)
		return &workerOperationExecution{
			Command:        buildWorkerOperationCommand(baseCommand, targetNodeName),
			TargetNodeName: targetNodeName,
		}, nil
	case workerOperationDelete:
		baseCommand = r.WorkerExecutor.DeleteCommand
		targetNodeName, err := r.selectWorkerNodeForDeletion(ctx, customScaler.Spec.WorkerPrototype)
		if err != nil {
			return nil, err
		}
		if targetNodeName == "" {
			return nil, nil
		}
		return &workerOperationExecution{
			Command:        buildWorkerOperationCommand(baseCommand, targetNodeName),
			TargetNodeName: targetNodeName,
		}, nil
	default:
		return nil, fmt.Errorf("unsupported worker operation type: %s", operationType)
	}
}

func buildWorkerOperationJob(
	customScaler *autoscalingv1.CustomScaler,
	status *autoscalingv1.WorkerPrototypeStatus,
	operationType string,
	config WorkerExecutorConfig,
	execution workerOperationExecution,
	now time.Time,
) batchv1.Job {
	backoffLimit := int32(0)
	sshSecretDefaultMode := int32(0o400)
	namePrefix := fmt.Sprintf("%s-worker-%s-", customScaler.Name, operationType)
	jobName := sanitizeJobName(namePrefix + rand.String(5))

	container := corev1.Container{
		Name:    "executor",
		Image:   config.Image,
		Command: []string{"/bin/sh", "-c", execution.Command},
		Env: []corev1.EnvVar{
			{Name: "SCALER_NAME", Value: customScaler.Name},
			{Name: "SCALER_NAMESPACE", Value: customScaler.Namespace},
			{Name: "WORKER_OPERATION_TYPE", Value: operationType},
			{Name: "WORKER_TARGET_NODE_NAME", Value: execution.TargetNodeName},
			{Name: "WORKER_TARGET_COUNT", Value: fmt.Sprintf("%d", status.TargetWorkerCount)},
			{Name: "WORKER_OBSERVED_READY_COUNT", Value: fmt.Sprintf("%d", status.ObservedReadyWorkerCount)},
			{Name: "WORKER_PENDING_CREATE_COUNT", Value: fmt.Sprintf("%d", status.PendingCreateCount)},
			{Name: "WORKER_PENDING_DELETE_COUNT", Value: fmt.Sprintf("%d", status.PendingDeleteCount)},
			{Name: "WORKER_EFFECTIVE_COUNT", Value: fmt.Sprintf("%d", status.EffectiveWorkerCount)},
			{Name: "WORKER_ENSURE_TIME", Value: now.UTC().Format(time.RFC3339)},
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
		Affinity:           controlPlaneAffinity(),
		Tolerations:        controlPlaneTolerations(),
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
					Affinity:           podSpec.Affinity,
					Tolerations:        podSpec.Tolerations,
				},
			},
		},
	}
}

func (r *CustomScalerControllerBase) selectWorkerNodeForDeletion(
	ctx context.Context,
	spec *autoscalingv1.WorkerPrototypeSpec,
) (string, error) {
	nodes, err := r.listManagedWorkerNodes(ctx, spec)
	if err != nil {
		return "", err
	}

	var podList corev1.PodList
	if err := r.List(ctx, &podList); err != nil {
		return "", err
	}

	return chooseWorkerNodeForDeletion(nodes, podList.Items), nil
}

func chooseWorkerNodeForDeletion(nodes []corev1.Node, pods []corev1.Pod) string {
	type candidate struct {
		NodeName         string
		CreationUnixNano int64
		PodCount         int
	}

	candidates := make([]candidate, 0, len(nodes))
	nodeNames := map[string]struct{}{}
	for _, node := range nodes {
		if !isNodeReady(&node) {
			continue
		}
		candidates = append(candidates, candidate{
			NodeName:         node.Name,
			CreationUnixNano: node.CreationTimestamp.Time.UnixNano(),
		})
		nodeNames[node.Name] = struct{}{}
	}

	if len(candidates) == 0 {
		return ""
	}

	podCounts := map[string]int{}
	for _, pod := range pods {
		nodeName := pod.Spec.NodeName
		if nodeName == "" {
			continue
		}
		if _, exists := nodeNames[nodeName]; !exists {
			continue
		}
		if pod.DeletionTimestamp != nil {
			continue
		}
		if pod.Status.Phase == corev1.PodSucceeded || pod.Status.Phase == corev1.PodFailed {
			continue
		}
		if isDaemonSetManagedPod(&pod) {
			continue
		}
		podCounts[nodeName]++
	}

	for i := range candidates {
		candidates[i].PodCount = podCounts[candidates[i].NodeName]
	}

	sort.Slice(candidates, func(i, j int) bool {
		if candidates[i].PodCount != candidates[j].PodCount {
			return candidates[i].PodCount < candidates[j].PodCount
		}
		if candidates[i].CreationUnixNano != candidates[j].CreationUnixNano {
			return candidates[i].CreationUnixNano > candidates[j].CreationUnixNano
		}
		return candidates[i].NodeName < candidates[j].NodeName
	})

	return candidates[0].NodeName
}

func isDaemonSetManagedPod(pod *corev1.Pod) bool {
	for _, ownerRef := range pod.OwnerReferences {
		if ownerRef.Kind == "DaemonSet" && ownerRef.Controller != nil && *ownerRef.Controller {
			return true
		}
	}

	return false
}

func buildWorkerOperationCommand(baseCommand, targetNodeName string) string {
	baseCommand = strings.TrimSpace(baseCommand)
	if targetNodeName == "" {
		return baseCommand
	}

	return fmt.Sprintf("%s %s", baseCommand, shellQuote(targetNodeName))
}

func generateWorkerNodeName(prefix, scalerName string, now time.Time) string {
	sanitizedPrefix := sanitizeNameComponent(prefix)
	if sanitizedPrefix == "" {
		sanitizedPrefix = "k3s-worker"
	}

	sanitizedScalerName := sanitizeNameComponent(scalerName)
	if sanitizedScalerName == "" {
		sanitizedScalerName = "scaler"
	}

	return sanitizeJobName(fmt.Sprintf("%s-%s-%d-%s", sanitizedPrefix, sanitizedScalerName, now.UTC().Unix(), rand.String(4)))
}

func sanitizeNameComponent(value string) string {
	var builder strings.Builder
	lower := strings.ToLower(strings.TrimSpace(value))
	lastWasDash := false

	for _, r := range lower {
		isAlphaNum := (r >= 'a' && r <= 'z') || (r >= '0' && r <= '9')
		if isAlphaNum {
			builder.WriteRune(r)
			lastWasDash = false
			continue
		}
		if !lastWasDash {
			builder.WriteByte('-')
			lastWasDash = true
		}
	}

	return strings.Trim(builder.String(), "-")
}

func shellQuote(value string) string {
	if value == "" {
		return "''"
	}

	return "'" + strings.ReplaceAll(value, "'", "'\"'\"'") + "'"
}

func rollbackWorkerOperation(plan *workerPrototypePlan, active *autoscalingv1.WorkerOperationStatus) {
	rollbackUnstartedWorkerOperations(plan, active.OperationType, activeOperationRequestedCount(*active))
}

func rollbackUnstartedWorkerOperations(plan *workerPrototypePlan, operationType string, count int32) {
	if count <= 0 {
		return
	}

	switch operationType {
	case workerOperationCreate:
		rollbackCount := minInt32(plan.Status.PendingCreateCount, count)
		if rollbackCount > 0 {
			plan.Status.PendingCreateCount -= rollbackCount
		}
	case workerOperationDelete:
		rollbackCount := minInt32(plan.Status.PendingDeleteCount, count)
		if rollbackCount > 0 {
			plan.Status.PendingDeleteCount -= rollbackCount
		}
	}

	plan.Status.EffectiveWorkerCount = plan.Status.ObservedReadyWorkerCount + plan.Status.PendingCreateCount - plan.Status.PendingDeleteCount
}

func workerOperationTimedOut(
	active *autoscalingv1.WorkerOperationStatus,
	now time.Time,
	timeout time.Duration,
) bool {
	if active == nil || timeout <= 0 {
		return false
	}

	reference := active.CommandFinishedAt
	if reference == nil {
		reference = active.StartedAt
	}
	if reference == nil {
		return false
	}

	return now.Sub(reference.Time) >= timeout
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

func normalizePositiveInt32(value, fallback int32) int32 {
	if value > 0 {
		return value
	}
	return fallback
}
