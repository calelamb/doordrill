import { NavigationContainer } from "@react-navigation/native";
import { createNativeStackNavigator } from "@react-navigation/native-stack";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { ClipboardList, History, User, MessageSquare } from "lucide-react-native";
import { Platform } from "react-native";

import { useSession } from "../store/session";
import { AssignmentsScreen } from "../screens/AssignmentsScreen";
import { PreSessionScreen } from "../screens/PreSessionScreen";
import { HistoryScreen } from "../screens/HistoryScreen";
import { LoginScreen } from "../screens/LoginScreen";
import { ScoreScreen } from "../screens/ScoreScreen";
import { SessionScreen } from "../screens/SessionScreen";
import { ProfileScreen } from "../screens/ProfileScreen";
import { CommunicationsScreen } from "../screens/CommunicationsScreen";
import { MessageThreadScreen } from "../screens/MessageThreadScreen";
import { NewMessageScreen } from "../screens/NewMessageScreen";
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
          backgroundColor: "#FFFCF4",
          borderTopColor: "rgba(0, 0, 0, 0.05)",
          borderTopWidth: 1,
          paddingBottom: Platform.OS === "ios" ? 24 : 8,
          paddingTop: 8,
          height: Platform.OS === "ios" ? 85 : 65,
        },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: "#6C6255",
        tabBarLabelStyle: {
          fontSize: 11,
          fontWeight: "700",
          marginTop: 4,
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
        name="CommunicationsTab" 
        component={CommunicationsScreen} 
        options={{
          tabBarLabel: "Inbox",
          tabBarIcon: ({ color, size }) => <MessageSquare color={color} size={size} />,
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
          <Stack.Screen name="MessageThread" component={MessageThreadScreen} options={{ headerShown: false }} />
          <Stack.Screen 
            name="NewMessage" 
            component={NewMessageScreen} 
            options={{
              headerShown: false,
              presentation: "modal"
            }} 
          />
        </Stack.Navigator>
      )}
    </NavigationContainer>
  );
}
