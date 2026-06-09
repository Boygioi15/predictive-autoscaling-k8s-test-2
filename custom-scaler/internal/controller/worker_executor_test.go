package controller

import (
	"testing"
	"time"

	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

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
		LoadBalancerID:     "lb-1234",
		NodeNamePrefix:     "k3s-worker",
		ConfigMapName:      "custom-scaler-vm-job-config",
		SecretName:         "custom-scaler-vm-job-secret",
		SecretMountPath:    "/var/run/vm-job-secret",
		TTLSecondsAfterRun: 3600,
	}

	job := buildWorkerOperationJob(customScaler, status, workerOperationCreate, config, now)
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

	foundVultrSecret := false
	foundK3STokenSecret := false
	for _, envVar := range container.Env {
		if envVar.Name == "VULTR_API_KEY" && envVar.ValueFrom != nil && envVar.ValueFrom.SecretKeyRef != nil {
			foundVultrSecret = envVar.ValueFrom.SecretKeyRef.Name == "custom-scaler-vm-job-secret" && envVar.ValueFrom.SecretKeyRef.Key == "VULTR_API_KEY"
		}
		if envVar.Name == "K3S_TOKEN" && envVar.ValueFrom != nil && envVar.ValueFrom.SecretKeyRef != nil {
			foundK3STokenSecret = envVar.ValueFrom.SecretKeyRef.Name == "custom-scaler-vm-job-secret" && envVar.ValueFrom.SecretKeyRef.Key == "K3S_TOKEN"
		}
	}
	if !foundVultrSecret {
		t.Fatalf("expected VULTR_API_KEY to come from the vm-job secret")
	}
	if !foundK3STokenSecret {
		t.Fatalf("expected K3S_TOKEN to come from the vm-job secret")
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
}
