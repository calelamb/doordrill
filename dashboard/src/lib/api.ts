import { clearStoredAuth, createAuthRequiredError, getValidStoredAuth, storeAuth } from "./auth";
import type { AuthSession } from "./auth";
import { ApiError, extractApiErrorCode, formatApiErrorDetail } from "./apiError";
import type {
  AlertItem,
  AnalyticsMetricDefinition,
  BenchmarksResponse,
  ManagerChatResponse,
  CoachingAnalyticsResponse,
  CommandCenterResponse,
  ExplorerResponse,
  FeedItem,
  LiveSessionsResponse,
  LiveTranscriptResponse,
  ManagerAnalyticsOperations,
  ManagerActionLog,
  ManagerAnalytics,
  ManagerAssignment,
  ManagerInvitation,
  ManagerTeamMember,
  OneOnOnePrepResponse,
  OnboardingStatus,
  OrganizationProfile,
  ReplayResponse,
  RepInsightResponse,
  RepAssignment,
  RepProgress,
  RepRiskDetailResponse,
  RepSessionDetail,
  ScenarioSummary,
  ScenarioIntelligenceResponse,
  SessionAnnotationsResponse,
  SessionDetail,
  TeamCoachingSummaryResponse,
  WeeklyTeamBriefingResponse,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? "/api" : "http://127.0.0.1:8000");
const WS_BASE = import.meta.env.VITE_WS_BASE_URL ??
  (import.meta.env.DEV
    ? `${window.location.origin.replace(/^http/i, "ws")}/api`
    : API_BASE.replace(/^http/i, "ws"));

type AuthOptions = {
  userId?: string;
  role?: "manager" | "admin" | "rep";
  public?: boolean;
};

type ManagerTeamResponse = {
  items: ManagerTeamMember[];
};

type ManagerSessionsResponse = {
  items: SessionDetail[];
};

type ManagerAssignmentsResponse = {
  items: ManagerAssignment[];
};

type ManagerSessionDetailResponse = {
  session: SessionDetail;
  assignment: ReplayResponse["assignment"];
  scorecard: ReplayResponse["scorecard"];
};

type AuthLoginResponse = AuthSession;

function buildHeaders({ userId, role, public: isPublic }: AuthOptions = {}): Headers {
  const headers = new Headers({ "content-type": "application/json" });
  if (isPublic) {
    return headers;
  }

  const auth = getValidStoredAuth();
  if (!auth) {
    throw createAuthRequiredError();
  }

  headers.set("authorization", `Bearer ${auth.access_token}`);
  headers.set("x-user-id", userId ?? auth.user.id);
  headers.set("x-user-role", role ?? (auth.user.role as "manager" | "admin" | "rep"));
  return headers;
}

async function requestJson<T>(path: string, init: RequestInit = {}, authOptions: AuthOptions = {}): Promise<T> {
  const headers = buildHeaders(authOptions);
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers
  });

  if (response.status === 401) {
    clearStoredAuth();
    throw createAuthRequiredError();
  }

  if (!response.ok) {
    let detail: unknown = null;
    try {
      const body = await response.json();
      detail = body?.detail;
    } catch {
      detail = null;
    }
    throw new ApiError(
      formatApiErrorDetail(detail, response.status, path),
      response.status,
      extractApiErrorCode(detail),
      detail,
    );
  }

  return response.json() as Promise<T>;
}

function calculateDurationSeconds(startedAt?: string | null, endedAt?: string | null, fallback?: number | null): number | null {
  if (typeof fallback === "number" && Number.isFinite(fallback) && fallback > 0) {
    return Math.round(fallback);
  }
  if (!startedAt || !endedAt) {
    return null;
  }
  const started = new Date(startedAt).getTime();
  const ended = new Date(endedAt).getTime();
  if (!Number.isFinite(started) || !Number.isFinite(ended) || ended <= started) {
    return null;
  }
  return Math.round((ended - started) / 1000);
}

export async function loginManager(email: string, password: string) {
  const response = await requestJson<NonNullable<AuthLoginResponse>>(
    "/auth/login",
    {
      method: "POST",
      body: JSON.stringify({ email, password })
    },
    { public: true }
  );

  if (!["manager", "admin"].includes(response.user.role)) {
    throw new Error("manager credentials required");
  }

  storeAuth(response);
  return response;
}

