package controller

import (
	"os"
	"strconv"
)

const (
	defaultRequestsPerPod           = 25.0
	defaultCPUSecondsPerPod         = 30.0
	defaultSafetyFactor             = 1.10
	defaultSparePod                 = int32(1)
	defaultMinReplicas              = int32(1)
	defaultMaxReplicas              = int32(10)
	defaultScaleDownPolicy          = "dangerous"
	defaultAppErrorRateThreshold    = 0.05
	defaultIngressP99ThresholdSecs  = 0.50
	defaultIngressDeploymentName    = "ingress-nginx-controller"
	defaultIngressDeploymentNS      = "ingress-nginx"
	defaultIngressReplicasPerWorker = int32(2)
	defaultReactiveRequiredPoints   = int32(2)
	defaultReactiveIncreaseStep     = int32(1)
	defaultReactiveDecreaseStep     = int32(2)
	defaultReactiveMaxBump          = int32(10)
	defaultReactiveReplicaStep      = int32(2)
	defaultWorkerNodeAllocMilliCPU  = int32(1800)
	defaultWorkerPodRequestMilliCPU = int32(600)
	defaultWorkerSafetyPods         = int32(1)
	defaultWorkerCapacityStrategy   = "direct-divide"
	defaultWorkerMinCount           = int32(0)
	defaultWorkerMaxCount           = int32(0)
	defaultForecastContractID       = "demo-linear-regression-v1"
)

type ScalingDefaults struct {
	RequestsPerPod           float64
	CPUSecondsPerPod         float64
	SafetyFactor             float64
	SparePod                 int32
	MinReplicas              int32
	MaxReplicas              int32
	ScaleDownPolicy          string
	AppErrorRateThreshold    float64
	IngressP99ThresholdSec   float64
	IngressDeploymentName    string
	IngressDeploymentNS      string
	IngressReplicasPerWorker int32
	ReactiveRequiredPoints   int32
	ReactiveIncreaseStep     int32
	ReactiveDecreaseStep     int32
	ReactiveMaxBump          int32
	ReactiveReplicaStep      int32
}

type WorkerCapacityDefaults struct {
	NodeAllocatableMilliCPU int32
	PodRequestMilliCPU      int32
	SafetyPods              int32
	CapacityStrategy        string
	MinWorkerCount          int32
	MaxWorkerCount          int32
}

type ForecastingDefaults struct {
	ContractID string
}

func LoadScalingDefaultsFromEnv() ScalingDefaults {
	return ScalingDefaults{
		RequestsPerPod:           getEnvFloat("SCALER_REQUESTS_PER_POD", defaultRequestsPerPod),
		CPUSecondsPerPod:         getEnvFloat("SCALER_CPU_SECONDS_PER_POD", defaultCPUSecondsPerPod),
		SafetyFactor:             getEnvFloat("SCALER_SAFETY_FACTOR", defaultSafetyFactor),
		SparePod:                 getEnvInt32("SCALER_SPARE_POD", defaultSparePod),
		MinReplicas:              getEnvInt32("SCALER_MIN_REPLICAS", defaultMinReplicas),
		MaxReplicas:              getEnvInt32("SCALER_MAX_REPLICAS", defaultMaxReplicas),
		ScaleDownPolicy:          getEnvString("SCALER_SCALE_DOWN_POLICY", defaultScaleDownPolicy),
		AppErrorRateThreshold:    getEnvFloat("SCALER_APP_ERROR_RATE_THRESHOLD", defaultAppErrorRateThreshold),
		IngressP99ThresholdSec:   getEnvFloat("SCALER_INGRESS_P99_THRESHOLD_SECONDS", defaultIngressP99ThresholdSecs),
		IngressDeploymentName:    getEnvString("SCALER_INGRESS_DEPLOYMENT_NAME", defaultIngressDeploymentName),
		IngressDeploymentNS:      getEnvString("SCALER_INGRESS_DEPLOYMENT_NAMESPACE", defaultIngressDeploymentNS),
		IngressReplicasPerWorker: getEnvInt32("SCALER_INGRESS_REPLICAS_PER_WORKER", defaultIngressReplicasPerWorker),
		ReactiveRequiredPoints:   getEnvInt32("SCALER_REACTIVE_REQUIRED_POINTS", defaultReactiveRequiredPoints),
		ReactiveIncreaseStep:     getEnvInt32("SCALER_REACTIVE_INCREASE_STEP", defaultReactiveIncreaseStep),
		ReactiveDecreaseStep:     getEnvInt32("SCALER_REACTIVE_DECREASE_STEP", defaultReactiveDecreaseStep),
		ReactiveMaxBump:          getEnvInt32("SCALER_REACTIVE_MAX_BUMP", defaultReactiveMaxBump),
		ReactiveReplicaStep:      getEnvInt32("SCALER_REACTIVE_REPLICA_STEP", defaultReactiveReplicaStep),
	}
}

func LoadForecastingDefaultsFromEnv() ForecastingDefaults {
	return ForecastingDefaults{
		ContractID: getEnvString("SCALER_FORECAST_CONTRACT_ID", defaultForecastContractID),
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
	if d.RequestsPerPod <= 0 {
		d.RequestsPerPod = defaultRequestsPerPod
	}
	if d.CPUSecondsPerPod <= 0 {
		d.CPUSecondsPerPod = defaultCPUSecondsPerPod
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
	if d.AppErrorRateThreshold <= 0 {
		d.AppErrorRateThreshold = defaultAppErrorRateThreshold
	}
	if d.IngressP99ThresholdSec <= 0 {
		d.IngressP99ThresholdSec = defaultIngressP99ThresholdSecs
	}
	if d.IngressReplicasPerWorker < 0 {
		d.IngressReplicasPerWorker = defaultIngressReplicasPerWorker
	}
	if d.ReactiveRequiredPoints <= 0 {
		d.ReactiveRequiredPoints = defaultReactiveRequiredPoints
	}
	if d.ReactiveIncreaseStep <= 0 {
		d.ReactiveIncreaseStep = defaultReactiveIncreaseStep
	}
	if d.ReactiveDecreaseStep <= 0 {
		d.ReactiveDecreaseStep = defaultReactiveDecreaseStep
	}
	if d.ReactiveMaxBump < 0 {
		d.ReactiveMaxBump = defaultReactiveMaxBump
	}
	if d.ReactiveReplicaStep < 0 {
		d.ReactiveReplicaStep = defaultReactiveReplicaStep
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
