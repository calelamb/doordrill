import { API_BASE_URL } from "./config";
import {
  CategoryScoreDetail,
  ImprovementTarget,
  RepAssignment,
  RepPlan,
  RepProgress,
  RepSessionDetail,
  RepTrend,
  ScenarioBrief,
  Scorecard,
  TranscriptTurn,
} from "../types";

type HeaderMap = Record<string, string>;

type RawCategoryScore = number | (Partial<CategoryScoreDetail> & { score?: number }) | null;

type RawScorecard = Omit<Scorecard, "category_scores" | "improvement_targets" | "scorecard_schema_version"> & {
  scorecard_schema_version?: string;
  category_scores?: Record<string, RawCategoryScore>;
};

type RawRepSessionDetail = Omit<RepSessionDetail, "scorecard" | "transcript" | "manager_note" | "manager_coaching_note"> & {
  scorecard: RawScorecard | null;
  transcript?: TranscriptTurn[];
  improvement_targets?: ImprovementTarget[];
  manager_coaching_note?: RepSessionDetail["manager_coaching_note"];
};

function repHeaders(repId: string): HeaderMap {
  return {
    "x-user-id": repId,
    "x-user-role": "rep",
    "content-type": "application/json"
  };
}

async function parseJson<T>(response: Response, action: string): Promise<T> {
  if (!response.ok) {
    throw new Error(`${action} failed (${response.status})`);
  }
  return (await response.json()) as T;
}

function normalizeCategoryScore(value: RawCategoryScore): CategoryScoreDetail {
  if (typeof value === "number") {
    return { score: value };
  }

  if (value && typeof value === "object") {
    return {
      score: typeof value.score === "number" ? value.score : 0,
      rationale_summary: value.rationale_summary,
      rationale_detail: value.rationale_detail,
      improvement_target: value.improvement_target ?? null,
      behavioral_signals: Array.isArray(value.behavioral_signals) ? value.behavioral_signals : [],
      evidence_turn_ids: Array.isArray(value.evidence_turn_ids) ? value.evidence_turn_ids : [],
      confidence: typeof value.confidence === "number" ? value.confidence : undefined,
    };
  }

  return { score: 0 };
}

function normalizeScorecard(
  scorecard: RawScorecard | null,
  improvementTargets: ImprovementTarget[]
): Scorecard | null {
  if (!scorecard) {
    return null;
  }

  const normalizedScores = Object.fromEntries(
    Object.entries(scorecard.category_scores ?? {}).map(([key, value]) => [key, normalizeCategoryScore(value)])
  );

  return {
    ...scorecard,
    scorecard_schema_version: scorecard.scorecard_schema_version ?? "v1",
    category_scores: normalizedScores,
    improvement_targets: improvementTargets,
    highlights: scorecard.highlights ?? [],
    ai_summary: scorecard.ai_summary ?? "",
    evidence_turn_ids: Array.isArray(scorecard.evidence_turn_ids) ? scorecard.evidence_turn_ids : [],
    weakness_tags: Array.isArray(scorecard.weakness_tags) ? scorecard.weakness_tags : [],
  };
}

function normalizeRepSessionDetail(payload: RawRepSessionDetail): RepSessionDetail {
  const improvementTargets = Array.isArray(payload.improvement_targets) ? payload.improvement_targets : [];
  const managerCoachingNote = payload.manager_coaching_note ?? null;

  return {
    ...payload,
    scorecard: normalizeScorecard(payload.scorecard, improvementTargets),
    transcript: Array.isArray(payload.transcript) ? payload.transcript : [],
    manager_coaching_note: managerCoachingNote,
    manager_note: managerCoachingNote?.note ?? null,
  };
}

function normalizeRepPlan(plan: RepPlan): RepPlan {
  return {
    focus_skills: Array.isArray(plan.focus_skills) ? plan.focus_skills.filter((skill) => typeof skill === "string" && skill) : [],
    recommended_difficulty: typeof plan.recommended_difficulty === "number" ? plan.recommended_difficulty : 1,
    readiness_trajectory: plan.readiness_trajectory ?? {},
    next_scenario_suggestion: plan.next_scenario_suggestion
      ? {
          name: plan.next_scenario_suggestion.name,
          scenario_id: plan.next_scenario_suggestion.scenario_id ?? null,
          difficulty: plan.next_scenario_suggestion.difficulty,
          reason: plan.next_scenario_suggestion.reason,
        }
      : null,
  };
}

function normalizeRepProgress(progress: RepProgress): RepProgress {
  return {
    ...progress,
    session_count: typeof progress.session_count === "number" ? progress.session_count : 0,
    scored_session_count: typeof progress.scored_session_count === "number" ? progress.scored_session_count : 0,
    completed_drills:
      typeof progress.completed_drills === "number"
        ? progress.completed_drills
        : typeof progress.scored_session_count === "number"
          ? progress.scored_session_count
          : 0,
    average_score: typeof progress.average_score === "number" ? progress.average_score : null,
    streak_days: typeof progress.streak_days === "number" ? progress.streak_days : 0,
    personal_best: typeof progress.personal_best === "number" ? progress.personal_best : null,
    personal_best_session_id: progress.personal_best_session_id ?? null,
    most_improved_category: progress.most_improved_category ?? null,
    most_improved_delta: typeof progress.most_improved_delta === "number" ? progress.most_improved_delta : null,
    last_scored_session_at: progress.last_scored_session_at ?? null,
  };
}