export async function fetchManagerTeam(managerId: string): Promise<ManagerTeamMember[]> {
  const response = await requestJson<ManagerTeamResponse>(
    `/manager/team?manager_id=${encodeURIComponent(managerId)}`,
    {},
    { userId: managerId, role: "manager" }
  );
  return response.items ?? [];
}

export async function fetchManagerOrganization(): Promise<OrganizationProfile> {
  const auth = getValidStoredAuth();
  if (!auth) {
    throw createAuthRequiredError();
  }

  return requestJson<OrganizationProfile>(
    "/manager/organization",
    {},
    { userId: auth.user.id, role: "manager" }
  );
}

export async function updateManagerOrganization(payload: {
  name: string;
  industry: string;
}): Promise<OrganizationProfile> {
  const auth = getValidStoredAuth();
  if (!auth) {
    throw createAuthRequiredError();
  }

  return requestJson<OrganizationProfile>(
    "/manager/organization",
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
    { userId: auth.user.id, role: "manager" }
  );
}

export async function fetchOnboardingStatus(): Promise<OnboardingStatus> {
  const auth = getValidStoredAuth();
  if (!auth) {
    throw createAuthRequiredError();
  }

  return requestJson<OnboardingStatus>(
    "/manager/onboarding-status",
    {},
    { userId: auth.user.id, role: "manager" }
  );
}

export async function fetchManagerSessions(managerId: string): Promise<SessionDetail[]> {
  const response = await requestJson<ManagerSessionsResponse>(
    `/manager/sessions?manager_id=${encodeURIComponent(managerId)}`,
    {},
    { userId: managerId, role: "manager" }
  );
  return response.items ?? [];
}

export async function fetchManagerAssignments(managerId: string): Promise<ManagerAssignment[]> {
  const response = await requestJson<ManagerAssignmentsResponse>(
    `/manager/assignments?manager_id=${encodeURIComponent(managerId)}`,
    {},
    { userId: managerId, role: "manager" }
  );
  return response.items ?? [];
}

export async function createManagerAssignment(
  managerId: string,
  payload: {
    scenario_id: string;
    rep_id: string;
    due_at?: string;
    min_score_target?: number;
    retry_policy?: Record<string, unknown>;
  }
): Promise<ManagerAssignment> {
  return requestJson<ManagerAssignment>(
    "/manager/assignments",
    {
      method: "POST",
      body: JSON.stringify({
        ...payload,
        assigned_by: managerId,
      }),
    },
    { userId: managerId, role: "manager" }
  );
}

export async function fetchScenarios(): Promise<ScenarioSummary[]> {
  const auth = getValidStoredAuth();
  if (!auth) {
    throw createAuthRequiredError();
  }
  return requestJson<ScenarioSummary[]>("/scenarios", {}, { userId: auth.user.id, role: auth.user.role as "manager" | "admin" | "rep" });
}

export async function createScenario(payload: {
  name: string;
  industry: string;
  difficulty: number;
  description: string;
  persona: Record<string, unknown>;
  rubric: Record<string, unknown>;
  stages: string[];
  created_by_id: string;
}): Promise<ScenarioSummary> {
  const auth = getValidStoredAuth();
  if (!auth) {
    throw createAuthRequiredError();
  }

  return requestJson<ScenarioSummary>(
    "/scenarios",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    { userId: auth.user.id, role: "manager" }
  );
}

export async function createManagerInvitation(payload: {
  email: string;
  team_id?: string | null;
  role?: "rep";
}): Promise<ManagerInvitation> {
  const auth = getValidStoredAuth();
  if (!auth) {
    throw createAuthRequiredError();
  }

  return requestJson<ManagerInvitation>(
    "/manager/invitations",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    { userId: auth.user.id, role: "manager" }
  );
}

