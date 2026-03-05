import { StatusBar } from "expo-status-bar";

import { AppNavigator } from "./src/navigation/AppNavigator";
import { SessionProvider } from "./src/store/session";

export default function App() {
  return (
    <SessionProvider>
      <StatusBar style="dark" />
      <AppNavigator />
    </SessionProvider>
  );
}
