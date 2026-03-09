import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { Platform } from "react-native";

import { registerDeviceToken } from "./api";
import { EXPO_PROJECT_ID } from "./config";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});

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

  await registerDeviceToken(repId, {
    token,
    platform: Platform.OS,
    provider: "expo",
  });
}
