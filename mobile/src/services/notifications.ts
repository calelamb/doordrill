import AsyncStorage from "@react-native-async-storage/async-storage";
import { createNavigationContainerRef } from "@react-navigation/native";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

import { RootStackParamList } from "../navigation/types";
import { registerDeviceToken } from "./api";
import { EXPO_PROJECT_ID } from "./config";

type NotificationIntent =
  | {
      name: "Score";
      params: RootStackParamList["Score"];
    }
  | {
      name: "MainTabs";
      params: RootStackParamList["MainTabs"];
    };

type NotificationData = Record<string, unknown>;

export const navigationRef = createNavigationContainerRef<RootStackParamList>();

let pendingNotificationIntent: NotificationIntent | null = null;
let lastHandledNotificationId: string | null = null;
const PUSH_TOKEN_ID_STORAGE_KEY = "push_token_id";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});

function notificationIntentFromData(data: NotificationData): NotificationIntent | null {
  const type = typeof data.type === "string" ? data.type : null;
  const sessionId = typeof data.session_id === "string" ? data.session_id : null;

  switch (type) {
    case "score_ready":
    case "coaching_note":
      return sessionId
        ? {
            name: "Score",
            params: { sessionId },
          }
        : null;
    case "assignment_created":
    case "assignment_due_soon":
      return {
        name: "MainTabs",
        params: { screen: "AssignmentsTab" },
      };
    default:
      return null;
  }
}

function canNavigateTo(routeName: keyof RootStackParamList): boolean {
  const state = navigationRef.getRootState();
  return Boolean(state?.routeNames.includes(routeName));
}

function navigateToIntent(intent: NotificationIntent): boolean {
  if (!navigationRef.isReady() || !canNavigateTo(intent.name)) {
    pendingNotificationIntent = intent;
    return false;
  }

  if (intent.name === "Score") {
    navigationRef.navigate("Score", intent.params);
  } else {
    navigationRef.navigate("MainTabs", intent.params);
  }
  pendingNotificationIntent = null;
  return true;
}

function handleNotificationResponse(response: Notifications.NotificationResponse): void {
  const notificationId = response.notification.request.identifier;
  if (notificationId === lastHandledNotificationId) {
    return;
  }

  const intent = notificationIntentFromData(response.notification.request.content.data as NotificationData);
  if (!intent) {
    return;
  }

  lastHandledNotificationId = notificationId;
  navigateToIntent(intent);
}

export function flushPendingNotificationNavigation(): boolean {
  if (!pendingNotificationIntent) {
    return false;
  }
  return navigateToIntent(pendingNotificationIntent);
}

export async function requestAndRegisterPushToken(repId: string): Promise<void> {
  if (!repId.trim() || !Device.isDevice) {
    return;
  }

  if (Platform.OS !== "ios" && Platform.OS !== "android") {
    return;
  }

  if (!EXPO_PROJECT_ID) {
    return;
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;

  if (existingStatus !== "granted") {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }

  if (finalStatus !== "granted") {
    return;
  }

  const token = (
    await Notifications.getExpoPushTokenAsync({
      projectId: EXPO_PROJECT_ID,
    })
  ).data;

  const registeredToken = await registerDeviceToken(repId, {
    token,
    platform: Platform.OS,
    provider: "expo",
  });
  await AsyncStorage.setItem(PUSH_TOKEN_ID_STORAGE_KEY, registeredToken.id);
}

export async function getStoredPushToken(): Promise<string | null> {
  return AsyncStorage.getItem(PUSH_TOKEN_ID_STORAGE_KEY);
}

export async function clearStoredPushToken(): Promise<void> {
  await AsyncStorage.removeItem(PUSH_TOKEN_ID_STORAGE_KEY);
}

export function setupNotificationResponseListener(): () => void {
  void Notifications.getLastNotificationResponseAsync().then((response) => {
    if (response) {
      handleNotificationResponse(response);
    }
  });

  const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
    handleNotificationResponse(response);
  });

  return () => {
    subscription.remove();
  };
}

export function handleForegroundNotification(notification: Notifications.Notification): void {
  const data = notification.request.content.data as NotificationData;
  const type = typeof data.type === "string" ? data.type : null;

  switch (type) {
    case "score_ready":
    case "coaching_note":
    case "assignment_created":
    case "assignment_due_soon":
      break;
    default:
      break;
  }
}
