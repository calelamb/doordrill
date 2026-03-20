import { API_BASE_URL } from "./config";
import { useSession } from "../store/session";
import {
  AuthTokenResponse,
  CategoryScoreDetail,
  DEFAULT_NOTIFICATION_PREFERENCES,
  ImprovementTarget,
  InviteValidationResponse,
  NotificationPreferences,
  RegisteredDeviceToken,
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
type DeviceTokenRegistrationPayload = {
  token: string;
  platform: "ios" | "android";
  provider: "expo" | "fcm";
};

type ApiRequestOptions = {
  auth?: boolean;
  body?: BodyInit;
  headers?: HeaderMap;
  allowNotFound?: boolean;
  retryOn401?: boolean;
};

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

let refreshInFlight: Promise<boolean> | null = null;
const API_TIMEOUT_MS = 10_000;

async function buildHeaders(headers: HeaderMap | undefined, auth: boolean): Promise<HeaderMap> {
  const mergedHeaders = {
    // Bypass the localtunnel browser-warning page for dev tunnels.
    "bypass-tunnel-reminder": "true",
    ...(headers ?? {})
  };
  if (!auth) {
    return mergedHeaders;
  }

  const token = await useSession.getState().getAccessToken();
  if (token) {
    mergedHeaders.Authorization = `Bearer ${token}`;
  }
  return mergedHeaders;
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }

    if (Array.isArray(payload.detail)) {
      const messages = payload.detail
        .map((entry) => {
          if (!entry || typeof entry !== "object") {
            return null;
          }

          const message = "msg" in entry ? entry.msg : null;
          return typeof message === "string" && message.trim() ? message : null;
        })
        .filter((message): message is string => Boolean(message));

      if (messages.length > 0) {
        return messages.join(", ");
      }
    }
  } catch {
    // Ignore malformed or empty JSON error payloads.
  }

  return `HTTP ${response.status}`;
}

