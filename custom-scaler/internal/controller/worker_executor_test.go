package controller

import (
	"context"
	"testing"
	"time"

	batchv1 "k8s.io/api/batch/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"

	autoscalingv1 "github.com/Boygioi15/predictive-autoscaling-k8s-test/api/v1"
)

func TestBuildWorkerOperationJobInjectsConfigAndSecret(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	customScaler := &autoscalingv1.CustomScaler{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "prime-scaler",
			Namespace: "default",
		},
	}

	status := &autoscalingv1.WorkerPrototypeStatus{
		TargetWorkerCount:        3,
		ObservedReadyWorkerCount: 1,
		PendingCreateCount:       1,
		PendingDeleteCount:       0,
		EffectiveWorkerCount:     2,
	}

	config := WorkerExecutorConfig{
		Namespace:          "custom-scaler-system",
		ServiceAccountName: "custom-scaler-controller-manager",
		Image:              "docker.io/boygioi/vm-job:latest",
		CreateCommand:      "/workspace/linux-script/executor-create-worker.sh",
		NodeNamePrefix:     "k3s-worker",
		ConfigMapName:      "custom-scaler-vm-job-config",
		SecretName:         "custom-scaler-vm-job-secret",
		SecretMountPath:    "/var/run/vm-job-secret",
		TTLSecondsAfterRun: 3600,
	}

	execution := workerOperationExecution{
		Command:        "/workspace/linux-script/executor-create-worker.sh 'k3s-worker-prime-1700000000-abcd'",
		TargetNodeName: "k3s-worker-prime-1700000000-abcd",
	}

	job := buildWorkerOperationJob(customScaler, status, workerOperationCreate, config, execution, now)
	if job.Namespace != "custom-scaler-system" {
		t.Fatalf("expected job namespace custom-scaler-system, got %s", job.Namespace)
	}

	if len(job.Spec.Template.Spec.Containers) != 1 {
		t.Fatalf("expected one container, got %d", len(job.Spec.Template.Spec.Containers))
	}

	container := job.Spec.Template.Spec.Containers[0]
	if len(container.EnvFrom) != 1 || container.EnvFrom[0].ConfigMapRef == nil {
		t.Fatalf("expected one ConfigMap envFrom source")
	}
	if container.EnvFrom[0].ConfigMapRef.Name != "custom-scaler-vm-job-config" {
		t.Fatalf("unexpected ConfigMap name: %s", container.EnvFrom[0].ConfigMapRef.Name)
	}
	if got := container.Command[2]; got != execution.Command {
		t.Fatalf("expected command %q, got %q", execution.Command, got)
	}

	foundVultrSecret := false
	foundK3STokenSecret := false
	foundTargetNodeName := false
	for _, envVar := range container.Env {
		if envVar.Name == "VULTR_API_KEY" && envVar.ValueFrom != nil && envVar.ValueFrom.SecretKeyRef != nil {
			foundVultrSecret = envVar.ValueFrom.SecretKeyRef.Name == "custom-scaler-vm-job-secret" && envVar.ValueFrom.SecretKeyRef.Key == "VULTR_API_KEY"
		}
		if envVar.Name == "K3S_TOKEN" && envVar.ValueFrom != nil && envVar.ValueFrom.SecretKeyRef != nil {
			foundK3STokenSecret = envVar.ValueFrom.SecretKeyRef.Name == "custom-scaler-vm-job-secret" && envVar.ValueFrom.SecretKeyRef.Key == "K3S_TOKEN"
		}
		if envVar.Name == "WORKER_TARGET_NODE_NAME" && envVar.Value == execution.TargetNodeName {
			foundTargetNodeName = true
		}
	}
	if !foundVultrSecret {
		t.Fatalf("expected VULTR_API_KEY to come from the vm-job secret")
	}
	if !foundK3STokenSecret {
		t.Fatalf("expected K3S_TOKEN to come from the vm-job secret")
	}
	if !foundTargetNodeName {
		t.Fatalf("expected WORKER_TARGET_NODE_NAME env to be %q", execution.TargetNodeName)
	}

	if len(container.VolumeMounts) != 1 {
		t.Fatalf("expected one secret volume mount, got %d", len(container.VolumeMounts))
	}
	if container.VolumeMounts[0].MountPath != "/var/run/vm-job-secret" {
		t.Fatalf("unexpected secret mount path: %s", container.VolumeMounts[0].MountPath)
	}

	if len(job.Spec.Template.Spec.Volumes) != 1 {
		t.Fatalf("expected one volume, got %d", len(job.Spec.Template.Spec.Volumes))
	}
	secretVolume := job.Spec.Template.Spec.Volumes[0].VolumeSource.Secret
	if secretVolume == nil {
		t.Fatalf("expected secret volume source")
	}
	if secretVolume.SecretName != "custom-scaler-vm-job-secret" {
		t.Fatalf("unexpected secret volume name: %s", secretVolume.SecretName)
	}
	if secretVolume.DefaultMode == nil || *secretVolume.DefaultMode != 0o400 {
		t.Fatalf("expected secret volume mode 0400, got %v", secretVolume.DefaultMode)
	}
	if job.Spec.Template.Spec.Affinity == nil || job.Spec.Template.Spec.Affinity.NodeAffinity == nil {
		t.Fatalf("expected worker job to be pinned to the control plane")
	}
	terms := job.Spec.Template.Spec.Affinity.NodeAffinity.RequiredDuringSchedulingIgnoredDuringExecution
	if terms == nil || len(terms.NodeSelectorTerms) != 2 {
		t.Fatalf("expected worker job to allow control-plane or master labels, got %#v", terms)
	}
	if len(job.Spec.Template.Spec.Tolerations) != 3 {
		t.Fatalf("expected worker job to tolerate control-plane and infra taints, got %d tolerations", len(job.Spec.Template.Spec.Tolerations))
	}
	if !containsToleration(job.Spec.Template.Spec.Tolerations, "role", corev1.TolerationOpEqual, "infra", corev1.TaintEffectNoSchedule) {
		t.Fatalf("expected worker job to tolerate role=infra:NoSchedule")
	}
}

