import type { FeedItem, ManagerActionLog, ManagerAnalytics, ReplayResponse, RepAssignment, RepProgress, RepSessionDetail } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const WS_BASE = import.meta.env.VITE_WS_BASE_URL ?? API_BASE.replace(/^http/i, "ws");

const managerHeaders = (managerId: string) => ({
  "x-user-id": managerId,
  "x-user-role": "manager",
  "content-type": "application/json"
});

const repHeaders = (repId: string) => ({
  "x-user-id": repId,
  "x-user-role": "rep",
  "content-type": "application/json"
});

export async function fetchManagerFeed(managerId: string): Promise<FeedItem[]> {
  const response = await fetch(`${API_BASE}/manager/feed?manager_id=${encodeURIComponent(managerId)}`, {
    headers: managerHeaders(managerId)
  });
  if (!response.ok) {
    throw new Error(`feed request failed: ${response.status}`);
  }
  const body = await response.json();
  return body.items ?? [];
}

export async function fetchReplay(managerId: string, sessionId: string): Promise<ReplayResponse> {
  const response = await fetch(`${API_BASE}/manager/sessions/${sessionId}/replay`, {
    headers: managerHeaders(managerId)
  });
  if (!response.ok) {
    throw new Error(`replay request failed: ${response.status}`);
  }
  return response.json();
}

export async function submitOverride(
  managerId: string,
  scorecardId: string,
  payload: { reason_code: string; override_score?: number; notes?: string }
): Promise<void> {
  const response = await fetch(`${API_BASE}/manager/scorecards/${scorecardId}`, {
    method: "PATCH",
    headers: managerHeaders(managerId),
    body: JSON.stringify({ reviewer_id: managerId, ...payload })
  });
  if (!response.ok) {
    throw new Error(`override request failed: ${response.status}`);
  }
}

export async function createFollowup(
  managerId: string,
  scorecardId: string,
  scenarioId: string
): Promise<void> {
  const response = await fetch(`${API_BASE}/manager/scorecards/${scorecardId}/followup-assignment`, {
    method: "POST",
    headers: managerHeaders(managerId),
    body: JSON.stringify({
      scenario_id: scenarioId,
      assigned_by: managerId,
      retry_policy: { max_attempts: 2 }
    })
  });
  if (!response.ok) {
    throw new Error(`follow-up assignment request failed: ${response.status}`);
  }
}

export async function fetchManagerAnalytics(managerId: string): Promise<ManagerAnalytics> {
  const response = await fetch(`${API_BASE}/manager/analytics?manager_id=${encodeURIComponent(managerId)}`, {
    headers: managerHeaders(managerId)
  });
  if (!response.ok) {
    throw new Error(`analytics request failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchRepProgress(managerId: string, repId: string): Promise<RepProgress> {
  const response = await fetch(
    `${API_BASE}/manager/reps/${encodeURIComponent(repId)}/progress?manager_id=${encodeURIComponent(managerId)}`,
    { headers: managerHeaders(managerId) }
  );
  if (!response.ok) {
    throw new Error(`rep progress request failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchManagerActions(managerId: string, limit = 25): Promise<ManagerActionLog[]> {
  const response = await fetch(
    `${API_BASE}/manager/actions?manager_id=${encodeURIComponent(managerId)}&limit=${encodeURIComponent(limit)}`,
    { headers: managerHeaders(managerId) }
  );
  if (!response.ok) {
    throw new Error(`manager actions request failed: ${response.status}`);
  }
  const body = await response.json();
  return body.items ?? [];
}

export async function fetchRepAssignments(repId: string): Promise<RepAssignment[]> {
  const response = await fetch(`${API_BASE}/rep/assignments?rep_id=${encodeURIComponent(repId)}`, {
    headers: repHeaders(repId)
  });
  if (!response.ok) {
    throw new Error(`rep assignments request failed: ${response.status}`);
  }
  return response.json();
}

export async function createRepSession(
  repId: string,
  assignmentId: string,
  scenarioId: string
): Promise<{ id: string }> {
  const response = await fetch(`${API_BASE}/rep/sessions`, {
    method: "POST",
    headers: repHeaders(repId),
    body: JSON.stringify({
      assignment_id: assignmentId,
      rep_id: repId,
      scenario_id: scenarioId
    })
  });
  if (!response.ok) {
    throw new Error(`create rep session request failed: ${response.status}`);
  }
  return response.json();
}

export async function fetchRepSession(repId: string, sessionId: string): Promise<RepSessionDetail> {
  const response = await fetch(`${API_BASE}/rep/sessions/${encodeURIComponent(sessionId)}`, {
    headers: repHeaders(repId)
  });
  if (!response.ok) {
    throw new Error(`rep session request failed: ${response.status}`);
  }
  return response.json();
}

export function getRepSessionWsUrl(sessionId: string): string {
  return `${WS_BASE}/ws/sessions/${encodeURIComponent(sessionId)}`;
}
