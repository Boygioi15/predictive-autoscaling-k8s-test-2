package controller

import "testing"

func TestHasSustainedReactivePressureReturnsTrueWhenRecentIngressPointsAreAboveThreshold(t *testing.T) {
	policy := scalingPolicy{
		AppErrorRateThreshold:  0.05,
		IngressP99ThresholdSec: 0.50,
		ReactiveRequiredPoints: 2,
	}

	underPressure, reason := hasSustainedReactivePressure(
		map[string][]*float64{
			"ingress_p99_seconds": {
				float64Ptr(0.30),
				float64Ptr(0.60),
				float64Ptr(0.70),
			},
		},
		policy,
	)

	if !underPressure {
		t.Fatalf("expected sustained reactive pressure to be true")
	}
	if reason != "recent-reactive-pressure-all-triggered" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestHasSustainedReactivePressureReturnsTrueWhenRecentErrorRatePointsAreAboveThreshold(t *testing.T) {
	policy := scalingPolicy{
		AppErrorRateThreshold:  0.05,
		IngressP99ThresholdSec: 0.50,
		ReactiveRequiredPoints: 2,
	}

	underPressure, reason := hasSustainedReactivePressure(
		map[string][]*float64{
			"app_error_rate": {
				float64Ptr(0.02),
				float64Ptr(0.08),
				float64Ptr(0.07),
			},
		},
		policy,
	)

	if !underPressure {
		t.Fatalf("expected sustained reactive pressure to be true")
	}
	if reason != "recent-reactive-pressure-all-triggered" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestHasSustainedReactivePressureReturnsTrueWhenRecentPointsUseMixedSignals(t *testing.T) {
	policy := scalingPolicy{
		AppErrorRateThreshold:  0.05,
		IngressP99ThresholdSec: 0.50,
		ReactiveRequiredPoints: 2,
	}

	underPressure, reason := hasSustainedReactivePressure(
		map[string][]*float64{
			"ingress_p99_seconds": {
				float64Ptr(0.20),
				float64Ptr(0.60),
				float64Ptr(0.10),
			},
			"app_error_rate": {
				float64Ptr(0.01),
				float64Ptr(0.02),
				float64Ptr(0.06),
			},
		},
		policy,
	)

	if !underPressure {
		t.Fatalf("expected sustained reactive pressure to be true")
	}
	if reason != "recent-reactive-pressure-all-triggered" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestHasSustainedReactivePressureReturnsFalseWhenRecentPointsAreNotAllTriggered(t *testing.T) {
	policy := scalingPolicy{
		AppErrorRateThreshold:  0.05,
		IngressP99ThresholdSec: 0.50,
		ReactiveRequiredPoints: 2,
	}

	underPressure, reason := hasSustainedReactivePressure(
		map[string][]*float64{
			"ingress_p99_seconds": {
				float64Ptr(0.60),
				float64Ptr(0.20),
			},
			"app_error_rate": {
				float64Ptr(0.02),
				float64Ptr(0.03),
			},
		},
		policy,
	)

	if underPressure {
		t.Fatalf("expected sustained reactive pressure to be false")
	}
	if reason != "recent-reactive-pressure-not-triggered" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestHasSustainedReactivePressureReturnsFalseWhenThereAreFewerThanRequiredValidPoints(t *testing.T) {
	policy := scalingPolicy{
		AppErrorRateThreshold:  0.05,
		IngressP99ThresholdSec: 0.50,
		ReactiveRequiredPoints: 2,
	}

	underPressure, reason := hasSustainedReactivePressure(
		map[string][]*float64{
			"ingress_p99_seconds": {
				nil,
				float64Ptr(0.70),
			},
			"app_error_rate": {
				nil,
				nil,
			},
		},
		policy,
	)

	if underPressure {
		t.Fatalf("expected sustained reactive pressure to be false")
	}
	if reason != "insufficient-reactive-history" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestNextReactivePressureBumpIncreasesWhenReactivePressurePersists(t *testing.T) {
	policy := scalingPolicy{
		AppErrorRateThreshold:  0.05,
		IngressP99ThresholdSec: 0.50,
		ReactiveRequiredPoints: 2,
		ReactiveIncreaseStep:   1,
		ReactiveDecreaseStep:   2,
		ReactiveMaxBump:        10,
	}

	next, reason := nextReactivePressureBump(
		2,
		map[string][]*float64{
			"app_error_rate": {
				float64Ptr(0.04),
				float64Ptr(0.08),
				float64Ptr(0.09),
			},
		},
		policy,
	)

	if next != 3 {
		t.Fatalf("expected next bump to be 3, got %d", next)
	}
	if reason != "recent-reactive-pressure-all-triggered" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestNextReactivePressureBumpDecaysWhenReactivePressureClears(t *testing.T) {
	policy := scalingPolicy{
		AppErrorRateThreshold:  0.05,
		IngressP99ThresholdSec: 0.50,
		ReactiveRequiredPoints: 2,
		ReactiveIncreaseStep:   1,
		ReactiveDecreaseStep:   2,
		ReactiveMaxBump:        10,
	}

	next, reason := nextReactivePressureBump(
		3,
		map[string][]*float64{
			"ingress_p99_seconds": {
				float64Ptr(0.40),
				float64Ptr(0.20),
			},
			"app_error_rate": {
				float64Ptr(0.01),
				float64Ptr(0.03),
			},
		},
		policy,
	)

	if next != 1 {
		t.Fatalf("expected next bump to decay to 1, got %d", next)
	}
	if reason != "recent-reactive-pressure-not-triggered" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestNextReactivePressureBumpClampsAtZeroAndMax(t *testing.T) {
	policy := scalingPolicy{
		AppErrorRateThreshold:  0.05,
		IngressP99ThresholdSec: 0.50,
		ReactiveRequiredPoints: 2,
		ReactiveIncreaseStep:   2,
		ReactiveDecreaseStep:   2,
		ReactiveMaxBump:        4,
	}

	high, _ := nextReactivePressureBump(
		3,
		map[string][]*float64{
			"ingress_p99_seconds": {
				float64Ptr(0.60),
				float64Ptr(0.70),
			},
		},
		policy,
	)
	if high != 4 {
		t.Fatalf("expected next bump to clamp at 4, got %d", high)
	}

	low, _ := nextReactivePressureBump(
		1,
		map[string][]*float64{
			"app_error_rate": {
				float64Ptr(0.01),
				float64Ptr(0.02),
			},
		},
		policy,
	)
	if low != 0 {
		t.Fatalf("expected next bump to clamp at 0, got %d", low)
	}
}

func TestAllowIngressScaleDownAllowsOnlyWhenLastThreeIngressPointsAreBelowThreshold(t *testing.T) {
	policy := scalingPolicy{
		IngressP99ThresholdSec: 0.50,
		ReactiveRequiredPoints: 3,
	}

	allowed, reason := allowIngressScaleDown(
		map[string][]*float64{
			"ingress_p99_seconds": {
				float64Ptr(0.70),
				float64Ptr(0.40),
				float64Ptr(0.30),
				float64Ptr(0.20),
			},
		},
		policy,
	)

	if !allowed {
		t.Fatalf("expected ingress scale down to be allowed, got false with reason %q", reason)
	}
	if reason != "recent-ingress-p99-all-below-threshold" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestAllowIngressScaleDownBlocksWhenRecentIngressPointTouchesThreshold(t *testing.T) {
	policy := scalingPolicy{
		IngressP99ThresholdSec: 0.50,
		ReactiveRequiredPoints: 3,
	}

	allowed, reason := allowIngressScaleDown(
		map[string][]*float64{
			"ingress_p99_seconds": {
				float64Ptr(0.40),
				float64Ptr(0.50),
				float64Ptr(0.20),
			},
		},
		policy,
	)

	if allowed {
		t.Fatalf("expected ingress scale down to be blocked")
	}
	if reason == "" {
		t.Fatalf("expected a non-empty reason")
	}
}

func TestAllowScaleDownBlocksWhenRecentErrorRateExceedsThreshold(t *testing.T) {
	policy := scalingPolicy{
		ScaleDownPolicy:        "safe",
		AppErrorRateThreshold:  0.05,
		IngressP99ThresholdSec: 0.50,
		ReactiveRequiredPoints: 2,
	}

	allowed, reason := allowScaleDown(
		map[string][]*float64{
			"app_error_rate": {
				float64Ptr(0.01),
				float64Ptr(0.07),
			},
			"ingress_p99_seconds": {
				float64Ptr(0.20),
				float64Ptr(0.30),
			},
		},
		policy,
	)

	if allowed {
		t.Fatalf("expected scale down to be blocked")
	}
	if reason != "app_error_rate_above_threshold: 0.070 > 0.050" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestAllowScaleDownBlocksWhenIngressP99ExceedsThreshold(t *testing.T) {
	policy := scalingPolicy{
		ScaleDownPolicy:        "safe",
		AppErrorRateThreshold:  0.05,
		IngressP99ThresholdSec: 0.50,
		ReactiveRequiredPoints: 2,
	}

	allowed, reason := allowScaleDown(
		map[string][]*float64{
			"app_error_rate": {
				float64Ptr(0.01),
				float64Ptr(0.02),
			},
			"ingress_p99_seconds": {
				float64Ptr(0.20),
				float64Ptr(0.60),
			},
		},
		policy,
	)

	if allowed {
		t.Fatalf("expected scale down to be blocked")
	}
	if reason != "ingress_p99_above_threshold: 0.600 > 0.500" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestAllowScaleDownAllowsWhenOnlyOlderIngressSpikeExceedsThreshold(t *testing.T) {
	policy := scalingPolicy{
		ScaleDownPolicy:        "safe",
		AppErrorRateThreshold:  0.05,
		IngressP99ThresholdSec: 0.50,
		ReactiveRequiredPoints: 3,
	}

	allowed, reason := allowScaleDown(
		map[string][]*float64{
			"app_error_rate": {
				float64Ptr(0.01),
				float64Ptr(0.02),
				float64Ptr(0.03),
				float64Ptr(0.02),
			},
			"ingress_p99_seconds": {
				float64Ptr(2.00),
				float64Ptr(0.20),
				float64Ptr(0.25),
				float64Ptr(0.30),
			},
		},
		policy,
	)

	if !allowed {
		t.Fatalf("expected scale down to be allowed, got false with reason %q", reason)
	}
	if reason != "recent-guardrails-healthy" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestAllowScaleDownBlocksWhenThereAreFewerThanRequiredRecentGuardrailPoints(t *testing.T) {
	policy := scalingPolicy{
		ScaleDownPolicy:        "safe",
		AppErrorRateThreshold:  0.05,
		IngressP99ThresholdSec: 0.50,
		ReactiveRequiredPoints: 3,
	}

	allowed, reason := allowScaleDown(
		map[string][]*float64{
			"app_error_rate": {
				nil,
				float64Ptr(0.01),
				float64Ptr(0.02),
			},
			"ingress_p99_seconds": {
				float64Ptr(0.20),
				nil,
				float64Ptr(0.30),
			},
		},
		policy,
	)

	if allowed {
		t.Fatalf("expected scale down to be blocked")
	}
	if reason != "insufficient-guardrail-history" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func float64Ptr(value float64) *float64 {
	return &value
}