func containsToleration(
	tolerations []corev1.Toleration,
	key string,
	operator corev1.TolerationOperator,
	value string,
	effect corev1.TaintEffect,
) bool {
	for _, toleration := range tolerations {
		if toleration.Key == key &&
			toleration.Operator == operator &&
			toleration.Value == value &&
			toleration.Effect == effect {
			return true
		}
	}
	return false
}

func TestChooseWorkerNodeForDeletionPrefersFewestNonDaemonPods(t *testing.T) {
	nodes := []corev1.Node{
		{
			ObjectMeta: metav1.ObjectMeta{
				Name:              "worker-a",
				CreationTimestamp: metav1.NewTime(time.Unix(100, 0)),
			},
			Status: corev1.NodeStatus{
				Conditions: []corev1.NodeCondition{{Type: corev1.NodeReady, Status: corev1.ConditionTrue}},
			},
		},
		{
			ObjectMeta: metav1.ObjectMeta{
				Name:              "worker-b",
				CreationTimestamp: metav1.NewTime(time.Unix(200, 0)),
			},
			Status: corev1.NodeStatus{
				Conditions: []corev1.NodeCondition{{Type: corev1.NodeReady, Status: corev1.ConditionTrue}},
			},
		},
	}

	pods := []corev1.Pod{
		{
			ObjectMeta: metav1.ObjectMeta{Name: "app-a"},
			Spec:       corev1.PodSpec{NodeName: "worker-a"},
			Status:     corev1.PodStatus{Phase: corev1.PodRunning},
		},
		{
			ObjectMeta: metav1.ObjectMeta{Name: "app-b"},
			Spec:       corev1.PodSpec{NodeName: "worker-a"},
			Status:     corev1.PodStatus{Phase: corev1.PodRunning},
		},
		{
			ObjectMeta: metav1.ObjectMeta{
				Name:            "daemon-b",
				OwnerReferences: []metav1.OwnerReference{{Kind: "DaemonSet", Controller: boolPtr(true)}},
			},
			Spec:   corev1.PodSpec{NodeName: "worker-b"},
			Status: corev1.PodStatus{Phase: corev1.PodRunning},
		},
	}

	got := chooseWorkerNodeForDeletion(nodes, pods)
	if got != "worker-b" {
		t.Fatalf("expected worker-b to be chosen, got %s", got)
	}
}

