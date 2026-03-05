import { useState } from "react";
import { Pressable, SafeAreaView, StyleSheet, Text, TextInput, View } from "react-native";

import { colors } from "../theme/tokens";
import { useSession } from "../store/session";

export function LoginScreen() {
  const { setRepId } = useSession();
  const [repIdInput, setRepIdInput] = useState("");

  const canContinue = repIdInput.trim().length > 0;

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <Text style={styles.title}>DoorDrill Mobile</Text>
        <Text style={styles.subtitle}>Rep session bootstrap</Text>
        <TextInput
          style={styles.input}
          value={repIdInput}
          onChangeText={setRepIdInput}
          placeholder="Enter Rep ID"
          autoCapitalize="none"
          autoCorrect={false}
        />
        <Pressable
          style={[styles.button, !canContinue && styles.buttonDisabled]}
          disabled={!canContinue}
          onPress={() => setRepId(repIdInput)}
        >
          <Text style={styles.buttonLabel}>Continue</Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.bg },
  container: { flex: 1, padding: 24, justifyContent: "center", gap: 12 },
  title: { fontSize: 34, fontWeight: "700", color: colors.ink },
  subtitle: { fontSize: 16, color: colors.muted },
  input: {
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    borderRadius: 14,
    paddingHorizontal: 14,
    paddingVertical: 12
  },
  button: {
    marginTop: 8,
    backgroundColor: colors.accent,
    borderRadius: 14,
    paddingVertical: 13,
    alignItems: "center"
  },
  buttonDisabled: { opacity: 0.45 },
  buttonLabel: { color: "white", fontWeight: "700", fontSize: 16 }
});
