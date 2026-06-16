package controller

import (
	"os"
	"strconv"
)

const (
	defaultSafeRPSPerPod                 = 20.0
	defaultSafetyFactor                  = 1.10
	defaultSparePod                      = int32(1)
	defaultMinReplicas                   = int32(1)
	defaultMaxReplicas                   = int32(10)
	defaultScaleDownPolicy               = "dangerous"
	defaultAppP95ThresholdSeconds        = 0.50
	defaultIngressP95ThresholdSecs       = 0.50
	defaultIngressDeploymentName         = "ingress-nginx-controller"
	defaultIngressDeploymentNS           = "ingress-nginx"
	defaultIngressReplicasPerWorker      = int32(2)
	defaultIngressPressureRequiredPoints = int32(3)
	defaultIngressPressureIncreaseStep   = int32(1)
	defaultIngressPressureDecreaseStep   = int32(2)
	defaultIngressPressureMaxBump        = int32(10)
	defaultIngressPressureWorkerStep     = int32(1)
	defaultIngressPressureReplicaStep    = int32(2)
	defaultWorkerNodeAllocMilliCPU       = int32(1800)
	defaultWorkerPodRequestMilliCPU      = int32(600)
	defaultWorkerSafetyPods              = int32(1)
	defaultWorkerCapacityStrategy        = "direct-divide"
	defaultWorkerMinCount                = int32(0)
	defaultWorkerMaxCount                = int32(0)
)

type ScalingDefaults struct {
	SafeRPSPerPod                 float64
	SafetyFactor                  float64
	SparePod                      int32
	MinReplicas                   int32
	MaxReplicas                   int32
	ScaleDownPolicy               string
	AppP95ThresholdSeconds        float64
	IngressP95ThresholdSec        float64
	IngressDeploymentName         string
	IngressDeploymentNS           string
	IngressReplicasPerWorker      int32
	IngressPressureRequiredPoints int32
	IngressPressureIncreaseStep   int32
	IngressPressureDecreaseStep   int32
	IngressPressureMaxBump        int32
	IngressPressureWorkerStep     int32
	IngressPressureReplicaStep    int32
}

type WorkerCapacityDefaults struct {
	NodeAllocatableMilliCPU int32
	PodRequestMilliCPU      int32
	SafetyPods              int32
	CapacityStrategy        string
	MinWorkerCount          int32
	MaxWorkerCount          int32
}

func LoadScalingDefaultsFromEnv() ScalingDefaults {
	return ScalingDefaults{
		SafeRPSPerPod:                 getEnvFloat("SCALER_SAFE_RPS_PER_POD", defaultSafeRPSPerPod),
		SafetyFactor:                  getEnvFloat("SCALER_SAFETY_FACTOR", defaultSafetyFactor),
		SparePod:                      getEnvInt32("SCALER_SPARE_POD", defaultSparePod),
		MinReplicas:                   getEnvInt32("SCALER_MIN_REPLICAS", defaultMinReplicas),
		MaxReplicas:                   getEnvInt32("SCALER_MAX_REPLICAS", defaultMaxReplicas),
		ScaleDownPolicy:               getEnvString("SCALER_SCALE_DOWN_POLICY", defaultScaleDownPolicy),
		AppP95ThresholdSeconds:        getEnvFloat("SCALER_APP_P95_THRESHOLD_SECONDS", defaultAppP95ThresholdSeconds),
		IngressP95ThresholdSec:        getEnvFloat("SCALER_INGRESS_P95_THRESHOLD_SECONDS", defaultIngressP95ThresholdSecs),
		IngressDeploymentName:         getEnvString("SCALER_INGRESS_DEPLOYMENT_NAME", defaultIngressDeploymentName),
		IngressDeploymentNS:           getEnvString("SCALER_INGRESS_DEPLOYMENT_NAMESPACE", defaultIngressDeploymentNS),
		IngressReplicasPerWorker:      getEnvInt32("SCALER_INGRESS_REPLICAS_PER_WORKER", defaultIngressReplicasPerWorker),
		IngressPressureRequiredPoints: getEnvInt32("SCALER_INGRESS_PRESSURE_REQUIRED_POINTS", defaultIngressPressureRequiredPoints),
		IngressPressureIncreaseStep:   getEnvInt32("SCALER_INGRESS_PRESSURE_INCREASE_STEP", defaultIngressPressureIncreaseStep),
		IngressPressureDecreaseStep:   getEnvInt32("SCALER_INGRESS_PRESSURE_DECREASE_STEP", defaultIngressPressureDecreaseStep),
		IngressPressureMaxBump:        getEnvInt32("SCALER_INGRESS_PRESSURE_MAX_BUMP", defaultIngressPressureMaxBump),
		IngressPressureWorkerStep:     getEnvInt32("SCALER_INGRESS_PRESSURE_WORKER_STEP", defaultIngressPressureWorkerStep),
		IngressPressureReplicaStep:    getEnvInt32("SCALER_INGRESS_PRESSURE_REPLICA_STEP", defaultIngressPressureReplicaStep),
	}
}

