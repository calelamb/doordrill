import { Platform } from "react-native";
import Constants from "expo-constants";

const extras = (Constants.expoConfig?.extra ?? {}) as Record<string, string | undefined>;

// Use 10.0.2.2 for Android emulator to reach host localhost, otherwise 127.0.0.1
const defaultHost = Platform.OS === "android" ? "10.0.2.2" : "127.0.0.1";
const defaultApiUrl = `http://${defaultHost}:8000`;

export const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? extras.apiBaseUrl ?? defaultApiUrl;
export const WS_BASE_URL =
  process.env.EXPO_PUBLIC_WS_BASE_URL ??
  extras.wsBaseUrl ??
  API_BASE_URL.replace(/^http/i, "ws");
