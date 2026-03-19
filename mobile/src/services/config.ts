import { Platform } from "react-native";
import Constants from "expo-constants";
import * as Device from "expo-device";

type ExpoExtras = {
  apiBaseUrl?: string;
  wsBaseUrl?: string;
  projectId?: string;
};

const extras = (Constants.expoConfig?.extra ?? {}) as ExpoExtras;
type ExpoGoRuntimeConfig = {
  debuggerHost?: string;
};

// Try to get the IP address of the machine running the Expo development server
// This is essential for testing on a physical device via Expo Go.
const expoGoConfig = (Constants.expoGoConfig ?? null) as ExpoGoRuntimeConfig | null;
const debuggerHost = expoGoConfig?.debuggerHost ?? Constants.expoConfig?.hostUri;
const localhost = debuggerHost 
  ? debuggerHost.split(':')[0] 
  : (Platform.OS === "android" ? "10.0.2.2" : "127.0.0.1");

const defaultApiUrl = `http://${localhost}:8000`;
const simulatorApiUrl = `http://${Platform.OS === "android" ? "10.0.2.2" : "127.0.0.1"}:8000`;
const deviceDevApiUrl = __DEV__ ? defaultApiUrl : undefined;
const resolvedApiBaseUrl =
  Device.isDevice === false
    ? simulatorApiUrl
    : process.env.EXPO_PUBLIC_API_BASE_URL ?? deviceDevApiUrl ?? extras.apiBaseUrl ?? defaultApiUrl;

if (__DEV__ === false && resolvedApiBaseUrl.startsWith("http://127.0.0.1")) {
  console.warn("[DoorDrill] API base URL is pointing to localhost in a non-dev build. Set EXPO_PUBLIC_API_BASE_URL.");
}

export const API_BASE_URL = resolvedApiBaseUrl;
export const WS_BASE_URL =
  (Device.isDevice === false
    ? API_BASE_URL.replace(/^http/i, "ws")
    : process.env.EXPO_PUBLIC_WS_BASE_URL ?? (__DEV__ ? defaultApiUrl.replace(/^http/i, "ws") : undefined) ?? extras.wsBaseUrl) ??
  API_BASE_URL.replace(/^http/i, "ws");
export const EXPO_PROJECT_ID = process.env.EXPO_PUBLIC_PROJECT_ID ?? extras.projectId ?? null;
