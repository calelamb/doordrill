import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, SafeAreaView, StyleSheet, Text, View } from "react-native";
import { Award, Target, Zap } from "lucide-react-native";

import { RootStackParamList } from "../navigation/types";
import { fetchRepProgress } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { RepProgress } from "../types";

type Props = NativeStackScreenProps<RootStackParamList, "Profile">;

export function ProfileScreen({ navigation }: Props) {
  const { repId, clearSession } = useSession();
  const [progress, setProgress] = useState<RepProgress | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadProgress = useCallback(async () => {
    if (!repId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await fetchRepProgress(repId);
      setProgress(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load progress");
    } finally {
      setLoading(false);
    }
  }, [repId]);

  useEffect(() => {
    void loadProgress();
  }, [loadProgress]);

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <View style={styles.avatarContainer}>
          <View style={styles.avatar}>
            <Text style={styles.avatarText}>{repId?.slice(0, 2).toUpperCase()}</Text>
          </View>
          <Text style={styles.name}>{repId}</Text>
          <Text style={styles.role}>Sales Representative</Text>
        </View>

        {loading && !progress ? (
          <ActivityIndicator size="large" color={colors.accent} style={{ marginTop: 40 }} />
        ) : error ? (
          <View style={styles.errorContainer}>
            <Text style={styles.error}>{error}</Text>
            <Pressable onPress={loadProgress}>
              <Text style={styles.retryText}>Retry</Text>
            </Pressable>
          </View>
        ) : progress ? (
          <View style={styles.statsContainer}>
            <Text style={styles.sectionTitle}>Your Progress</Text>
            
            <View style={styles.statGrid}>
              <View style={styles.statCard}>
                <View style={styles.statHeader}>
                  <Target size={18} color={colors.muted} />
                  <Text style={styles.statLabel}>Total Drills</Text>
                </View>
                <Text style={styles.statValue}>{progress.session_count}</Text>
              </View>

              <View style={styles.statCard}>
                <View style={styles.statHeader}>
                  <Award size={18} color={colors.accent} />
                  <Text style={styles.statLabel}>Average Score</Text>
                </View>
                <Text style={[styles.statValue, { color: colors.accent }]}>
                  {progress.average_score !== null ? progress.average_score.toFixed(1) : "--"}
                </Text>
              </View>

              <View style={[styles.statCard, { width: "100%" }]}>
                <View style={styles.statHeader}>
                  <Zap size={18} color="#D97706" />
                  <Text style={styles.statLabel}>Scored Sessions</Text>
                </View>
                <Text style={styles.statValue}>{progress.scored_session_count}</Text>
              </View>
            </View>
          </View>
        ) : null}

        <View style={styles.actionsContainer}>
          <Pressable style={styles.actionButton} onPress={() => navigation.navigate("History")}>
            <Text style={styles.actionButtonText}>View Drill History</Text>
          </Pressable>
          
          <Pressable style={styles.logoutButton} onPress={clearSession}>
            <Text style={styles.logoutText}>Sign Out</Text>
          </Pressable>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.bg },
  container: { flex: 1, padding: 20 },
  avatarContainer: { alignItems: "center", marginTop: 24, marginBottom: 32 },
  avatar: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: colors.accentSoft,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 16,
    borderWidth: 2,
    borderColor: colors.accent,
  },
  avatarText: { fontSize: 32, fontWeight: "800", color: colors.accent },
  name: { fontSize: 24, fontWeight: "800", color: colors.ink, marginBottom: 4 },
  role: { fontSize: 15, color: colors.muted },
  errorContainer: {
    backgroundColor: "#FEE2E2",
    padding: 16,
    borderRadius: 12,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 20,
  },
  error: { color: "#991B1B", fontWeight: "600", flex: 1 },
  retryText: { color: "#991B1B", fontWeight: "800", textDecorationLine: "underline" },
  statsContainer: { flex: 1 },
  sectionTitle: { fontSize: 18, fontWeight: "800", color: colors.ink, marginBottom: 16 },
  statGrid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  statCard: {
    flex: 1,
    minWidth: "45%",
    backgroundColor: colors.panel,
    borderRadius: 16,
    padding: 16,
    borderWidth: 1,
    borderColor: colors.line,
  },
  statHeader: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 12 },
  statLabel: { fontSize: 13, fontWeight: "700", color: colors.muted, textTransform: "uppercase" },
  statValue: { fontSize: 32, fontWeight: "800", color: colors.ink },
  actionsContainer: { marginTop: "auto", gap: 12, paddingTop: 24 },
  actionButton: {
    backgroundColor: colors.panel,
    borderWidth: 1,
    borderColor: colors.line,
    paddingVertical: 16,
    borderRadius: 14,
    alignItems: "center",
  },
  actionButtonText: { fontSize: 16, fontWeight: "700", color: colors.ink },
  logoutButton: {
    paddingVertical: 16,
    alignItems: "center",
  },
  logoutText: { fontSize: 16, fontWeight: "700", color: colors.accent },
});