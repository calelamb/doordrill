import { Platform } from "react-native";
import Constants from "expo-constants";

const extras = (Constants.expoConfig?.extra ?? {}) as Record<string, string | undefined>;

// Try to get the IP address of the machine running the Expo development server
// This is essential for testing on a physical device via Expo Go.
const debuggerHost = Constants.expoConfig?.hostUri;
const localhost = debuggerHost 
  ? debuggerHost.split(':')[0] 
  : (Platform.OS === "android" ? "10.0.2.2" : "127.0.0.1");

const defaultApiUrl = `http://${localhost}:8000`;

export const API_BASE_URL = process.env.EXPO_PUBLIC_API_BASE_URL ?? extras.apiBaseUrl ?? defaultApiUrl;
export const WS_BASE_URL =
  process.env.EXPO_PUBLIC_WS_BASE_URL ??
  extras.wsBaseUrl ??
  API_BASE_URL.replace(/^http/i, "ws");
