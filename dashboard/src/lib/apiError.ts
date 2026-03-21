export class ApiError extends Error {
  status: number;
  code?: string | null;
  detail?: unknown;

  constructor(message: string, status: number, code?: string | null, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

export function formatApiErrorDetail(detail: unknown, status: number, fallback: string): string {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (detail && typeof detail === "object") {
    const message = "message" in detail ? (detail as { message?: unknown }).message : null;
    if (typeof message === "string" && message.trim()) {
      return message;
    }
  }
  return `${fallback}: ${status}`;
}

export function extractApiErrorCode(detail: unknown): string | null {
  if (detail && typeof detail === "object" && "code" in detail) {
    const code = (detail as { code?: unknown }).code;
    return typeof code === "string" && code.trim() ? code : null;
  }
  return null;
}

export function getApiErrorCode(error: unknown): string | null {
  return error instanceof ApiError ? error.code ?? null : null;
}
