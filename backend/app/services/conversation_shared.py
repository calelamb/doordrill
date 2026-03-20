from __future__ import annotations


OBJECTION_SEMANTIC_ANCHORS: dict[str, tuple[str, ...]] = {
    "price": ("budget", "monthly cost", "value"),
    "trust": ("legit", "proof", "company reputation"),
    "spouse": ("partner", "shared decision", "not deciding alone"),
    "incumbent_provider": ("already covered", "switching", "current provider"),
    "safety_environment": ("kids", "pets", "chemicals"),
    "timing": ("busy", "schedule", "right now"),
}
