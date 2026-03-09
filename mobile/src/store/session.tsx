import * as SecureStore from "expo-secure-store";
import { ReactNode } from "react";
import { create } from "zustand";

import { refreshTokens } from "../services/api";
import { AuthRole, AuthUser } from "../types";

const ACCESS_TOKEN_KEY = "dd_access_token";
const REFRESH_TOKEN_KEY = "dd_refresh_token";

type AuthTokens = {
  access: string;
  refresh: string;
};

type SessionState = {
  repId: string | null;
  userId: string | null;
  orgId: string | null;
  role: AuthRole | null;
  name: string | null;
  isAuthenticated: boolean;
  isFirstLaunch: boolean;
  setSession: (user: AuthUser, tokens: AuthTokens) => Promise<void>;
  restoreSession: () => Promise<void>;
  clearSession: () => Promise<void>;
  getAccessToken: () => Promise<string | null>;
  getRefreshToken: () => Promise<string | null>;
};

type Props = {
  children: ReactNode;
};

const unauthenticatedState = {
  repId: null,
  userId: null,
  orgId: null,
  role: null,
  name: null,
  isAuthenticated: false,
};

export const useSession = create<SessionState>((set, get) => ({
  ...unauthenticatedState,
  isFirstLaunch: true,

  setSession: async (user, tokens) => {
    await Promise.all([
      SecureStore.setItemAsync(ACCESS_TOKEN_KEY, tokens.access),
      SecureStore.setItemAsync(REFRESH_TOKEN_KEY, tokens.refresh),
    ]);

    set({
      repId: user.id,
      userId: user.id,
      orgId: user.org_id,
      role: user.role,
      name: user.name,
      isAuthenticated: true,
      isFirstLaunch: false,
    });
  },

  restoreSession: async () => {
    const refreshToken = await SecureStore.getItemAsync(REFRESH_TOKEN_KEY);
    if (!refreshToken) {
      set({ isFirstLaunch: false });
      return;
    }

    try {
      const result = await refreshTokens(refreshToken);
      await get().setSession(result.user, {
        access: result.access_token,
        refresh: result.refresh_token,
      });
    } catch {
      await get().clearSession();
    } finally {
      set({ isFirstLaunch: false });
    }
  },

  clearSession: async () => {
    await Promise.all([
      SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY),
      SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY),
    ]);
    set({
      ...unauthenticatedState,
      isFirstLaunch: false,
    });
  },

  getAccessToken: async () => SecureStore.getItemAsync(ACCESS_TOKEN_KEY),
  getRefreshToken: async () => SecureStore.getItemAsync(REFRESH_TOKEN_KEY),
}));

export function SessionProvider({ children }: Props) {
  return <>{children}</>;
}
