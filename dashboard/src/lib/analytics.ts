import type { CategoryScoreValue, FeedItem } from "./types";

export const PASSING_SCORE = 7.0;

export const CATEGORY_META = [
  { key: "opening", label: "Opening" },
  { key: "pitch", label: "Pitch" },
  { key: "objection_handling", label: "Objection Handling" },
  { key: "closing", label: "Closing" },
  { key: "professionalism", label: "Professionalism" },
] as const;

export type AnalyticsCategoryKey = (typeof CATEGORY_META)[number]["key"];

const CATEGORY_ALIASES: Record<string, AnalyticsCategoryKey> = {
  opening: "opening",
  pitch: "pitch",
  pitch_delivery: "pitch",
  objection_handling: "objection_handling",
  closing: "closing",
  closing_technique: "closing",
  professionalism: "professionalism",
};

export function normalizeCategoryKey(value: string | null | undefined): AnalyticsCategoryKey | null {
  if (!value) {
    return null;
  }
  return CATEGORY_ALIASES[value] ?? null;
}

export function getCategoryLabel(key: AnalyticsCategoryKey): string {
  return CATEGORY_META.find((category) => category.key === key)?.label ?? key;
}

function getNumericScore(value: CategoryScoreValue | number | undefined): number | null {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (value && typeof value === "object" && typeof value.score === "number") {
    return Number.isFinite(value.score) ? value.score : null;
  }
  return null;
}

export function getCategoryScore(
  source: Record<string, CategoryScoreValue | number> | undefined,
  key: AnalyticsCategoryKey
): number | null {
  if (!source) {
    return null;
  }

  const direct = getNumericScore(source[key]);
  if (direct !== null) {
    return direct;
  }

  for (const [rawKey, normalizedKey] of Object.entries(CATEGORY_ALIASES)) {
    if (normalizedKey !== key) {
      continue;
    }
    const aliased = getNumericScore(source[rawKey]);
    if (aliased !== null) {
      return aliased;
    }
  }

  return null;
}

export function emptyCategoryRecord(): Record<AnalyticsCategoryKey, number> {
  return CATEGORY_META.reduce<Record<AnalyticsCategoryKey, number>>((accumulator, category) => {
    accumulator[category.key] = 0;
    return accumulator;
  }, {} as Record<AnalyticsCategoryKey, number>);
}

export function averageCategoryScores(
  sessions: Array<Pick<FeedItem, "category_scores">>
): Record<AnalyticsCategoryKey, number> {
  const totals = emptyCategoryRecord();
  const counts = emptyCategoryRecord();

  for (const session of sessions) {
    for (const category of CATEGORY_META) {
      const value = getCategoryScore(session.category_scores, category.key);
      if (value === null) {
        continue;
      }
      totals[category.key] += value;
      counts[category.key] += 1;
    }
  }

  return CATEGORY_META.reduce<Record<AnalyticsCategoryKey, number>>((accumulator, category) => {
    const count = counts[category.key];
    accumulator[category.key] = count > 0 ? Number((totals[category.key] / count).toFixed(2)) : 0;
    return accumulator;
  }, emptyCategoryRecord());
}
