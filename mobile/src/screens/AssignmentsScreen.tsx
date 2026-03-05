import { SafeAreaView, StyleSheet, Text, View } from "react-native";

import { colors } from "../theme/tokens";

export function AssignmentsScreen() {
  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <Text style={styles.title}>Assignments</Text>
        <Text style={styles.subtitle}>Loading mobile assignments flow...</Text>
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
