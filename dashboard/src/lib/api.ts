import { clearStoredAuth, createAuthRequiredError, getValidStoredAuth, storeAuth } from "./auth";
import type { AuthSession } from "./auth";
import type {
  FeedItem,
  ManagerActionLog,
  ManagerAnalytics,
  ManagerAssignment,
  ManagerTeamMember,
  ReplayResponse,
  RepAssignment,
  RepProgress,
  RepSessionDetail,
  ScenarioSummary,
  SessionDetail,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const WS_BASE = import.meta.env.VITE_WS_BASE_URL ?? API_BASE.replace(/^http/i, "ws");

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

function formatErrorDetail(detail: unknown, status: number, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  return `${fallback}: ${status}`;
}

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
    throw new Error(formatErrorDetail(detail, response.status, path));
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

export async function fetchScenarios(): Promise<ScenarioSummary[]> {
  const auth = getValidStoredAuth();
  if (!auth) {
    throw createAuthRequiredError();
  }
  return requestJson<ScenarioSummary[]>("/scenarios", {}, { userId: auth.user.id, role: auth.user.role as "manager" | "admin" | "rep" });
}

export async function fetchManagerFeed(managerId: string): Promise<FeedItem[]> {
  const [feedBody, sessions, team, scenarios] = await Promise.all([
    requestJson<{ items: FeedItem[] }>(
      `/manager/feed?manager_id=${encodeURIComponent(managerId)}`,
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

export async function fetchManagerAnalytics(managerId: string): Promise<ManagerAnalytics> {
  return requestJson<ManagerAnalytics>(
    `/manager/analytics?manager_id=${encodeURIComponent(managerId)}`,
    {},
    { userId: managerId, role: "manager" }
  );
}

export async function fetchRepProgress(managerId: string, repId: string): Promise<RepProgress> {
  return requestJson<RepProgress>(
    `/manager/reps/${encodeURIComponent(repId)}/progress?manager_id=${encodeURIComponent(managerId)}`,
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
