export type AuthUser = {
  id: string;
  org_id: string;
  team_id?: string | null;
  role: string;
  name: string;
  email: string;
};

export type AuthSession = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  token_type?: string;
  user: AuthUser;
};

export const AUTH_STORAGE_KEY = "doordrill.dashboard.auth";
export const AUTH_REQUIRED_ERROR = "AUTH_REQUIRED";

function decodeJwtPayload(token: string): Record<string, unknown> | null {
  try {
    const encoded = token.split(".")[1];
    if (!encoded) {
      return null;
    }
    const normalized = encoded.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized.padEnd(normalized.length + ((4 - (normalized.length % 4)) % 4), "=");
    const json = window.atob(padded);
    return JSON.parse(json) as Record<string, unknown>;
  } catch {
    return null;
  }
}

export function isJwtExpired(token: string | null | undefined, skewSeconds = 30): boolean {
  if (!token) {
    return true;
  }
  const payload = decodeJwtPayload(token);
  const exp = typeof payload?.exp === "number" ? payload.exp : null;
  if (!exp) {
    return true;
  }
  return exp <= Math.floor(Date.now() / 1000) + skewSeconds;
}

export function getStoredAuth(): AuthSession | null {
  try {
    const raw = window.localStorage.getItem(AUTH_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    return JSON.parse(raw) as AuthSession;
  } catch {
    return null;
  }
}

export function storeAuth(session: AuthSession): void {
  window.localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(session));
}

export function clearStoredAuth(): void {
  window.localStorage.removeItem(AUTH_STORAGE_KEY);
}

export function getValidStoredAuth(): AuthSession | null {
  const session = getStoredAuth();
  if (!session || isJwtExpired(session.access_token)) {
    clearStoredAuth();
    return null;
  }
  return session;
}

export function createAuthRequiredError(): Error {
  return new Error(AUTH_REQUIRED_ERROR);
}

export function isAuthError(error: unknown): boolean {
  return error instanceof Error && error.message === AUTH_REQUIRED_ERROR;
}