async function apiRequest<T>(
  method: string,
  path: string,
  options: ApiRequestOptions = {},
  hasRetried = false
): Promise<T> {
  const auth = options.auth !== false;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers: await buildHeaders(options.headers, auth),
      body: options.body,
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error("Request timed out");
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
  }

  if (response.status === 401 && auth && options.retryOn401 !== false && !hasRetried) {
    const refreshed = await attemptSilentRefresh();
    if (refreshed) {
      return apiRequest<T>(method, path, options, true);
    }

    await useSession.getState().clearSession();
    throw new Error("Session expired");
  }

  if (response.status === 404 && options.allowNotFound) {
    return undefined as T;
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

async function apiJsonRequest<T>(
  method: string,
  path: string,
  body?: unknown,
  options: Omit<ApiRequestOptions, "body"> = {}
): Promise<T> {
  const headers = { "Content-Type": "application/json", ...(options.headers ?? {}) };
  return apiRequest<T>(
    method,
    path,
    {
      ...options,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    }
  );
}

async function attemptSilentRefresh(): Promise<boolean> {
  if (refreshInFlight) {
    return refreshInFlight;
  }

  refreshInFlight = (async () => {
    const store = useSession.getState();
    const refreshToken = await store.getRefreshToken();
    if (!refreshToken) {
      return false;
    }

    try {
      const result = await refreshTokens(refreshToken);
      await store.setSession(result.user, {
        access: result.access_token,
        refresh: result.refresh_token,
      });
      return true;
    } catch {
      return false;
    }
  })();

  try {
    return await refreshInFlight;
  } finally {
    refreshInFlight = null;
  }
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

function normalizeNotificationPreferences(
  preferences: Partial<NotificationPreferences> | null | undefined
): NotificationPreferences {
  return {
    score_ready:
      typeof preferences?.score_ready === "boolean"
        ? preferences.score_ready
        : DEFAULT_NOTIFICATION_PREFERENCES.score_ready,
    assignment_created:
      typeof preferences?.assignment_created === "boolean"
        ? preferences.assignment_created
        : DEFAULT_NOTIFICATION_PREFERENCES.assignment_created,
    assignment_due_soon:
      typeof preferences?.assignment_due_soon === "boolean"
        ? preferences.assignment_due_soon
        : DEFAULT_NOTIFICATION_PREFERENCES.assignment_due_soon,
    coaching_note:
      typeof preferences?.coaching_note === "boolean"
        ? preferences.coaching_note
        : DEFAULT_NOTIFICATION_PREFERENCES.coaching_note,
    streak_nudge:
      typeof preferences?.streak_nudge === "boolean"
        ? preferences.streak_nudge
        : DEFAULT_NOTIFICATION_PREFERENCES.streak_nudge,
  };
}

export async function loginWithCredentials(email: string, password: string): Promise<AuthTokenResponse> {
  return apiJsonRequest<AuthTokenResponse>(
    "POST",
    "/auth/login",
    { email, password },
    { auth: false, retryOn401: false }
  );
}

export async function refreshTokens(refreshToken: string): Promise<AuthTokenResponse> {
  return apiJsonRequest<AuthTokenResponse>(
    "POST",
    "/auth/refresh",
    { refresh_token: refreshToken },
    { auth: false, retryOn401: false }
  );
}

export async function requestPasswordReset(email: string): Promise<void> {
  return apiJsonRequest<void>(
    "POST",
    "/auth/request-password-reset",
    { email },
    { auth: false, retryOn401: false }
  );
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  return apiJsonRequest<void>(
    "POST",
    "/auth/reset-password",
    { token, new_password: newPassword },
    { auth: false, retryOn401: false }
  );
}

export async function validateInvite(token: string): Promise<InviteValidationResponse> {
  return apiRequest<InviteValidationResponse>(
    "GET",
    `/auth/validate-invite?token=${encodeURIComponent(token)}`,
    { auth: false, retryOn401: false }
  );
}

export async function acceptInvite(payload: {
  token: string;
  name: string;
  password: string;
}): Promise<AuthTokenResponse> {
  return apiJsonRequest<AuthTokenResponse>("POST", "/auth/accept-invite", payload, {
    auth: false,
    retryOn401: false,
  });
}

export async function checkApiReachable(timeoutMs = 3500): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE_URL}/health`, {
      method: "GET",
      signal: controller.signal,
    });
    return response.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchRepAssignments(repId: string): Promise<RepAssignment[]> {
  return apiRequest<RepAssignment[]>("GET", `/rep/assignments?rep_id=${encodeURIComponent(repId)}`);
}

export async function createRepSession(
  repId: string,
  assignmentId: string | null,
  scenarioId: string
): Promise<{ id: string }> {
  return apiJsonRequest<{ id: string }>("POST", "/rep/sessions", {
    assignment_id: assignmentId,
    rep_id: repId,
    scenario_id: scenarioId,
  });
}

export async function fetchAllScenarios(_repId: string): Promise<ScenarioBrief[]> {
  return apiRequest<ScenarioBrief[]>("GET", "/rep/scenarios");
}

export async function fetchRepScenario(_repId: string, scenarioId: string): Promise<ScenarioBrief> {
  return apiRequest<ScenarioBrief>("GET", `/scenarios/${encodeURIComponent(scenarioId)}`);
}

export async function fetchRepSession(_repId: string, sessionId: string): Promise<RepSessionDetail> {
  const payload = await apiRequest<RawRepSessionDetail>("GET", `/rep/sessions/${encodeURIComponent(sessionId)}`);
  return normalizeRepSessionDetail(payload);
}

export async function fetchRepProgress(repId: string): Promise<RepProgress> {
  const payload = await apiRequest<RepProgress>("GET", `/rep/progress?rep_id=${encodeURIComponent(repId)}`);
  return normalizeRepProgress(payload);
}

export async function fetchRepSessionsHistory(
  repId: string
): Promise<{ items: import("../types").RepSessionHistoryItem[] }> {
  return apiRequest<{ items: import("../types").RepSessionHistoryItem[] }>(
    "GET",
    `/rep/sessions?rep_id=${encodeURIComponent(repId)}`
  );
}

export async function fetchRepTrend(repId: string, sessions = 10): Promise<RepTrend> {
  return apiRequest<RepTrend>(
    "GET",
    `/rep/progress/trend?rep_id=${encodeURIComponent(repId)}&sessions=${encodeURIComponent(String(sessions))}`
  );
}

export async function fetchRepPlan(repId: string): Promise<RepPlan> {
  const payload = await apiRequest<RepPlan>("GET", `/rep/plan?rep_id=${encodeURIComponent(repId)}`);
  return normalizeRepPlan(payload);
}

export async function registerDeviceToken(
  payload: DeviceTokenRegistrationPayload
): Promise<RegisteredDeviceToken> {
  return apiJsonRequest<RegisteredDeviceToken>("POST", "/rep/device-tokens", payload);
}

export async function revokeDeviceToken(tokenId: string): Promise<void> {
  await apiRequest<Record<string, unknown> | undefined>(
    "DELETE",
    `/rep/device-tokens/${encodeURIComponent(tokenId)}`,
    { allowNotFound: true }
  );
}

export async function fetchNotificationPreferences(): Promise<NotificationPreferences> {
  const payload = await apiRequest<Partial<NotificationPreferences>>("GET", "/rep/notification-preferences");
  return normalizeNotificationPreferences(payload);
}

export async function updateNotificationPreferences(
  preferences: NotificationPreferences
): Promise<NotificationPreferences> {
  const payload = await apiJsonRequest<Partial<NotificationPreferences>>(
    "PUT",
    "/rep/notification-preferences",
    preferences
  );
  return normalizeNotificationPreferences(payload);
}

export async function uploadRepAvatar(uri: string): Promise<{ avatar_url: string }> {
  const ext = uri.split(".").pop() || "jpg";
  const formData = new FormData();
  formData.append("file", {
    uri,
    name: `avatar.${ext}`,
    type: `image/${ext}`,
  } as unknown as Blob);

  return apiRequest<{ avatar_url: string }>("POST", "/rep/profile/avatar", {
    body: formData,
  });
}

export async function updateRepProfile(name: string): Promise<{ name: string; avatar_url: string | null }> {
  return apiJsonRequest<{ name: string; avatar_url: string | null }>("PATCH", "/rep/profile", { name });
}

export async function fetchRepHierarchy(): Promise<import("../types").HierarchyNode[]> {
  return apiRequest<import("../types").HierarchyNode[]>("GET", "/rep/hierarchy");
}
