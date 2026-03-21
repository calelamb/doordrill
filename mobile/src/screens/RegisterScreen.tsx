import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { BlurView } from "expo-blur";
import { LinearGradient } from "expo-linear-gradient";
import { Lock, TreePine, User } from "lucide-react-native";

import { RootStackParamList } from "../navigation/types";
import { acceptInvite, validateInvite } from "../services/api";
import { registerPushTokenIfAuthorized } from "../services/notifications";
import { useSession } from "../store/session";

type Props = NativeStackScreenProps<RootStackParamList, "Register">;

const EXPIRED_INVITE_ERROR = "Invitation has expired — ask your manager to resend";

function toInviteError(message: string): string {
  const normalized = message.toLowerCase();
  if (normalized.includes("invalid or expired")) {
    return EXPIRED_INVITE_ERROR;
  }
  if (normalized.includes("already registered")) {
    return "This email is already registered. Sign in instead.";
  }
  return message;
}

export function RegisterScreen({ navigation, route }: Props) {
  const { setSession } = useSession();
  const { token, email: routeEmail } = route.params;
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [email, setEmail] = useState(routeEmail);
  const [validating, setValidating] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [inviteValid, setInviteValid] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadInvite() {
      setValidating(true);
      setError("");
      try {
        const result = await validateInvite(token);
        if (cancelled) {
          return;
        }
        setEmail(result.email);
        setInviteValid(result.valid);
      } catch (err) {
        if (cancelled) {
          return;
        }
        const message = err instanceof Error ? err.message : EXPIRED_INVITE_ERROR;
        setInviteValid(false);
        setError(toInviteError(message));
      } finally {
        if (!cancelled) {
          setValidating(false);
        }
      }
    }

    void loadInvite();

    return () => {
      cancelled = true;
    };
  }, [token]);

  const canSubmit = useMemo(() => {
    return inviteValid && name.trim().length > 0 && password.length >= 8 && confirmPassword.length >= 8 && !submitting;
  }, [confirmPassword.length, inviteValid, name, password.length, submitting]);

  const handleRegister = async () => {
    if (!canSubmit) {
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    setSubmitting(true);
    setError("");
    try {
      const result = await acceptInvite({
        token,
        name: name.trim(),
        password,
      });
      await setSession(result.user, {
        access: result.access_token,
        refresh: result.refresh_token,
      });
      void registerPushTokenIfAuthorized().catch(() => undefined);
    } catch (err) {
      const message = err instanceof Error ? err.message : EXPIRED_INVITE_ERROR;
      setError(toInviteError(message));
      setSubmitting(false);
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
              <Text style={styles.title}>Join DoorDrill</Text>
              <Text style={styles.subtitle}>Complete your invited account setup</Text>
            </View>

            <BlurView intensity={40} tint="light" style={styles.glassCard}>
              {validating ? (
                <ActivityIndicator color="#144227" style={styles.validationSpinner} />
              ) : (
                <>
                  <View style={styles.emailPreview}>
                    <Text style={styles.emailLabel}>Invited Email</Text>
                    <Text style={styles.emailValue}>{email}</Text>
                  </View>

                  <View style={styles.inputGroup}>
                    <Text style={styles.label}>Full Name</Text>
                    <View style={styles.inputWrapper}>
                      <User size={18} color="#9ca3af" style={styles.inputIcon} />
                      <TextInput
                        style={styles.input}
                        value={name}
                        onChangeText={setName}
                        placeholder="Enter your full name"
                        placeholderTextColor="#6b7280"
                        autoCapitalize="words"
                        autoCorrect={false}
                        editable={inviteValid}
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
                        placeholder="Minimum 8 characters"
                        placeholderTextColor="#6b7280"
                        secureTextEntry
                        editable={inviteValid}
                        selectionColor="#516354"
                      />
                    </View>
                  </View>

                  <View style={styles.inputGroup}>
                    <Text style={styles.label}>Confirm Password</Text>
                    <View style={styles.inputWrapper}>
                      <Lock size={18} color="#9ca3af" style={styles.inputIcon} />
                      <TextInput
                        style={styles.input}
                        value={confirmPassword}
                        onChangeText={setConfirmPassword}
                        placeholder="Repeat your password"
                        placeholderTextColor="#6b7280"
                        secureTextEntry
                        editable={inviteValid}
                        selectionColor="#516354"
                      />
                    </View>
                  </View>

                  {error ? <Text style={styles.errorText}>{error}</Text> : null}

                  <Pressable
                    style={({ pressed }) => [
                      styles.button,
                      (!canSubmit || !inviteValid) && styles.buttonDisabled,
                      pressed && canSubmit && inviteValid && styles.buttonPressed,
                    ]}
                    onPress={handleRegister}
                    disabled={!canSubmit || !inviteValid}
                    accessibilityLabel="Create account from invitation"
                  >
                    {submitting ? (
                      <ActivityIndicator color="#ffffff" />
                    ) : (
                      <Text style={styles.buttonLabel}>Create Account</Text>
                    )}
                  </Pressable>

                  <Pressable
                    onPress={() => navigation.navigate("Login")}
                    style={styles.secondaryAction}
                    accessibilityLabel="Go to login screen"
                  >
                    <Text style={styles.secondaryActionText}>Already registered? Sign in</Text>
                  </Pressable>
                </>
              )}
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
  validationSpinner: {
    marginVertical: 48,
  },
  emailPreview: {
    marginBottom: 20,
    paddingVertical: 14,
    paddingHorizontal: 16,
    borderRadius: 14,
    backgroundColor: "rgba(22, 101, 52, 0.07)",
    borderWidth: 1,
    borderColor: "rgba(22, 101, 52, 0.16)",
  },
  emailLabel: {
    fontSize: 12,
    fontWeight: "600",
    color: "#6C6255",
    marginBottom: 6,
    textTransform: "uppercase",
    letterSpacing: 0.8,
  },
  emailValue: {
    fontSize: 16,
    color: "#1F1A13",
    fontWeight: "600",
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
  secondaryAction: {
    marginTop: 16,
    alignItems: "center",
  },
  secondaryActionText: {
    color: "#144227",
    fontWeight: "700",
    fontSize: 14,
  },
  errorText: {
    color: "#dc2626",
    marginBottom: 8,
    textAlign: "center",
    fontWeight: "500",
  },
});
