import { useState } from "react";
import { Pressable, SafeAreaView, StyleSheet, Text, TextInput, View, KeyboardAvoidingView, Platform, ActivityIndicator } from "react-native";
import { BlurView } from "expo-blur";
import { LinearGradient } from "expo-linear-gradient";
import { TreePine, Mail, Lock } from "lucide-react-native";

import { useSession } from "../store/session";

export function LoginScreen() {
  const { setRepId } = useSession();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);

  const canContinue = email.trim().length > 0 && password.trim().length > 0 && !loading;

  const handleLogin = () => {
    setLoading(true);
    setTimeout(() => {
      // Mock log in flow mapping the email explicitly back to the dummy API state wrapper
      const mockRepId = email.includes("@") ? email.split("@")[0] : email;
      setRepId(mockRepId);
    }, 600);
  };

  return (
    <LinearGradient colors={["#173322", "#0d1f14", "#050a06"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <KeyboardAvoidingView
          behavior={Platform.OS === "ios" ? "padding" : "height"}
          style={styles.keyboardView}
        >
          <View style={styles.content}>
            <View style={styles.brandContainer}>
              <View style={styles.iconWrapper}>
                <TreePine size={32} color="#4ade80" strokeWidth={2.5} />
              </View>
              <Text style={styles.title}>DoorDrill</Text>
              <Text style={styles.subtitle}>Sign in to your account</Text>
            </View>

            <BlurView intensity={30} tint="dark" style={styles.glassCard}>
              <View style={styles.inputGroup}>
                <Text style={styles.label}>Email Address</Text>
                <View style={styles.inputWrapper}>
                  <Mail size={18} color="#9ca3af" style={styles.inputIcon} />
                  <TextInput
                    style={styles.input}
                    value={email}
                    onChangeText={setEmail}
                    placeholder="Enter your email or Rep ID"
                    placeholderTextColor="#6b7280"
                    autoCapitalize="none"
                    autoCorrect={false}
                    keyboardType="email-address"
                    selectionColor="#22c55e"
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
                    selectionColor="#22c55e"
                  />
                </View>
              </View>

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
    backgroundColor: "rgba(74, 222, 128, 0.12)",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 20,
    borderWidth: 1,
    borderColor: "rgba(74, 222, 128, 0.25)",
  },
  title: {
    fontFamily: "Poppins_800ExtraBold",
    fontSize: 34,
    fontWeight: "800",
    color: "#ffffff",
    letterSpacing: 0.5,
    marginBottom: 8,
  },
  subtitle: {
    fontSize: 16,
    color: "#9ca3af",
    fontWeight: "400",
    letterSpacing: 0.2,
  },
  glassCard: {
    borderRadius: 24,
    padding: 24,
    borderWidth: 1,
    borderColor: "rgba(255, 255, 255, 0.1)",
    overflow: "hidden",
    backgroundColor: "rgba(0, 0, 0, 0.25)",
  },
  inputGroup: {
    marginBottom: 20,
  },
  label: {
    fontSize: 12,
    fontWeight: "600",
    color: "#e5e7eb",
    marginBottom: 8,
    textTransform: "uppercase",
    letterSpacing: 0.8,
  },
  inputWrapper: {
    flexDirection: "row",
    alignItems: "center",
    backgroundColor: "rgba(0, 0, 0, 0.3)",
    borderWidth: 1,
    borderColor: "rgba(255, 255, 255, 0.08)",
    borderRadius: 14,
    height: 54,
    paddingHorizontal: 16,
  },
  inputIcon: {
    marginRight: 12,
  },
  input: {
    flex: 1,
    color: "#ffffff",
    fontSize: 16,
    height: "100%",
  },
  button: {
    marginTop: 12,
    backgroundColor: "#16a34a",
    borderRadius: 14,
    height: 56,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#16a34a",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 10,
    elevation: 4,
    borderWidth: 1,
    borderColor: "rgba(255, 255, 255, 0.1)",
  },
  buttonDisabled: {
    backgroundColor: "rgba(22, 163, 74, 0.4)",
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
});
