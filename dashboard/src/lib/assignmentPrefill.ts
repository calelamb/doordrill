import type { AssignmentSuggestion } from "./types";

export type AssignmentPrefillState = {
  prefillScenarioSearch?: string;
  prefillScenarioId?: string;
  prefillDifficulty?: number;
  prefillRepIds?: string[];
  prefillCategoryKey?: string;
  prefillMinScoreTarget?: number;
  prefillRetryPolicy?: Record<string, unknown>;
} | null;

export function buildAssignmentPrefillState(
  suggestion?: AssignmentSuggestion | null,
  overrides: Omit<NonNullable<AssignmentPrefillState>, never> = {},
): AssignmentPrefillState {
  const nextState: NonNullable<AssignmentPrefillState> = {
    ...overrides,
  };

  if (suggestion) {
    nextState.prefillScenarioSearch = suggestion.scenario_search ?? suggestion.scenario_label;
    nextState.prefillScenarioId = suggestion.scenario_id ?? undefined;
    nextState.prefillDifficulty = suggestion.difficulty ?? undefined;
    nextState.prefillRepIds = suggestion.rep_id ? [suggestion.rep_id] : undefined;
    nextState.prefillMinScoreTarget = suggestion.min_score_target ?? undefined;
    nextState.prefillRetryPolicy = suggestion.retry_policy ?? undefined;
  }

  return nextState;
}
