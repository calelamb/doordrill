import Constants from "expo-constants";

const extras = (Constants.expoConfig?.extra ?? {}) as Record<string, string | undefined>;

export const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? extras.apiBaseUrl ?? "http://127.0.0.1:8000";
export const WS_BASE_URL =
  process.env.EXPO_PUBLIC_WS_BASE_URL ??
  extras.wsBaseUrl ??
  API_BASE_URL.replace(/^http/i, "ws");
