import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { ClipboardList, History, User } from "lucide-react-native";

import { useSession } from "../store/session";
import { AssignmentsScreen } from "../screens/AssignmentsScreen";
import { PreSessionScreen } from "../screens/PreSessionScreen";
import { HistoryScreen } from "../screens/HistoryScreen";
import { LoginScreen } from "../screens/LoginScreen";
import { ScoreScreen } from "../screens/ScoreScreen";
import { SessionScreen } from "../screens/SessionScreen";
import { ProfileScreen } from "../screens/ProfileScreen";
import { RootStackParamList, BottomTabParamList } from "./types";
import { colors } from "../theme/tokens";

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tab = createBottomTabNavigator<BottomTabParamList>();

function MainTabNavigator() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerShown: false,
        tabBarStyle: {
          backgroundColor: colors.panel,
          borderTopColor: colors.line,
          paddingBottom: 8,
          paddingTop: 8,
          height: 60,
        },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.muted,
        tabBarLabelStyle: {
          fontSize: 12,
          fontWeight: "600",
        },
      }}
    >
      <Tab.Screen 
        name="AssignmentsTab" 
        component={AssignmentsScreen} 
        options={{
          tabBarLabel: "Drills",
          tabBarIcon: ({ color, size }) => <ClipboardList color={color} size={size} />,
        }}
      />
      <Tab.Screen 
        name="HistoryTab" 
        component={HistoryScreen} 
        options={{
          tabBarLabel: "History",
          tabBarIcon: ({ color, size }) => <History color={color} size={size} />,
        }}
      />
      <Tab.Screen 
        name="ProfileTab" 
        component={ProfileScreen} 
        options={{
          tabBarLabel: "Profile",
          tabBarIcon: ({ color, size }) => <User color={color} size={size} />,
        }}
      />
    </Tab.Navigator>
  );
}

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
          <Stack.Screen name="MainTabs" component={MainTabNavigator} options={{ headerShown: false }} />
          <Stack.Screen 
            name="PreSession" 
            component={PreSessionScreen} 
            options={{ 
              headerShown: false,
              presentation: "transparentModal",
              animation: "fade"
            }} 
          />
          <Stack.Screen name="Session" component={SessionScreen} options={{ headerShown: false }} />
          <Stack.Screen name="Score" component={ScoreScreen} options={{ title: "Scorecard" }} />
        </Stack.Navigator>
      )}
    </NavigationContainer>
  );
}
