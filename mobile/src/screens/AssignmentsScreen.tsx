import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View, ActivityIndicator, RefreshControl } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { ClipboardList, BookOpenCheck, TreePine, Bell, Zap, TrendingUp } from "lucide-react-native";
import { BlurView } from "expo-blur";

import { AssignmentCard } from "../components/AssignmentCard";
import { BottomTabParamList } from "../navigation/types";
import { fetchRepAssignments, fetchAllScenarios, fetchRepProgress } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { RepAssignment, ScenarioBrief, RepProgress } from "../types";
import { BottomTabScreenProps } from "@react-navigation/bottom-tabs";
import { CompositeScreenProps } from "@react-navigation/native";
import { RootStackParamList } from "../navigation/types";

type Props = CompositeScreenProps<
  BottomTabScreenProps<BottomTabParamList, "AssignmentsTab">,
  NativeStackScreenProps<RootStackParamList>
>;

function isDueSoon(dueAt: string | null): boolean {
  if (!dueAt) return false;
  const dueMs = new Date(dueAt).getTime();
  if (Number.isNaN(dueMs)) return false;
  const now = Date.now();
  return dueMs > now && dueMs - now <= 1000 * 60 * 60 * 48;
}

function isPastDue(dueAt: string | null): boolean {
  if (!dueAt) return false;
  const dueMs = new Date(dueAt).getTime();
  if (Number.isNaN(dueMs)) return false;
  return dueMs < Date.now();
}