export async function checkApiReachable(timeoutMs = 3500): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE_URL}/health`, {
      method: "GET",
      signal: controller.signal
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchRepAssignments(repId: string): Promise<RepAssignment[]> {
  const response = await fetch(`${API_BASE_URL}/rep/assignments?rep_id=${encodeURIComponent(repId)}`, {
    headers: repHeaders(repId)
  });
  return parseJson<RepAssignment[]>(response, "fetch assignments");
}

export async function createRepSession(
  repId: string,
  assignmentId: string | null,
  scenarioId: string
): Promise<{ id: string }> {
  const response = await fetch(`${API_BASE_URL}/rep/sessions`, {
    method: "POST",
    headers: repHeaders(repId),
    body: JSON.stringify({
      assignment_id: assignmentId,
      rep_id: repId,
      scenario_id: scenarioId
    })
  });
  return parseJson<{ id: string }>(response, "create session");
}

export async function fetchAllScenarios(repId: string): Promise<ScenarioBrief[]> {
  const response = await fetch(`${API_BASE_URL}/scenarios`, {
    headers: repHeaders(repId)
  });
  return parseJson<ScenarioBrief[]>(response, "fetch all scenarios");
}

export async function fetchRepScenario(repId: string, scenarioId: string): Promise<ScenarioBrief> {
  const response = await fetch(`${API_BASE_URL}/scenarios/${encodeURIComponent(scenarioId)}`, {
    headers: repHeaders(repId)
  });
  return parseJson<ScenarioBrief>(response, "fetch scenario");
}

export async function fetchRepSession(repId: string, sessionId: string): Promise<RepSessionDetail> {
  const response = await fetch(`${API_BASE_URL}/rep/sessions/${encodeURIComponent(sessionId)}`, {
    headers: repHeaders(repId)
  });
  const payload = await parseJson<RawRepSessionDetail>(response, "fetch session detail");
  return normalizeRepSessionDetail(payload);
}

export async function fetchRepProgress(repId: string): Promise<RepProgress> {
  const response = await fetch(`${API_BASE_URL}/rep/progress?rep_id=${encodeURIComponent(repId)}`, {
    headers: repHeaders(repId)
  });
  const payload = await parseJson<RepProgress>(response, "fetch progress");
  return normalizeRepProgress(payload);
}

export async function fetchRepSessionsHistory(repId: string): Promise<{ items: import("../types").RepSessionHistoryItem[] }> {
  const response = await fetch(`${API_BASE_URL}/rep/sessions?rep_id=${encodeURIComponent(repId)}`, {
    headers: repHeaders(repId)
  });
  return parseJson<{ items: import("../types").RepSessionHistoryItem[] }>(response, "fetch history");
}

export async function fetchRepTrend(repId: string, sessions = 10): Promise<RepTrend> {
  const response = await fetch(
    `${API_BASE_URL}/rep/progress/trend?rep_id=${encodeURIComponent(repId)}&sessions=${encodeURIComponent(String(sessions))}`,
    {
      headers: repHeaders(repId)
    }
  );
  return parseJson<RepTrend>(response, "fetch trend");
}

export async function fetchRepPlan(repId: string): Promise<RepPlan> {
  const response = await fetch(`${API_BASE_URL}/rep/plan?rep_id=${encodeURIComponent(repId)}`, {
    headers: repHeaders(repId)
  });
  const payload = await parseJson<RepPlan>(response, "fetch plan");
  return normalizeRepPlan(payload);
}

export async function lookupRepByEmail(email: string): Promise<{ rep_id: string }> {
  const response = await fetch(`${API_BASE_URL}/rep/lookup?email=${encodeURIComponent(email)}`);
  return parseJson<{ rep_id: string }>(response, "lookup rep");
}

export async function uploadRepAvatar(repId: string, uri: string): Promise<{ avatar_url: string }> {
  const ext = uri.split('.').pop() || 'jpg';
  const formData = new FormData();
  // @ts-ignore
  formData.append('file', {
    uri,
    name: `avatar.${ext}`,
    type: `image/${ext}`
  });

  const response = await fetch(`${API_BASE_URL}/rep/profile/avatar`, {
    method: "POST",
    headers: {
      "x-user-id": repId,
      "x-user-role": "rep",
      // Do not set Content-Type, fetch will set it with boundary
    },
    body: formData
  });
  return parseJson<{ avatar_url: string }>(response, "upload avatar");
}

export async function updateRepProfile(repId: string, name: string): Promise<{ name: string; avatar_url: string | null }> {
  const response = await fetch(`${API_BASE_URL}/rep/profile`, {
    method: "PATCH",
    headers: repHeaders(repId),
    body: JSON.stringify({ name })
  });
  return parseJson<{ name: string; avatar_url: string | null }>(response, "update profile");
}

export async function fetchRepHierarchy(repId: string): Promise<import("../types").HierarchyNode[]> {
  const response = await fetch(`${API_BASE_URL}/rep/hierarchy`, {
    headers: repHeaders(repId)
  });
  return parseJson<import("../types").HierarchyNode[]>(response, "fetch hierarchy");
}