export async function fetchManagerFeed(
  managerId: string,
  options: {
    repId?: string;
    scenarioId?: string;
    reviewed?: boolean;
    dateFrom?: string;
    dateTo?: string;
    limit?: number;
  } = {}
): Promise<FeedItem[]> {
  const params = new URLSearchParams({
    manager_id: managerId,
    limit: String(options.limit ?? 100),
  });
  if (options.repId) params.set("rep_id", options.repId);
  if (options.scenarioId) params.set("scenario_id", options.scenarioId);
  if (typeof options.reviewed === "boolean") params.set("reviewed", String(options.reviewed));
  if (options.dateFrom) params.set("date_from", new Date(`${options.dateFrom}T00:00:00`).toISOString());
  if (options.dateTo) params.set("date_to", new Date(`${options.dateTo}T23:59:59`).toISOString());

  const [feedBody, sessions, team, scenarios] = await Promise.all([
    requestJson<{ items: FeedItem[] }>(
      `/manager/feed?${params.toString()}`,
      {},
      { userId: managerId, role: "manager" }
    ),
    fetchManagerSessions(managerId),
    fetchManagerTeam(managerId),
    fetchScenarios()
  ]);

  const sessionsById = new Map(sessions.map((session) => [session.id, session]));
  const repsById = new Map(team.map((member) => [member.id, member]));
  const scenariosById = new Map(scenarios.map((scenario) => [scenario.id, scenario]));

  return (feedBody.items ?? []).map((item) => {
    const session = sessionsById.get(item.session_id);
    const rep = repsById.get(item.rep_id);
    const scenario = session?.scenario_id ? scenariosById.get(session.scenario_id) : null;
    return {
      ...item,
      rep_name: rep?.name ?? item.rep_id,
      scenario_id: session?.scenario_id ?? item.scenario_id ?? null,
      scenario_name: scenario?.name ?? session?.scenario_id ?? item.scenario_name ?? "Unknown scenario",
      scenario_difficulty: scenario?.difficulty ?? item.scenario_difficulty ?? null,
      scenario_description: scenario?.description ?? item.scenario_description ?? null,
      started_at: session?.started_at ?? item.started_at ?? null,
      ended_at: session?.ended_at ?? item.ended_at ?? null,
      duration_seconds: calculateDurationSeconds(session?.started_at, session?.ended_at, session?.duration_seconds) ?? item.duration_seconds ?? null,
    };
  });
}

export async function fetchManagerSessionDetail(managerId: string, sessionId: string): Promise<ManagerSessionDetailResponse> {
  return requestJson<ManagerSessionDetailResponse>(
    `/manager/sessions/${encodeURIComponent(sessionId)}`,
    {},
    { userId: managerId, role: "manager" }
  );
}

export async function fetchReplay(managerId: string, sessionId: string): Promise<ReplayResponse> {
  const [replay, detail] = await Promise.all([
    requestJson<ReplayResponse>(
      `/manager/sessions/${encodeURIComponent(sessionId)}/replay`,
      {},
      { userId: managerId, role: "manager" }
    ),
    fetchManagerSessionDetail(managerId, sessionId)
  ]);

  return {
    ...replay,
    session: detail.session,
    assignment: detail.assignment
  };
}

export async function fetchLiveSessions(managerId: string): Promise<LiveSessionsResponse> {
  return requestJson<LiveSessionsResponse>(
    `/manager/sessions/live?manager_id=${encodeURIComponent(managerId)}`,
    {},
    { userId: managerId, role: "manager" }
  );
}

export async function fetchLiveTranscript(managerId: string, sessionId: string): Promise<LiveTranscriptResponse> {
  return requestJson<LiveTranscriptResponse>(
    `/manager/sessions/${encodeURIComponent(sessionId)}/live-transcript?manager_id=${encodeURIComponent(managerId)}`,
    {},
    { userId: managerId, role: "manager" }
  );
}

export async function fetchRepInsight(
  managerId: string,
  repId: string,
  periodDays = 30
): Promise<RepInsightResponse> {
  return requestJson<RepInsightResponse>(
    "/manager/ai/rep-insight",
    {
      method: "POST",
      body: JSON.stringify({ manager_id: managerId, rep_id: repId, period_days: periodDays }),
    },
    { userId: managerId, role: "manager" }
  );
}

export async function fetchOneOnOnePrep(
  managerId: string,
  repId: string,
  periodDays = 14
): Promise<OneOnOnePrepResponse> {
  return requestJson<OneOnOnePrepResponse>(
    `/manager/reps/${encodeURIComponent(repId)}/one-on-one-prep`,
    {
      method: "POST",
      body: JSON.stringify({ manager_id: managerId, period_days: periodDays }),
    },
    { userId: managerId, role: "manager" }
  );
}

