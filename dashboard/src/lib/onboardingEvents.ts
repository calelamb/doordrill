export const ONBOARDING_REFRESH_EVENT = "doordrill:onboarding-refresh";

export function dispatchOnboardingRefresh(): void {
  window.dispatchEvent(new Event(ONBOARDING_REFRESH_EVENT));
}
