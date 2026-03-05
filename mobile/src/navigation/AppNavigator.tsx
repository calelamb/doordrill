import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";

import { useSession } from "../store/session";
import { AssignmentsScreen } from "../screens/AssignmentsScreen";
import { PreSessionScreen } from "../screens/PreSessionScreen";
import { HistoryScreen } from "../screens/HistoryScreen";
import { LoginScreen } from "../screens/LoginScreen";
import { ScoreScreen } from "../screens/ScoreScreen";
import { SessionScreen } from "../screens/SessionScreen";
import { ProfileScreen } from "../screens/ProfileScreen";
import { RootStackParamList } from "./types";
import { colors } from "../theme/tokens";

const Stack = createNativeStackNavigator<RootStackParamList>();

export function AppNavigator() {
  const { repId } = useSession();

  return (
    <NavigationContainer>
      {!repId ? (
        <Stack.Navigator>
          <Stack.Screen name="Login" component={LoginScreen} options={{ headerShown: false }} />
        </Stack.Navigator>
      ) : (
        <Stack.Navigator
          screenOptions={{
            headerStyle: { backgroundColor: colors.panel },
            headerTitleStyle: { color: colors.ink },
            headerTintColor: colors.accent
          }}
        >
          <Stack.Screen name="Assignments" component={AssignmentsScreen} options={{ headerShown: false }} />
          <Stack.Screen name="PreSession" component={PreSessionScreen} options={{ title: "Drill Brief" }} />
          <Stack.Screen name="Session" component={SessionScreen} options={{ headerShown: false }} />
          <Stack.Screen name="Score" component={ScoreScreen} options={{ title: "Scorecard" }} />
          <Stack.Screen name="History" component={HistoryScreen} options={{ title: "History" }} />
          <Stack.Screen name="Profile" component={ProfileScreen} options={{ title: "Profile" }} />
        </Stack.Navigator>
      )}
    </NavigationContainer>
  );
}