export function AssignmentsScreen({ navigation }: Props) {
  const { repId } = useSession();
  const [assignments, setAssignments] = useState<RepAssignment[]>([]);
  const [scenarios, setScenarios] = useState<Record<string, ScenarioBrief>>({});
  const [progress, setProgress] = useState<RepProgress | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!repId) return;
    setLoading(true);
    setError(null);
    try {
      const [assignmentsRes, scenariosRes, progressRes] = await Promise.all([
        fetchRepAssignments(repId),
        fetchAllScenarios(repId),
        fetchRepProgress(repId)
      ]);
      setAssignments(assignmentsRes);
      setProgress(progressRes);
      
      const scenarioMap: Record<string, ScenarioBrief> = {};
      for (const sc of scenariosRes) {
        scenarioMap[sc.id] = sc;
      }
      setScenarios(scenarioMap);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setLoading(false);
    }
  }, [repId]);

  const startDrill = useCallback(
    async (assignment: RepAssignment) => {
      if (!repId) return;
      navigation.navigate("PreSession", {
        assignmentId: assignment.id,
        scenarioId: assignment.scenario_id,
      });
    },
    [navigation, repId]
  );

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const sortedAssignments = useMemo(() => {
    const open = assignments.filter((a) => a.status !== "completed");
    const completed = assignments.filter((a) => a.status === "completed");

    // Sort open: past due first, then closest due date, then no due date
    open.sort((a, b) => {
      const aPast = isPastDue(a.due_at);
      const bPast = isPastDue(b.due_at);
      if (aPast && !bPast) return -1;
      if (!aPast && bPast) return 1;

      if (a.due_at && b.due_at) {
        return new Date(a.due_at).getTime() - new Date(b.due_at).getTime();
      }
      if (a.due_at) return -1;
      if (b.due_at) return 1;
      return 0;
    });

    return { open, completed };
  }, [assignments]);

  return (
    <LinearGradient colors={["#FDFDFD", "#F7F4EE", "#EBE5D9"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.content}>
          <View style={styles.headerRow}>
            <View style={styles.headerTextContainer}>
              <Text style={styles.greeting} numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.6}>
                {progress?.rep_name ? `Good morning, ${progress.rep_name.split(' ')[0]}!` : "Good morning!"}
              </Text>
              <Text style={styles.subtitle}>Let's hit today's targets.</Text>
            </View>
            <Pressable style={styles.bellButton}>
              <Bell size={24} color={colors.ink} />
            </Pressable>
          </View>

          {error ? (
            <View style={styles.errorContainer}>
              <Text style={styles.error}>{error}</Text>
              <Pressable onPress={loadData}>
                <Text style={styles.retryText}>Retry</Text>
              </Pressable>
            </View>
          ) : null}

          <ScrollView 
            contentContainerStyle={styles.list}
            showsVerticalScrollIndicator={false}
            refreshControl={
              <RefreshControl refreshing={loading && assignments.length > 0} onRefresh={loadData} colors={[colors.accent]} tintColor={colors.accent} />
            }
          >
            <View style={styles.statsRow}>
              <BlurView intensity={40} tint="light" style={styles.statCard}>
                <TrendingUp size={24} color={colors.accent} style={styles.statIcon} />
                <View>
                  <Text style={styles.statValue}>{progress?.average_score?.toFixed(1) ?? "0.0"}</Text>
                  <Text style={styles.statLabel}>Avg Score</Text>
                </View>
              </BlurView>
              <BlurView intensity={40} tint="light" style={styles.statCard}>
                <BookOpenCheck size={24} color={colors.accent} style={styles.statIcon} />
                <View>
                  <Text style={styles.statValue}>{progress?.completed_drills ?? 0}</Text>
                  <Text style={styles.statLabel}>Completed</Text>
                </View>
              </BlurView>
            </View>

            {Object.values(scenarios).length > 0 && (
              <Pressable 
                style={({ pressed }) => [styles.quickTrainCard, pressed && styles.quickTrainCardPressed]}
                onPress={() => {
                  const firstScenarioId = Object.keys(scenarios)[0];
                  if (firstScenarioId) {
                    navigation.navigate("PreSession", { scenarioId: firstScenarioId });
                  }
                }}
              >
                <LinearGradient colors={["#166534", "#15803d"]} style={styles.quickTrainGradient} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}>
                  <View style={styles.quickTrainIcon}>
                    <Zap size={24} color="#fff" fill="#fff" />
                  </View>
                  <View style={styles.quickTrainTextContainer}>
                    <Text style={styles.quickTrainTitle}>Quick Train</Text>
                    <Text style={styles.quickTrainSubtitle}>Start an open practice session</Text>
                  </View>
                </LinearGradient>
              </Pressable>
            )}

            <Text style={styles.sectionHeader}>Up Next</Text>

            {loading && assignments.length === 0 ? (
              <ActivityIndicator size="large" color={colors.accent} style={{ marginTop: 40 }} />
            ) : (
              <>
                {sortedAssignments.open.length === 0 && sortedAssignments.completed.length === 0 ? (
                  <View style={styles.emptyState}>
                    <View style={styles.emptyIconContainer}>
                      <ClipboardList size={32} color={colors.accent} />
                    </View>
                    <Text style={styles.emptyText}>No drills assigned.</Text>
                    <Text style={styles.emptySubtext}>Your manager will assign scenarios here. Use Quick Train to practice freely.</Text>
                  </View>
                ) : null}

                {sortedAssignments.open.map((assignment) => (
                  <AssignmentCard
                    key={assignment.id}
                    assignment={assignment}
                    scenario={scenarios[assignment.scenario_id]}
                    disabled={loading}
                    onStart={() => {
                      void startDrill(assignment);
                    }}
                  />
                ))}

                {sortedAssignments.completed.length > 0 && (
                  <View style={styles.completedSection}>
                    <View style={styles.completedHeader}>
                      <BookOpenCheck size={18} color={colors.success} />
                      <Text style={styles.sectionTitle}>Completed Drills</Text>
                    </View>
                    {sortedAssignments.completed.map((assignment) => (
                      <AssignmentCard
                        key={assignment.id}
                        assignment={assignment}
                        scenario={scenarios[assignment.scenario_id]}
                        disabled={loading}
                        onStart={() => {
                          void startDrill(assignment);
                        }}
                      />
                    ))}
                  </View>
                )}
              </>
            )}
          </ScrollView>
        </View>
      </SafeAreaView>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  safeArea: { flex: 1 },
  content: { flex: 1, padding: 20, gap: 16 },
  headerRow: { 
    flexDirection: "row", 
    justifyContent: "space-between", 
    alignItems: "center", 
    marginBottom: 16, 
    marginTop: 16,
  },
  headerTextContainer: {
    flex: 1,
    marginRight: 16,
  },
  greeting: { 
    fontSize: 26, 
    fontFamily: "Poppins_800ExtraBold", 
    color: colors.ink, 
    marginBottom: 2 
  },
  subtitle: { 
    color: colors.muted, 
    fontSize: 15,
    fontWeight: "500" 
  },
  bellButton: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: "rgba(255, 255, 255, 0.6)",
    alignItems: "center",
    justifyContent: "center",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
  },
  statsRow: {
    flexDirection: "row",
    gap: 12,
    marginBottom: 8,
  },
  statCard: {
    flex: 1,
    padding: 16,
    borderRadius: 20,
    backgroundColor: "rgba(255, 255, 255, 0.6)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  statIcon: {
    backgroundColor: colors.accentSoft,
    padding: 8,
    borderRadius: 12,
    overflow: "hidden",
  },
  statValue: {
    fontSize: 20,
    fontFamily: "Poppins_800ExtraBold",
    color: colors.ink,
  },
  statLabel: {
    fontSize: 12,
    fontWeight: "700",
    color: colors.muted,
    textTransform: "uppercase",
  },
  quickTrainCard: {
    borderRadius: 24,
    overflow: "hidden",
    shadowColor: colors.accent,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.25,
    shadowRadius: 16,
    elevation: 4,
    marginBottom: 8,
  },
  quickTrainCardPressed: {
    opacity: 0.9,
    transform: [{ scale: 0.98 }],
  },
  quickTrainGradient: {
    flexDirection: "row",
    alignItems: "center",
    padding: 20,
    gap: 16,
  },
  quickTrainIcon: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: "rgba(255, 255, 255, 0.2)",
    alignItems: "center",
    justifyContent: "center",
  },
  quickTrainTextContainer: {
    flex: 1,
  },
  quickTrainTitle: {
    color: "#fff",
    fontSize: 18,
    fontFamily: "Poppins_800ExtraBold",
    marginBottom: 2,
  },
  quickTrainSubtitle: {
    color: "rgba(255, 255, 255, 0.8)",
    fontSize: 14,
    fontWeight: "500",
  },
  sectionHeader: {
    fontSize: 14,
    fontWeight: "700",
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 1,
    marginTop: 8,
    marginBottom: 4,
  },
  errorContainer: {
    backgroundColor: "#FEE2E2",
    borderWidth: 1,
    borderColor: "#FECACA",
    padding: 14,
    borderRadius: 14,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center"
  },
  error: { color: "#991B1B", fontWeight: "600", flex: 1 },
  retryText: { color: "#991B1B", fontWeight: "800", textDecorationLine: "underline" },
  list: { gap: 12, paddingBottom: 40 },
  emptyState: { flex: 1, alignItems: "center", justifyContent: "center", marginTop: 40, gap: 12 },
  emptyIconContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.accentSoft,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 8,
    borderWidth: 1,
    borderColor: "rgba(22, 101, 52, 0.2)"
  },
  emptyText: { fontSize: 20, fontFamily: "Poppins_700Bold", color: colors.ink },
  emptySubtext: { fontSize: 15, color: colors.muted, textAlign: "center", paddingHorizontal: 20 },
  completedSection: {
    marginTop: 24,
    gap: 12,
  },
  completedHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    marginBottom: 8,
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: "700",
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 1,
  }
});
