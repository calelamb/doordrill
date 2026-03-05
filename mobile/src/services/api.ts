import { API_BASE_URL } from "./config";
import { RepAssignment, RepSessionDetail, ScenarioBrief } from "../types";

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
  assignmentId: string,
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
