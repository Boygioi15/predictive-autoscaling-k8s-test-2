package controller

import "testing"

func TestHasSustainedIngressPressureReturnsTrueWhenRecentPointsAreAboveThreshold(t *testing.T) {
	policy := scalingPolicy{
		IngressP95ThresholdSec:        0.50,
		IngressPressureRequiredPoints: 3,
	}

	underPressure, reason := hasSustainedIngressPressure(
		map[string][]*float64{
			"ingress_p95_seconds": {
				float64Ptr(0.30),
				float64Ptr(0.60),
				float64Ptr(0.70),
				float64Ptr(0.80),
			},
		},
		policy,
	)

	if !underPressure {
		t.Fatalf("expected sustained ingress pressure to be true")
	}
	if reason != "recent-ingress-p95-all-above-threshold" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestHasSustainedIngressPressureReturnsFalseWhenRecentIngressPointsAreNotAllAboveThreshold(t *testing.T) {
	policy := scalingPolicy{
		IngressP95ThresholdSec:        0.50,
		IngressPressureRequiredPoints: 3,
	}

	underPressure, reason := hasSustainedIngressPressure(
		map[string][]*float64{
			"ingress_p95_seconds": {
				float64Ptr(0.60),
				float64Ptr(0.70),
				float64Ptr(0.40),
			},
		},
		policy,
	)

	if underPressure {
		t.Fatalf("expected sustained ingress pressure to be false")
	}
	if reason != "recent-ingress-p95-not-all-above-threshold" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestHasSustainedIngressPressureReturnsFalseWhenThereAreFewerThanRequiredValidIngressPoints(t *testing.T) {
	policy := scalingPolicy{
		IngressP95ThresholdSec:        0.50,
		IngressPressureRequiredPoints: 3,
	}

	underPressure, reason := hasSustainedIngressPressure(
		map[string][]*float64{
			"ingress_p95_seconds": {
				nil,
				float64Ptr(0.70),
				float64Ptr(0.80),
			},
		},
		policy,
	)

	if underPressure {
		t.Fatalf("expected sustained ingress pressure to be false")
	}
	if reason != "insufficient-ingress-history" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestNextIngressPressureBumpIncreasesWhenPressurePersists(t *testing.T) {
	policy := scalingPolicy{
		IngressP95ThresholdSec:        0.50,
		IngressPressureRequiredPoints: 3,
		IngressPressureIncreaseStep:   1,
		IngressPressureDecreaseStep:   2,
		IngressPressureMaxBump:        10,
	}

	next, reason := nextIngressPressureBump(
		2,
		map[string][]*float64{
			"ingress_p95_seconds": {
				float64Ptr(0.60),
				float64Ptr(0.70),
				float64Ptr(0.80),
			},
		},
		policy,
	)

	if next != 3 {
		t.Fatalf("expected next bump to be 3, got %d", next)
	}
	if reason != "recent-ingress-p95-all-above-threshold" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestNextIngressPressureBumpDecaysWhenPressureClears(t *testing.T) {
	policy := scalingPolicy{
		IngressP95ThresholdSec:        0.50,
		IngressPressureRequiredPoints: 3,
		IngressPressureIncreaseStep:   1,
		IngressPressureDecreaseStep:   2,
		IngressPressureMaxBump:        10,
	}

	next, reason := nextIngressPressureBump(
		3,
		map[string][]*float64{
			"ingress_p95_seconds": {
				float64Ptr(0.40),
				float64Ptr(0.30),
				float64Ptr(0.20),
			},
		},
		policy,
	)

	if next != 1 {
		t.Fatalf("expected next bump to decay to 1, got %d", next)
	}
	if reason != "recent-ingress-p95-not-all-above-threshold" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestNextIngressPressureBumpClampsAtZeroAndMax(t *testing.T) {
	policy := scalingPolicy{
		IngressP95ThresholdSec:        0.50,
		IngressPressureRequiredPoints: 3,
		IngressPressureIncreaseStep:   2,
		IngressPressureDecreaseStep:   2,
		IngressPressureMaxBump:        4,
	}

	high, _ := nextIngressPressureBump(
		3,
		map[string][]*float64{
			"ingress_p95_seconds": {
				float64Ptr(0.60),
				float64Ptr(0.70),
				float64Ptr(0.80),
			},
		},
		policy,
	)
	if high != 4 {
		t.Fatalf("expected next bump to clamp at 4, got %d", high)
	}

	low, _ := nextIngressPressureBump(
		1,
		map[string][]*float64{
			"ingress_p95_seconds": {
				float64Ptr(0.10),
				float64Ptr(0.20),
				float64Ptr(0.30),
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
		IngressP95ThresholdSec:        0.50,
		IngressPressureRequiredPoints: 3,
	}

	allowed, reason := allowIngressScaleDown(
		map[string][]*float64{
			"ingress_p95_seconds": {
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
	if reason != "recent-ingress-p95-all-below-threshold" {
		t.Fatalf("unexpected reason: %s", reason)
	}
}

func TestAllowIngressScaleDownBlocksWhenRecentIngressPointTouchesThreshold(t *testing.T) {
	policy := scalingPolicy{
		IngressP95ThresholdSec:        0.50,
		IngressPressureRequiredPoints: 3,
	}

	allowed, reason := allowIngressScaleDown(
		map[string][]*float64{
			"ingress_p95_seconds": {
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

func float64Ptr(value float64) *float64 {
	return &value
}
