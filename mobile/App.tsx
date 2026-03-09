import "react-native-gesture-handler";
import { StatusBar } from "expo-status-bar";
import { useFonts } from "expo-font";
import * as Notifications from "expo-notifications";
import { Inter_400Regular, Inter_600SemiBold, Inter_700Bold } from "@expo-google-fonts/inter";
import { Poppins_400Regular, Poppins_600SemiBold, Poppins_700Bold, Poppins_800ExtraBold } from "@expo-google-fonts/poppins";
import { Outfit_400Regular, Outfit_600SemiBold, Outfit_700Bold, Outfit_800ExtraBold } from "@expo-google-fonts/outfit";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { useEffect } from "react";

import { AppNavigator } from "./src/navigation/AppNavigator";
import { SessionProvider } from "./src/store/session";
import { MessagesProvider } from "./src/store/messages";
import { handleForegroundNotification, setupNotificationResponseListener } from "./src/services/notifications";

export default function App() {
  const [fontsLoaded] = useFonts({
    Inter_400Regular,
    Inter_600SemiBold,
    Inter_700Bold,
    Poppins_400Regular,
    Poppins_600SemiBold,
    Poppins_700Bold,
    Poppins_800ExtraBold,
    Outfit_400Regular,
    Outfit_600SemiBold,
    Outfit_700Bold,
    Outfit_800ExtraBold,
  });

  if (!fontsLoaded) {
    return null;
  }

  return <AppRoot />;
}

function AppRoot() {
  useEffect(() => {
    const responseCleanup = setupNotificationResponseListener();
    const foregroundSub = Notifications.addNotificationReceivedListener((notification) => {
      handleForegroundNotification(notification);
    });

    return () => {
      foregroundSub.remove();
      responseCleanup();
    };
  }, []);

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SessionProvider>
        <MessagesProvider>
          <StatusBar style="dark" />
          <AppNavigator />
        </MessagesProvider>
      </SessionProvider>
    </GestureHandlerRootView>
  );
}
