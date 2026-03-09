import { useCallback, useEffect, useState } from "react";

import { fetchOnboardingStatus } from "../lib/api";
import { ONBOARDING_REFRESH_EVENT } from "../lib/onboardingEvents";
import type { OnboardingStatus } from "../lib/types";

type UseOnboardingStatusResult = {
  data: OnboardingStatus | null;
  isLoading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
};

export function useOnboardingStatus(): UseOnboardingStatusResult {
  const [data, setData] = useState<OnboardingStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await fetchOnboardingStatus();
      setData(result);
    } catch (loadError) {
      setData(null);
      setError(loadError instanceof Error ? loadError.message : "Failed to load onboarding status");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();

    const handleRefresh = () => {
      void load();
    };

    window.addEventListener(ONBOARDING_REFRESH_EVENT, handleRefresh);
    return () => {
      window.removeEventListener(ONBOARDING_REFRESH_EVENT, handleRefresh);
    };
  }, [load]);

  return {
    data,
    isLoading,
    error,
    refetch: load,
  };
}
