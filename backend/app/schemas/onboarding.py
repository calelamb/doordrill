from datetime import datetime

from pydantic import BaseModel


class OnboardingStep(BaseModel):
    id: str
    label: str
    is_complete: bool
    cta_url: str


class OnboardingStatus(BaseModel):
    steps: list[OnboardingStep]
    is_complete: bool
    onboarding_completed_at: datetime | None = None
