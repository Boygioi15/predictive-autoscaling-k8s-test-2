package controller

import (
	"os"
	"strconv"
)

const (
	defaultSafeRPSPerPod = 20.0
	defaultSafetyFactor  = 1.10
	defaultSparePod      = int32(1)
	defaultMinReplicas   = int32(1)
	defaultMaxReplicas   = int32(10)
)

type ScalingDefaults struct {
	SafeRPSPerPod float64
	SafetyFactor  float64
	SparePod      int32
	MinReplicas   int32
	MaxReplicas   int32
}

func LoadScalingDefaultsFromEnv() ScalingDefaults {
	return ScalingDefaults{
		SafeRPSPerPod: getEnvFloat("SCALER_SAFE_RPS_PER_POD", defaultSafeRPSPerPod),
		SafetyFactor:  getEnvFloat("SCALER_SAFETY_FACTOR", defaultSafetyFactor),
		SparePod:      getEnvInt32("SCALER_SPARE_POD", defaultSparePod),
		MinReplicas:   getEnvInt32("SCALER_MIN_REPLICAS", defaultMinReplicas),
		MaxReplicas:   getEnvInt32("SCALER_MAX_REPLICAS", defaultMaxReplicas),
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
	return d
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
