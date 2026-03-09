import "react-native-gesture-handler";
import { StatusBar } from "expo-status-bar";
import { useFonts } from "expo-font";
import * as Notifications from "expo-notifications";
import { Inter_400Regular, Inter_600SemiBold, Inter_700Bold } from "@expo-google-fonts/inter";
import { Poppins_400Regular, Poppins_600SemiBold, Poppins_700Bold, Poppins_800ExtraBold } from "@expo-google-fonts/poppins";
import { Outfit_400Regular, Outfit_600SemiBold, Outfit_700Bold, Outfit_800ExtraBold } from "@expo-google-fonts/outfit";
import { GestureHandlerRootView } from "react-native-gesture-handler";
import { useEffect, useState } from "react";

import { AppNavigator } from "./src/navigation/AppNavigator";
import { OnboardingScreen } from "./src/screens/OnboardingScreen";
import { SplashScreen } from "./src/screens/SplashScreen";
import { SessionProvider } from "./src/store/session";
import { MessagesProvider } from "./src/store/messages";
import { primeInitialInviteUrl, setupInviteLinkListener } from "./src/services/inviteLinking";
import { handleForegroundNotification, setupNotificationResponseListener } from "./src/services/notifications";
import { hasSeenOnboarding, markOnboardingComplete } from "./src/services/onboarding";
import { useSession } from "./src/store/session";

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
    return <SplashScreen />;
  }

  return <AppRoot />;
}

function AppRoot() {
  const [showOnboarding, setShowOnboarding] = useState<boolean | null>(null);

  useEffect(() => {
    void useSession.getState().restoreSession();
    void primeInitialInviteUrl();
    void hasSeenOnboarding().then((seen) => {
      setShowOnboarding(!seen);
    });
  }, []);

  useEffect(() => {
    const inviteCleanup = setupInviteLinkListener();
    const responseCleanup = setupNotificationResponseListener();
    const foregroundSub = Notifications.addNotificationReceivedListener((notification) => {
      handleForegroundNotification(notification);
    });

    return () => {
      foregroundSub.remove();
      responseCleanup();
      inviteCleanup();
    };
  }, []);

  const handleCompleteOnboarding = async () => {
    await markOnboardingComplete();
    setShowOnboarding(false);
  };

  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SessionProvider>
        <MessagesProvider>
          <StatusBar style="dark" />
          {showOnboarding === null ? (
            <SplashScreen />
          ) : showOnboarding ? (
            <OnboardingScreen onComplete={handleCompleteOnboarding} />
          ) : (
            <AppNavigator />
          )}
        </MessagesProvider>
      </SessionProvider>
    </GestureHandlerRootView>
  );
}
