import { SafeAreaView, StyleSheet, Text, View } from "react-native";

import { colors } from "../theme/tokens";

export function ScoreScreen() {
  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <Text style={styles.title}>Scorecard</Text>
        <Text style={styles.subtitle}>Session feedback will appear here.</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.bg },
  container: { flex: 1, padding: 20, gap: 8 },
  title: { fontSize: 28, fontWeight: "700", color: colors.ink },
  subtitle: { color: colors.muted }
});
