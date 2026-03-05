import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useCallback, useEffect, useState } from "react";
import { ActivityIndicator, Pressable, SafeAreaView, StyleSheet, Text, View } from "react-native";
import { Award, Target, Zap, LogOut } from "lucide-react-native";
import { LinearGradient } from "expo-linear-gradient";
import { BlurView } from "expo-blur";

import { BottomTabParamList, RootStackParamList } from "../navigation/types";
import { fetchRepProgress } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { RepProgress } from "../types";
import { BottomTabScreenProps } from "@react-navigation/bottom-tabs";
import { CompositeScreenProps } from "@react-navigation/native";

type Props = CompositeScreenProps<
  BottomTabScreenProps<BottomTabParamList, "ProfileTab">,
  NativeStackScreenProps<RootStackParamList>
>;

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
    <LinearGradient colors={["#FDFDFD", "#F7F4EE", "#EBE5D9"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.content}>
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
                <View style={styles.statCardWrapper}>
                  <BlurView intensity={40} tint="light" style={styles.statCard}>
                    <View style={styles.statHeader}>
                      <Target size={18} color={colors.muted} />
                      <Text style={styles.statLabel}>Total Drills</Text>
                    </View>
                    <Text style={styles.statValue}>{progress.session_count}</Text>
                  </BlurView>
                </View>

                <View style={styles.statCardWrapper}>
                  <BlurView intensity={40} tint="light" style={styles.statCard}>
                    <View style={styles.statHeader}>
                      <Award size={18} color={colors.accent} />
                      <Text style={styles.statLabel}>Average Score</Text>
                    </View>
                    <Text style={[styles.statValue, { color: colors.accent }]}>
                      {progress.average_score !== null ? progress.average_score.toFixed(1) : "--"}
                    </Text>
                  </BlurView>
                </View>

                <View style={[styles.statCardWrapper, { width: "100%" }]}>
                  <BlurView intensity={40} tint="light" style={styles.statCard}>
                    <View style={styles.statHeader}>
                      <Zap size={18} color="#D97706" />
                      <Text style={styles.statLabel}>Scored Sessions</Text>
                    </View>
                    <Text style={styles.statValue}>{progress.scored_session_count}</Text>
                  </BlurView>
                </View>
              </View>
            </View>
          ) : null}

          <View style={styles.actionsContainer}>
            <Pressable style={({pressed}) => [styles.logoutButton, pressed && styles.logoutButtonPressed]} onPress={clearSession}>
              <LogOut size={18} color="#991B1B" />
              <Text style={styles.logoutText}>Sign Out</Text>
            </Pressable>
          </View>
        </View>
      </SafeAreaView>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  safeArea: { flex: 1 },
  content: { flex: 1, padding: 20 },
  avatarContainer: { alignItems: "center", marginTop: 24, marginBottom: 32 },
  avatar: {
    width: 88,
    height: 88,
    borderRadius: 44,
    backgroundColor: "rgba(74, 222, 128, 0.12)",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 16,
    borderWidth: 1,
    borderColor: "rgba(74, 222, 128, 0.3)",
  },
  avatarText: { fontSize: 32, fontWeight: "800", color: colors.accent },
  name: { fontSize: 24, fontFamily: "Poppins_800ExtraBold", color: colors.ink, marginBottom: 4 },
  role: { fontSize: 15, color: colors.muted },
  errorContainer: {
    backgroundColor: "#FEE2E2",
    borderWidth: 1,
    borderColor: "#FECACA",
    padding: 16,
    borderRadius: 14,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 20,
  },
  error: { color: "#991B1B", fontWeight: "600", flex: 1 },
  retryText: { color: "#991B1B", fontWeight: "800", textDecorationLine: "underline" },
  statsContainer: { flex: 1 },
  sectionTitle: { fontSize: 18, fontFamily: "Poppins_700Bold", color: colors.ink, marginBottom: 16 },
  statGrid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  statCardWrapper: {
    flex: 1,
    minWidth: "45%",
    borderRadius: 20,
    overflow: "hidden",
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: "rgba(255, 255, 255, 0.5)",
  },
  statCard: {
    padding: 18,
  },
  statHeader: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 12 },
  statLabel: { fontSize: 12, fontWeight: "700", color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5 },
  statValue: { fontSize: 36, fontWeight: "800", color: colors.ink },
  actionsContainer: { marginTop: "auto", gap: 12, paddingTop: 24, paddingBottom: 20 },
  logoutButton: {
    flexDirection: "row",
    gap: 8,
    paddingVertical: 16,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#FEE2E2",
    borderWidth: 1,
    borderColor: "#FECACA",
    borderRadius: 16,
  },
  logoutButtonPressed: {
    opacity: 0.7,
  },
  logoutText: { fontSize: 16, fontWeight: "700", color: "#991B1B" },
});