func TestChooseWorkerNodeForDeletionBreaksTiesByNewestNode(t *testing.T) {
	nodes := []corev1.Node{
		{
			ObjectMeta: metav1.ObjectMeta{
				Name:              "worker-old",
				CreationTimestamp: metav1.NewTime(time.Unix(100, 0)),
			},
			Status: corev1.NodeStatus{
				Conditions: []corev1.NodeCondition{{Type: corev1.NodeReady, Status: corev1.ConditionTrue}},
			},
		},
		{
			ObjectMeta: metav1.ObjectMeta{
				Name:              "worker-new",
				CreationTimestamp: metav1.NewTime(time.Unix(200, 0)),
			},
			Status: corev1.NodeStatus{
				Conditions: []corev1.NodeCondition{{Type: corev1.NodeReady, Status: corev1.ConditionTrue}},
			},
		},
	}

	got := chooseWorkerNodeForDeletion(nodes, nil)
	if got != "worker-new" {
		t.Fatalf("expected worker-new to be chosen on tie, got %s", got)
	}
}

func TestReconcileActiveWorkerOperationTimesOutWaitingForObservation(t *testing.T) {
	scheme := runtime.NewScheme()
	if err := batchv1.AddToScheme(scheme); err != nil {
		t.Fatalf("failed to add batchv1 to scheme: %v", err)
	}

	job := &batchv1.Job{
		ObjectMeta: metav1.ObjectMeta{
			Name:      "delete-job",
			Namespace: "custom-scaler-system",
		},
		Status: batchv1.JobStatus{
			Conditions: []batchv1.JobCondition{
				{
					Type:   batchv1.JobComplete,
					Status: corev1.ConditionTrue,
				},
			},
		},
	}

	reconciler := &CustomScalerReconciler{
		Client: fake.NewClientBuilder().WithScheme(scheme).WithObjects(job).Build(),
		WorkerExecutor: WorkerExecutorConfig{
			ObservationTimeout: 5 * time.Minute,
		},
	}

	now := time.Unix(1_700_000_000, 0)
	commandFinishedAt := metav1.NewTime(now.Add(-10 * time.Minute))
	active := &autoscalingv1.WorkerOperationStatus{
		OperationType:     workerOperationDelete,
		TargetNodeName:    "k3s-worker-5",
		Phase:             workerOperationPhaseWaitObservation,
		JobNamespace:      "custom-scaler-system",
		JobName:           "delete-job",
		RequestedCount:    1,
		CommandFinishedAt: &commandFinishedAt,
	}

	customScaler := &autoscalingv1.CustomScaler{
		Status: autoscalingv1.CustomScalerStatus{
			WorkerPrototype: &autoscalingv1.WorkerPrototypeStatus{
				ObservedReadyWorkerCount: 5,
				PendingDeleteCount:       1,
			},
		},
	}
	plan := &workerPrototypePlan{
		Status: autoscalingv1.WorkerPrototypeStatus{
			ObservedReadyWorkerCount: 5,
			PendingDeleteCount:       1,
			EffectiveWorkerCount:     4,
			ActiveOperations:         []autoscalingv1.WorkerOperationStatus{*active},
			ActiveOperation:          active,
		},
	}

	if err := reconciler.reconcileActiveWorkerOperations(context.Background(), customScaler, plan, now); err != nil {
		t.Fatalf("expected no error, got %v", err)
	}

	if len(plan.Status.ActiveOperations) != 0 {
		t.Fatalf("expected active operations to be cleared after timeout, got %d", len(plan.Status.ActiveOperations))
	}
	if plan.Status.ActiveOperation != nil {
		t.Fatalf("expected legacy active operation mirror to be cleared after timeout")
	}
	if plan.Status.PendingDeleteCount != 0 {
		t.Fatalf("expected pending delete count to be rolled back to 0, got %d", plan.Status.PendingDeleteCount)
	}
	if plan.Status.EffectiveWorkerCount != 5 {
		t.Fatalf("expected effective worker count to return to observed count 5, got %d", plan.Status.EffectiveWorkerCount)
	}
	if plan.Status.LastAction != "executor-observation-timeout" {
		t.Fatalf("unexpected last action: %s", plan.Status.LastAction)
	}
}

func boolPtr(value bool) *bool {
	return &value
}
