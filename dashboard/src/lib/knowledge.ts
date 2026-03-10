import { clearStoredAuth, createAuthRequiredError, getValidStoredAuth } from "./auth";
import type {
  KnowledgeDeleteResponse,
  KnowledgeDocument,
  KnowledgeDocumentListResponse,
  KnowledgeQueryResponse,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? "/api" : "http://127.0.0.1:8000");
const MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024;
const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt"];

function buildAuthHeaders(managerId: string): Headers {
  const auth = getValidStoredAuth();
  if (!auth) {
    throw createAuthRequiredError();
  }

  const headers = new Headers();
  headers.set("authorization", `Bearer ${auth.access_token}`);
  headers.set("x-user-id", managerId || auth.user.id);
  headers.set("x-user-role", "manager");
  return headers;
}

function formatError(detail: unknown, status: number, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  return `${fallback}: ${status}`;
}

async function requestJson<T>(managerId: string, path: string, init: RequestInit): Promise<T> {
  const headers = buildAuthHeaders(managerId);
  const initHeaders = new Headers(init.headers ?? undefined);
  initHeaders.forEach((value, key) => {
    headers.set(key, value);
  });
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
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
    throw new Error(formatError(detail, response.status, path));
  }

  return response.json() as Promise<T>;
}

export function validateKnowledgeFile(file: File): string | null {
  const normalizedName = file.name.toLowerCase();
  if (!ACCEPTED_EXTENSIONS.some((extension) => normalizedName.endsWith(extension))) {
    return "Only PDF, DOCX, and TXT files are supported.";
  }
  if (file.size > MAX_FILE_SIZE_BYTES) {
    return "File size must be 25MB or smaller.";
  }
  return null;
}

export function uploadDocument(
  file: File,
  name: string,
  managerId: string,
  onProgress?: (progress: number) => void,
): Promise<KnowledgeDocument> {
  return new Promise<KnowledgeDocument>((resolve, reject) => {
    const validationError = validateKnowledgeFile(file);
    if (validationError) {
      reject(new Error(validationError));
      return;
    }

    const auth = getValidStoredAuth();
    if (!auth) {
      reject(createAuthRequiredError());
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    formData.append("name", name);
    formData.append("manager_id", managerId);

    const request = new XMLHttpRequest();
    request.open("POST", `${API_BASE}/manager/documents`);
    request.setRequestHeader("authorization", `Bearer ${auth.access_token}`);
    request.setRequestHeader("x-user-id", managerId || auth.user.id);
    request.setRequestHeader("x-user-role", "manager");

    request.upload.addEventListener("progress", (event) => {
      if (!event.lengthComputable || !onProgress) {
        return;
      }
      onProgress(Math.min(100, Math.round((event.loaded / event.total) * 100)));
    });

    request.addEventListener("load", () => {
      if (request.status === 401) {
        clearStoredAuth();
        reject(createAuthRequiredError());
        return;
      }

      let parsed: unknown = null;
      try {
        parsed = request.responseText ? JSON.parse(request.responseText) : null;
      } catch {
        parsed = null;
      }

      if (request.status < 200 || request.status >= 300) {
        const detail =
          parsed && typeof parsed === "object" && parsed !== null && "detail" in parsed
            ? (parsed as { detail?: unknown }).detail
            : null;
        reject(new Error(formatError(detail, request.status, "/manager/documents")));
        return;
      }

      onProgress?.(100);
      resolve(parsed as KnowledgeDocument);
    });

    request.addEventListener("error", () => {
      reject(new Error("Upload failed. Check your network connection and try again."));
    });

    request.send(formData);
  });
}

export async function listDocuments(managerId: string): Promise<KnowledgeDocument[]> {
  const response = await requestJson<KnowledgeDocumentListResponse>(
    managerId,
    `/manager/documents?manager_id=${encodeURIComponent(managerId)}`,
    { method: "GET" },
  );
  return response.documents ?? [];
}

export async function deleteDocument(documentId: string, managerId: string): Promise<KnowledgeDeleteResponse> {
  return requestJson<KnowledgeDeleteResponse>(
    managerId,
    `/manager/documents/${encodeURIComponent(documentId)}?manager_id=${encodeURIComponent(managerId)}`,
    { method: "DELETE" },
  );
}

export async function queryDocuments(
  managerId: string,
  query: string,
  k = 5,
): Promise<KnowledgeQueryResponse> {
  return requestJson<KnowledgeQueryResponse>(
    managerId,
    "/manager/documents/query",
    {
      method: "POST",
      body: JSON.stringify({ manager_id: managerId, query, k }),
      headers: { "content-type": "application/json" },
    },
  );
}
