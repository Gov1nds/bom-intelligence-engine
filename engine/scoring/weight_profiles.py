"""Weight profiles per PC-004, architecture.md Domain 9."""

WEIGHT_PROFILES: dict[str, dict[str, float]] = {
    "balanced":      {"cost": 0.25, "lead_time": 0.20, "quality": 0.25, "strategic_fit": 0.15, "operational_capability": 0.15},
    "cost_first":    {"cost": 0.40, "lead_time": 0.15, "quality": 0.20, "strategic_fit": 0.10, "operational_capability": 0.15},
    "speed_first":   {"cost": 0.15, "lead_time": 0.40, "quality": 0.15, "strategic_fit": 0.10, "operational_capability": 0.20},
    "quality_first": {"cost": 0.15, "lead_time": 0.15, "quality": 0.40, "strategic_fit": 0.15, "operational_capability": 0.15},
}


def validate_weight_profile(profile_name: str) -> dict[str, float]:
    if profile_name not in WEIGHT_PROFILES:
        raise ValueError(f"Unknown weight profile: {profile_name}")
    weights = WEIGHT_PROFILES[profile_name]
    total = sum(weights.values())
    assert abs(total - 1.0) < 0.001, f"Weights must sum to 1.0, got {total}"
    return weights