export async function fetchSessionAnnotations(
  managerId: string,
  sessionId: string
): Promise<SessionAnnotationsResponse> {
  return requestJson<SessionAnnotationsResponse>(
    "/manager/ai/session-annotations",
    {
      method: "POST",
      body: JSON.stringify({ manager_id: managerId, session_id: sessionId }),
    },
    { userId: managerId, role: "manager" }
  );
}

export async function fetchTeamCoachingSummary(
  managerId: string,
  periodDays = 30
): Promise<TeamCoachingSummaryResponse> {
  return requestJson<TeamCoachingSummaryResponse>(
    "/manager/ai/team-coaching-summary",
    {
      method: "POST",
      body: JSON.stringify({ manager_id: managerId, period_days: periodDays }),
    },
    { userId: managerId, role: "manager" }
  );
}

export async function fetchWeeklyTeamBriefing(managerId: string): Promise<WeeklyTeamBriefingResponse> {
  return requestJson<WeeklyTeamBriefingResponse>(
    "/manager/team/weekly-briefing",
    {
      method: "POST",
      body: JSON.stringify({ manager_id: managerId }),
    },
    { userId: managerId, role: "manager" }
  );
}

export async function sendManagerChatMessage(
  managerId: string,
  message: string,
  history: Array<{ role: "user" | "assistant"; content: string }>,
  periodDays = 30
): Promise<ManagerChatResponse> {
  return requestJson<ManagerChatResponse>(
    "/manager/ai/chat",
    {
      method: "POST",
      body: JSON.stringify({
        manager_id: managerId,
        message,
        conversation_history: history,
        period_days: periodDays,
      }),
    },
    { userId: managerId, role: "manager" }
  );
}

export async function submitOverride(
  managerId: string,
  scorecardId: string,
  payload: { reason_code: string; override_score?: number; notes?: string }
): Promise<void> {
  await requestJson(
    `/manager/scorecards/${encodeURIComponent(scorecardId)}`,
    {
      method: "PATCH",
      body: JSON.stringify({ reviewer_id: managerId, ...payload })
    },
    { userId: managerId, role: "manager" }
  );
}

export async function createFollowup(
  managerId: string,
  scorecardId: string,
  scenarioId: string
): Promise<void> {
  await requestJson(
    `/manager/scorecards/${encodeURIComponent(scorecardId)}/followup-assignment`,
    {
      method: "POST",
      body: JSON.stringify({
        scenario_id: scenarioId,
        assigned_by: managerId,
        retry_policy: { max_attempts: 2 }
      })
    },
    { userId: managerId, role: "manager" }
  );
}

export async function createCoachingNote(
  managerId: string,
  scorecardId: string,
  payload: { note: string; visible_to_rep?: boolean; weakness_tags?: string[] }
): Promise<void> {
  await requestJson(
    `/manager/scorecards/${encodeURIComponent(scorecardId)}/coaching-notes`,
    {
      method: "POST",
      body: JSON.stringify(payload)
    },
    { userId: managerId, role: "manager" }
  );
}

export async function fetchManagerAnalytics(
  managerId: string,
  options: { period?: string; dateFrom?: string; dateTo?: string } = {}
): Promise<ManagerAnalytics> {
  const params = new URLSearchParams({ manager_id: managerId, period: options.period ?? "30" });
  if (options.dateFrom) params.set("date_from", new Date(`${options.dateFrom}T00:00:00`).toISOString());
  if (options.dateTo) params.set("date_to", new Date(`${options.dateTo}T23:59:59`).toISOString());
  return requestJson<ManagerAnalytics>(
    `/manager/analytics/team?${params.toString()}`,
    {},
    { userId: managerId, role: "manager" }
  );
}

export async function fetchRepRiskDetail(
  managerId: string,
  options: { period?: string } = {}
): Promise<RepRiskDetailResponse> {
  const params = new URLSearchParams({ manager_id: managerId, period: options.period ?? "30" });
  return requestJson<RepRiskDetailResponse>(
    `/manager/analytics/rep-risk-detail?${params.toString()}`,
    {},
    { userId: managerId, role: "manager" }
  );
}

