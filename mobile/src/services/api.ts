import { API_BASE_URL } from "./config";
import { RepAssignment, RepSessionDetail } from "../types";

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

export async function fetchRepSession(repId: string, sessionId: string): Promise<RepSessionDetail> {
  const response = await fetch(`${API_BASE_URL}/rep/sessions/${encodeURIComponent(sessionId)}`, {
    headers: repHeaders(repId)
  });
  return parseJson<RepSessionDetail>(response, "fetch session detail");
}