func LoadWorkerCapacityDefaultsFromEnv() WorkerCapacityDefaults {
	return WorkerCapacityDefaults{
		NodeAllocatableMilliCPU: getEnvInt32("SCALER_WORKER_NODE_ALLOCATABLE_MILLICPU", defaultWorkerNodeAllocMilliCPU),
		PodRequestMilliCPU:      getEnvInt32("SCALER_WORKER_POD_REQUEST_MILLICPU", defaultWorkerPodRequestMilliCPU),
		SafetyPods:              getEnvInt32("SCALER_WORKER_SAFETY_PODS", defaultWorkerSafetyPods),
		CapacityStrategy:        getEnvString("SCALER_WORKER_CAPACITY_STRATEGY", defaultWorkerCapacityStrategy),
		MinWorkerCount:          getEnvInt32("SCALER_WORKER_MIN_COUNT", defaultWorkerMinCount),
		MaxWorkerCount:          getEnvInt32("SCALER_WORKER_MAX_COUNT", defaultWorkerMaxCount),
	}
}

func (d ScalingDefaults) normalized() ScalingDefaults {
	if d.SafeRPSPerPod <= 0 {
		d.SafeRPSPerPod = defaultSafeRPSPerPod
	}
	if d.SafetyFactor <= 0 {
		d.SafetyFactor = defaultSafetyFactor
	}
	if d.SparePod < 0 {
		d.SparePod = defaultSparePod
	}
	if d.MinReplicas <= 0 {
		d.MinReplicas = defaultMinReplicas
	}
	if d.MaxReplicas < d.MinReplicas {
		d.MaxReplicas = d.MinReplicas
	}
	switch d.ScaleDownPolicy {
	case "safe", "dangerous":
	default:
		d.ScaleDownPolicy = defaultScaleDownPolicy
	}
	if d.AppP95ThresholdSeconds <= 0 {
		d.AppP95ThresholdSeconds = defaultAppP95ThresholdSeconds
	}
	if d.IngressP95ThresholdSec <= 0 {
		d.IngressP95ThresholdSec = defaultIngressP95ThresholdSecs
	}
	if d.IngressReplicasPerWorker < 0 {
		d.IngressReplicasPerWorker = defaultIngressReplicasPerWorker
	}
	if d.IngressPressureRequiredPoints <= 0 {
		d.IngressPressureRequiredPoints = defaultIngressPressureRequiredPoints
	}
	if d.IngressPressureIncreaseStep <= 0 {
		d.IngressPressureIncreaseStep = defaultIngressPressureIncreaseStep
	}
	if d.IngressPressureDecreaseStep <= 0 {
		d.IngressPressureDecreaseStep = defaultIngressPressureDecreaseStep
	}
	if d.IngressPressureMaxBump < 0 {
		d.IngressPressureMaxBump = defaultIngressPressureMaxBump
	}
	if d.IngressPressureWorkerStep < 0 {
		d.IngressPressureWorkerStep = defaultIngressPressureWorkerStep
	}
	if d.IngressPressureReplicaStep < 0 {
		d.IngressPressureReplicaStep = defaultIngressPressureReplicaStep
	}
	return d
}

func (d WorkerCapacityDefaults) normalized() WorkerCapacityDefaults {
	if d.NodeAllocatableMilliCPU <= 0 {
		d.NodeAllocatableMilliCPU = defaultWorkerNodeAllocMilliCPU
	}
	if d.PodRequestMilliCPU <= 0 {
		d.PodRequestMilliCPU = defaultWorkerPodRequestMilliCPU
	}
	if d.SafetyPods < 0 {
		d.SafetyPods = defaultWorkerSafetyPods
	}
	if d.MinWorkerCount < 0 {
		d.MinWorkerCount = defaultWorkerMinCount
	}
	if d.MaxWorkerCount < 0 {
		d.MaxWorkerCount = defaultWorkerMaxCount
	}
	if d.MaxWorkerCount > 0 && d.MaxWorkerCount < d.MinWorkerCount {
		d.MaxWorkerCount = d.MinWorkerCount
	}
	switch d.CapacityStrategy {
	case "direct-divide", "free-slots":
	default:
		d.CapacityStrategy = defaultWorkerCapacityStrategy
	}
	return d
}

func getEnvString(key string, fallback string) string {
	raw := os.Getenv(key)
	if raw == "" {
		return fallback
	}

	return raw
}

func getEnvFloat(key string, fallback float64) float64 {
	raw := os.Getenv(key)
	if raw == "" {
		return fallback
	}

	parsed, err := strconv.ParseFloat(raw, 64)
	if err != nil {
		return fallback
	}

	return parsed
}

func getEnvInt32(key string, fallback int32) int32 {
	raw := os.Getenv(key)
	if raw == "" {
		return fallback
	}

	parsed, err := strconv.ParseInt(raw, 10, 32)
	if err != nil {
		return fallback
	}

	return int32(parsed)
}