export async function fetchManagerCommandCenter(
  managerId: string,
  options: { period?: string; dateFrom?: string; dateTo?: string } = {}
): Promise<CommandCenterResponse> {
  const params = new URLSearchParams({ manager_id: managerId, period: options.period ?? "30" });
  if (options.dateFrom) params.set("date_from", new Date(`${options.dateFrom}T00:00:00`).toISOString());
  if (options.dateTo) params.set("date_to", new Date(`${options.dateTo}T23:59:59`).toISOString());
  return requestJson<CommandCenterResponse>(
    `/manager/command-center?${params.toString()}`,
    {},
    { userId: managerId, role: "manager" }
  );
}

export async function fetchManagerScenarioIntelligence(
  managerId: string,
  options: { period?: string; dateFrom?: string; dateTo?: string } = {}
): Promise<ScenarioIntelligenceResponse> {
  const params = new URLSearchParams({ manager_id: managerId, period: options.period ?? "30" });
  if (options.dateFrom) params.set("date_from", new Date(`${options.dateFrom}T00:00:00`).toISOString());
  if (options.dateTo) params.set("date_to", new Date(`${options.dateTo}T23:59:59`).toISOString());
  return requestJson<ScenarioIntelligenceResponse>(
    `/manager/analytics/scenarios?${params.toString()}`,
    {},
    { userId: managerId, role: "manager" }
  );
}

export async function fetchManagerCoachingAnalytics(
  managerId: string,
  options: { period?: string; dateFrom?: string; dateTo?: string } = {}
): Promise<CoachingAnalyticsResponse> {
  const params = new URLSearchParams({ manager_id: managerId, period: options.period ?? "30" });
  if (options.dateFrom) params.set("date_from", new Date(`${options.dateFrom}T00:00:00`).toISOString());
  if (options.dateTo) params.set("date_to", new Date(`${options.dateTo}T23:59:59`).toISOString());
  return requestJson<CoachingAnalyticsResponse>(
    `/manager/analytics/coaching?${params.toString()}`,
    {},
    { userId: managerId, role: "manager" }
  );
}

export async function fetchManagerExplorer(
  managerId: string,
  options: {
    period?: string;
    dateFrom?: string;
    dateTo?: string;
    repId?: string;
    scenarioId?: string;
    reviewed?: "true" | "false" | "all";
    weaknessTag?: string;
    scoreMin?: number;
    scoreMax?: number;
    bargeInOnly?: boolean;
    search?: string;
    limit?: number;
  } = {}
): Promise<ExplorerResponse> {
  const params = new URLSearchParams({ manager_id: managerId, period: options.period ?? "30" });
  if (options.dateFrom) params.set("date_from", new Date(`${options.dateFrom}T00:00:00`).toISOString());
  if (options.dateTo) params.set("date_to", new Date(`${options.dateTo}T23:59:59`).toISOString());
  if (options.repId) params.set("rep_id", options.repId);
  if (options.scenarioId) params.set("scenario_id", options.scenarioId);
  if (options.reviewed && options.reviewed !== "all") params.set("reviewed", String(options.reviewed === "true"));
  if (options.weaknessTag) params.set("weakness_tag", options.weaknessTag);
  if (typeof options.scoreMin === "number") params.set("score_min", String(options.scoreMin));
  if (typeof options.scoreMax === "number") params.set("score_max", String(options.scoreMax));
  if (options.bargeInOnly) params.set("barge_in_only", "true");
  if (options.search) params.set("search", options.search);
  if (options.limit) params.set("limit", String(options.limit));
  return requestJson<ExplorerResponse>(
    `/manager/analytics/explorer?${params.toString()}`,
    {},
    { userId: managerId, role: "manager" }
  );
}

export async function fetchManagerAlerts(
  managerId: string,
  options: { period?: string; dateFrom?: string; dateTo?: string } = {}
): Promise<AlertItem[]> {
  const params = new URLSearchParams({ manager_id: managerId, period: options.period ?? "30" });
  if (options.dateFrom) params.set("date_from", new Date(`${options.dateFrom}T00:00:00`).toISOString());
  if (options.dateTo) params.set("date_to", new Date(`${options.dateTo}T23:59:59`).toISOString());
  const response = await requestJson<{ items: AlertItem[] }>(
    `/manager/alerts?${params.toString()}`,
    {},
    { userId: managerId, role: "manager" }
  );
  return response.items ?? [];
}

