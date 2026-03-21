import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useEffect, useState } from "react";
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
import { Lock, Mail, TreePine } from "lucide-react-native";

import { RootStackParamList } from "../navigation/types";
import { requestPasswordReset, resetPassword } from "../services/api";

type Props = NativeStackScreenProps<RootStackParamList, "ForgotPassword">;

function normalizeResetError(message: string): string {
  if (message.toLowerCase().includes("invalid or expired")) {
    return "Reset link is invalid or expired";
  }
  return message;
}

export function ForgotPasswordScreen({ navigation, route }: Props) {
  const resetToken = typeof route.params?.token === "string" ? route.params.token.trim() : "";
  const isResetState = resetToken.length > 0;
  const [email, setEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  useEffect(() => {
    setError("");
    setSuccess("");
    setNewPassword("");
    setConfirmPassword("");
  }, [resetToken]);

  const canRequest = email.trim().length > 0 && !submitting;
  const canReset = newPassword.length >= 8 && confirmPassword.length >= 8 && !submitting;

  const handleRequestReset = async () => {
    if (!canRequest) {
      return;
    }

    setSubmitting(true);
    setError("");
    setSuccess("");
    try {
      await requestPasswordReset(email.trim().toLowerCase());
      setSuccess("Check your email for a reset link");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unable to send reset link";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  };

  const handleResetPassword = async () => {
    if (!canReset) {
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    setSubmitting(true);
    setError("");
    setSuccess("");
    try {
      await resetPassword(resetToken, newPassword);
      navigation.replace("Login", {
        message: "Password updated. Sign in with your new password.",
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unable to reset password";
      setError(normalizeResetError(message));
      setSubmitting(false);
    }
  };

  return (
    <LinearGradient colors={["#FBF9F5", "#EFEEEA", "#E4E2DE"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : "height"} style={styles.keyboardView}>
          <View style={styles.content}>
            <View style={styles.brandContainer}>
              <View style={styles.iconWrapper}>
                <TreePine size={32} color="#a1d2ad" strokeWidth={2.5} />
              </View>
              <Text style={styles.title}>{isResetState ? "Set New Password" : "Forgot Password"}</Text>
              <Text style={styles.subtitle}>
                {isResetState ? "Choose a new password for your account" : "Request a reset link for your account"}
              </Text>
            </View>

            <BlurView intensity={40} tint="light" style={styles.glassCard}>
              {!isResetState ? (
                <>
                  <View style={styles.inputGroup}>
                    <Text style={styles.label}>Email</Text>
                    <View style={styles.inputWrapper}>
                      <Mail size={18} color="#9ca3af" style={styles.inputIcon} />
                      <TextInput
                        style={styles.input}
                        value={email}
                        onChangeText={setEmail}
                        placeholder="Enter your email"
                        placeholderTextColor="#6b7280"
                        autoCapitalize="none"
                        autoCorrect={false}
                        autoComplete="email"
                        keyboardType="email-address"
                        textContentType="emailAddress"
                        selectionColor="#516354"
                      />
                    </View>
                  </View>

                  {success ? <Text style={styles.successText}>{success}</Text> : null}
                  {error ? <Text style={styles.errorText}>{error}</Text> : null}

                  <Pressable
                    style={({ pressed }) => [
                      styles.button,
                      !canRequest && styles.buttonDisabled,
                      pressed && canRequest && styles.buttonPressed,
                    ]}
                    disabled={!canRequest}
                    onPress={handleRequestReset}
                    accessibilityLabel="Send password reset link"
                  >
                    {submitting ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.buttonLabel}>Send Reset Link</Text>}
                  </Pressable>
                </>
              ) : (
                <>
                  <View style={styles.inputGroup}>
                    <Text style={styles.label}>New Password</Text>
                    <View style={styles.inputWrapper}>
                      <Lock size={18} color="#9ca3af" style={styles.inputIcon} />
                      <TextInput
                        style={styles.input}
                        value={newPassword}
                        onChangeText={setNewPassword}
                        placeholder="Minimum 8 characters"
                        placeholderTextColor="#6b7280"
                        secureTextEntry
                        autoCapitalize="none"
                        autoCorrect={false}
                        autoComplete="new-password"
                        textContentType="newPassword"
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
                        placeholder="Repeat your new password"
                        placeholderTextColor="#6b7280"
                        secureTextEntry
                        autoCapitalize="none"
                        autoCorrect={false}
                        autoComplete="new-password"
                        textContentType="newPassword"
                        selectionColor="#516354"
                      />
                    </View>
                  </View>

                  {error ? <Text style={styles.errorText}>{error}</Text> : null}

                  <Pressable
                    style={({ pressed }) => [
                      styles.button,
                      !canReset && styles.buttonDisabled,
                      pressed && canReset && styles.buttonPressed,
                    ]}
                    disabled={!canReset}
                    onPress={handleResetPassword}
                    accessibilityLabel="Set a new password"
                  >
                    {submitting ? <ActivityIndicator color="#ffffff" /> : <Text style={styles.buttonLabel}>Set New Password</Text>}
                  </Pressable>
                </>
              )}

              <Pressable
                onPress={() => navigation.navigate("Login")}
                style={styles.secondaryAction}
                accessibilityLabel="Go to login screen"
              >
                <Text style={styles.secondaryActionText}>Back to Sign In</Text>
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
    textAlign: "center",
  },
  subtitle: {
    fontSize: 16,
    color: "#6C6255",
    fontWeight: "400",
    letterSpacing: 0.2,
    textAlign: "center",
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
  secondaryAction: {
    marginTop: 20,
    alignItems: "center",
  },
  secondaryActionText: {
    color: "#144227",
    fontWeight: "700",
    fontSize: 15,
  },
  successText: {
    color: "#144227",
    marginBottom: 16,
    textAlign: "center",
    fontWeight: "600",
  },
  errorText: {
    color: "#dc2626",
    marginBottom: 16,
    textAlign: "center",
    fontWeight: "500",
  },
});
