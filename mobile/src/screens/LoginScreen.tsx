import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useEffect, useState } from "react";
import { Pressable, SafeAreaView, StyleSheet, Text, TextInput, View, KeyboardAvoidingView, Platform, ActivityIndicator } from "react-native";
import { BlurView } from "expo-blur";
import { LinearGradient } from "expo-linear-gradient";
import { TreePine, Mail, Lock } from "lucide-react-native";

import { RootStackParamList } from "../navigation/types";
import { useSession } from "../store/session";
import { loginWithCredentials } from "../services/api";
import { registerPushTokenIfAuthorized } from "../services/notifications";

type Props = NativeStackScreenProps<RootStackParamList, "Login">;

export function LoginScreen({ navigation, route }: Props) {
  const { setSession } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [successMessage, setSuccessMessage] = useState("");

  useEffect(() => {
    if (!route.params?.message) {
      return;
    }
    setSuccessMessage(route.params.message);
    navigation.setParams({ message: undefined });
  }, [navigation, route.params?.message]);

  const canContinue = email.trim().length > 0 && password.trim().length > 0 && !loading;

  const handleLogin = async () => {
    setLoading(true);
    setError("");
    setSuccessMessage("");
    try {
      const result = await loginWithCredentials(email.trim(), password);
      await setSession(result.user, {
        access: result.access_token,
        refresh: result.refresh_token,
      });
      void registerPushTokenIfAuthorized().catch(() => undefined);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Invalid email or password";
      setError(message.toLowerCase().includes("invalid credentials") ? "Invalid email or password" : message);
      setLoading(false);
    }
  };

  return (
    <LinearGradient colors={["#FBF9F5", "#EFEEEA", "#E4E2DE"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : "height"}
          style={styles.keyboardView}
        >
          <View style={styles.content}>
            <View style={styles.brandContainer}>
              <View style={styles.iconWrapper}>
                <TreePine size={32} color="#a1d2ad" strokeWidth={2.5} />
              </View>
              <Text style={styles.title}>DoorDrill</Text>
              <Text style={styles.subtitle}>Sign in to your account</Text>
            </View>

            <BlurView intensity={40} tint="light" style={styles.glassCard}>
              <View style={styles.inputGroup}>
                <Text style={styles.label}>Email or Username</Text>
                <View style={styles.inputWrapper}>
                  <Mail size={18} color="#9ca3af" style={styles.inputIcon} />
                  <TextInput
                    style={styles.input}
                    value={email}
                    onChangeText={setEmail}
                    placeholder="Enter your email or username"
                    placeholderTextColor="#6b7280"
                    autoCapitalize="none"
                    autoCorrect={false}
                    autoComplete="username"
                    textContentType="username"
                    selectionColor="#516354"
                  />
                </View>
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.label}>Password</Text>
                <View style={styles.inputWrapper}>
                  <Lock size={18} color="#9ca3af" style={styles.inputIcon} />
                  <TextInput
                    style={styles.input}
                    value={password}
                    onChangeText={setPassword}
                    placeholder="••••••••"
                    placeholderTextColor="#6b7280"
                    secureTextEntry
                    selectionColor="#516354"
                  />
                </View>
              </View>

              {error ? (
                <Text style={styles.errorText}>{error}</Text>
              ) : null}

              {successMessage ? <Text style={styles.successText}>{successMessage}</Text> : null}

              <Pressable
                style={({ pressed }) => [
                  styles.button,
                  !canContinue && styles.buttonDisabled,
                  pressed && canContinue && styles.buttonPressed
                ]}
                disabled={!canContinue}
                onPress={handleLogin}
              >
                {loading ? (
                  <ActivityIndicator color="#ffffff" />
                ) : (
                  <Text style={styles.buttonLabel}>Sign In</Text>
                )}
              </Pressable>

              <Pressable
                onPress={() => navigation.navigate("ForgotPassword")}
                style={styles.secondaryAction}
                accessibilityLabel="Go to forgot password screen"
              >
                <Text style={styles.secondaryActionText}>Forgot password?</Text>
              </Pressable>
            </BlurView>
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  safeArea: { flex: 1 },
  keyboardView: { flex: 1 },
  content: {
    flex: 1,
    justifyContent: "center",
    paddingHorizontal: 24,
    paddingBottom: 40,
  },
  brandContainer: {
    alignItems: "center",
    marginBottom: 44,
  },
  iconWrapper: {
    width: 68,
    height: 68,
    borderRadius: 22,
    backgroundColor: "rgba(22, 101, 52, 0.12)",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 20,
    borderWidth: 1,
    borderColor: "rgba(22, 101, 52, 0.25)",
  },
  title: {
    fontFamily: "Poppins_800ExtraBold",
    fontSize: 34,
    fontWeight: "800",
    color: "#1F1A13",
    letterSpacing: 0.5,
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: "#6C6255",
    fontWeight: "400",
    letterSpacing: 0.2,
  },
  glassCard: {
    borderRadius: 24,
    padding: 24,
    borderWidth: 1,
    borderColor: "rgba(0, 0, 0, 0.08)",
    overflow: "hidden",
    backgroundColor: "rgba(255, 255, 255, 0.5)",
  },
  inputGroup: {
    marginBottom: 20,
  },
  label: {
    fontSize: 12,
    fontWeight: "600",
    color: "#6C6255",
    marginBottom: 8,
    textTransform: "uppercase",
    letterSpacing: 0.8,
  },
  inputWrapper: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "rgba(255, 255, 255, 0.8)",
    borderWidth: 1,
    borderColor: "rgba(0, 0, 0, 0.08)",
    borderRadius: 14,
    height: 54,
    paddingHorizontal: 16,
  },
  inputIcon: {
    marginRight: 12,
  },
  input: {
    flex: 1,
    color: "#1F1A13",
    fontSize: 16,
    height: "100%",
  },
  button: {
    marginTop: 12,
    backgroundColor: "#144227",
    borderRadius: 14,
    height: 56,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#144227",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 10,
    elevation: 4,
    borderWidth: 1,
    borderColor: "rgba(255, 255, 255, 0.1)",
  },
  buttonDisabled: {
    backgroundColor: "rgba(22, 101, 52, 0.4)",
    shadowOpacity: 0,
    borderColor: "transparent",
  },
  buttonPressed: {
    opacity: 0.85,
    transform: [{ scale: 0.98 }],
  },
  buttonLabel: {
    color: "#ffffff",
    fontWeight: "700",
    fontSize: 17,
    letterSpacing: 0.3,
  },
  errorText: {
    color: "#dc2626",
    marginBottom: 16,
    textAlign: "center",
    fontWeight: "500",
  },
  successText: {
    color: "#144227",
    marginBottom: 16,
    textAlign: "center",
    fontWeight: "600",
  },
  secondaryAction: {
    marginTop: 20,
    alignItems: "center",
  },
  secondaryActionText: {
    color: "#144227",
    fontWeight: "700",
    fontSize: 15,
  },
});