export async function acknowledgeManagerAlert(managerId: string, alertId: string): Promise<void> {
  await requestJson(
    `/manager/alerts/${encodeURIComponent(alertId)}/ack?manager_id=${encodeURIComponent(managerId)}`,
    { method: "POST" },
    { userId: managerId, role: "manager" }
  );
}

export async function fetchManagerBenchmarks(
  managerId: string,
  options: { period?: string; dateFrom?: string; dateTo?: string } = {}
): Promise<BenchmarksResponse> {
  const params = new URLSearchParams({ manager_id: managerId, period: options.period ?? "30" });
  if (options.dateFrom) params.set("date_from", new Date(`${options.dateFrom}T00:00:00`).toISOString());
  if (options.dateTo) params.set("date_to", new Date(`${options.dateTo}T23:59:59`).toISOString());
  return requestJson<BenchmarksResponse>(
    `/manager/benchmarks?${params.toString()}`,
    {},
    { userId: managerId, role: "manager" }
  );
}

export async function fetchManagerAnalyticsOperations(managerId: string): Promise<ManagerAnalyticsOperations> {
  return requestJson<ManagerAnalyticsOperations>(
    `/manager/analytics/operations?manager_id=${encodeURIComponent(managerId)}`,
    {},
    { userId: managerId, role: "manager" }
  );
}

export async function fetchAnalyticsMetricDefinitions(managerId: string): Promise<AnalyticsMetricDefinition[]> {
  const response = await requestJson<{ items: AnalyticsMetricDefinition[] }>(
    `/manager/analytics/metrics/definitions?manager_id=${encodeURIComponent(managerId)}`,
    {},
    { userId: managerId, role: "manager" }
  );
  return response.items ?? [];
}

export async function fetchRepProgress(
  managerId: string,
  repId: string,
  options: {
    days?: number;
    limit?: number;
    dateFrom?: string;
    dateTo?: string;
  } = {}
): Promise<RepProgress> {
  const params = new URLSearchParams({
    manager_id: managerId,
    days: String(options.days ?? 30),
    limit: String(options.limit ?? 30),
  });
  if (options.dateFrom) params.set("date_from", new Date(`${options.dateFrom}T00:00:00`).toISOString());
  if (options.dateTo) params.set("date_to", new Date(`${options.dateTo}T23:59:59`).toISOString());

  return requestJson<RepProgress>(
    `/manager/analytics/reps/${encodeURIComponent(repId)}?${params.toString()}`,
    {},
    { userId: managerId, role: "manager" }
  );
}

export async function fetchManagerActions(managerId: string, limit = 25): Promise<ManagerActionLog[]> {
  const response = await requestJson<{ items: ManagerActionLog[] }>(
    `/manager/actions?manager_id=${encodeURIComponent(managerId)}&limit=${encodeURIComponent(limit)}`,
    {},
    { userId: managerId, role: "manager" }
  );
  return response.items ?? [];
}

export async function fetchRepAssignments(repId: string): Promise<RepAssignment[]> {
  return requestJson<RepAssignment[]>(
    `/rep/assignments?rep_id=${encodeURIComponent(repId)}`,
    {},
    { userId: repId, role: "rep" }
  );
}

export async function createRepSession(
  repId: string,
  assignmentId: string,
  scenarioId: string
): Promise<{ id: string }> {
  return requestJson<{ id: string }>(
    "/rep/sessions",
    {
      method: "POST",
      body: JSON.stringify({
        assignment_id: assignmentId,
        rep_id: repId,
        scenario_id: scenarioId
      })
    },
    { userId: repId, role: "rep" }
  );
}

export async function fetchRepSession(repId: string, sessionId: string): Promise<RepSessionDetail> {
  return requestJson<RepSessionDetail>(
    `/rep/sessions/${encodeURIComponent(sessionId)}`,
    {},
    { userId: repId, role: "rep" }
  );
}

export function getRepSessionWsUrl(sessionId: string): string {
  return `${WS_BASE}/ws/sessions/${encodeURIComponent(sessionId)}`;
}

export function getManagerLiveSessionsStreamUrl(managerId: string): string {
  const auth = getValidStoredAuth();
  if (!auth) {
    throw createAuthRequiredError();
  }

  const params = new URLSearchParams({
    manager_id: managerId,
    access_token: auth.access_token,
  });
  return `${API_BASE}/manager/sessions/live/stream?${params.toString()}`;
}
