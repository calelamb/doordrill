import { API_BASE_URL } from "./config";
import { RepAssignment, RepProgress, RepSessionDetail, ScenarioBrief } from "../types";

type HeaderMap = Record<string, string>;

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
  return parseJson<RepSessionDetail>(response, "fetch session detail");
}

export async function fetchRepProgress(repId: string): Promise<RepProgress> {
  const response = await fetch(`${API_BASE_URL}/rep/progress?rep_id=${encodeURIComponent(repId)}`, {
    headers: repHeaders(repId)
  });
  return parseJson<RepProgress>(response, "fetch progress");
}

export async function fetchRepSessionsHistory(repId: string): Promise<{ items: import("../types").RepSessionHistoryItem[] }> {
  const response = await fetch(`${API_BASE_URL}/rep/sessions?rep_id=${encodeURIComponent(repId)}`, {
    headers: repHeaders(repId)
  });
  return parseJson<{ items: import("../types").RepSessionHistoryItem[] }>(response, "fetch history");
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
