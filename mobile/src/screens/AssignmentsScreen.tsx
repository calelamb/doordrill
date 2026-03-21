import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View, ActivityIndicator, RefreshControl } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { ClipboardList, BookOpenCheck, Bell, ChevronRight, Zap, TrendingUp } from "lucide-react-native";
import Animated, { FadeInDown } from "react-native-reanimated";
import { BlurView } from "expo-blur";

import { AssignmentCard } from "../components/AssignmentCard";
import { BottomTabParamList } from "../navigation/types";
import { fetchRepAssignments, fetchAllScenarios, fetchRepProgress, fetchRepSessionsHistory } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { RepAssignment, RepProgress, RepSessionHistoryItem, ScenarioBrief } from "../types";
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

function wasYesterday(value: string | null | undefined): boolean {
  if (!value) return false;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return false;

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  return target.getTime() === yesterday.getTime();
}

export function AssignmentsScreen({ navigation }: Props) {
  const { repId } = useSession();
  const [assignments, setAssignments] = useState<RepAssignment[]>([]);
  const [sessionHistory, setSessionHistory] = useState<RepSessionHistoryItem[]>([]);
  const [scenarios, setScenarios] = useState<Record<string, ScenarioBrief>>({});
  const [progress, setProgress] = useState<RepProgress | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!repId) return;
    setLoading(true);
    setError(null);
    try {
      const [assignmentsRes, scenariosRes, progressRes, historyRes] = await Promise.all([
        fetchRepAssignments(repId),
        fetchAllScenarios(repId),
        fetchRepProgress(repId),
        fetchRepSessionsHistory(repId),
      ]);
      setAssignments(assignmentsRes);
      setProgress(progressRes);
      setSessionHistory(historyRes.items);
      
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

  const hasActiveSessions = useMemo(
    () => sessionHistory.some((session) => session.status === "active" || session.status === "processing"),
    [sessionHistory]
  );

  const isFirstTimer = useMemo(
    () => (progress?.completed_drills ?? 0) === 0 && !hasActiveSessions,
    [hasActiveSessions, progress?.completed_drills]
  );

  const navigateToScenarioPicker = useCallback(() => {
    navigation.navigate("ScenarioPicker", { isFirstTimer });
  }, [isFirstTimer, navigation]);

  const startDrill = useCallback(
    async (assignment: RepAssignment) => {
      if (!repId) return;
      navigation.navigate("PreSession", {
        assignmentId: assignment.id,
        scenarioId: assignment.scenario_id,
        isFirstSession: isFirstTimer,
      });
    },
    [isFirstTimer, navigation, repId]
  );

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const openAssignments = useMemo(() => {
    const open = assignments.filter((a) => a.status !== "completed");

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

    return open;
  }, [assignments]);

  const streakBanner = useMemo(() => {
    const streakDays = progress?.streak_days ?? 0;
    if (streakDays >= 7) {
      return {
        tone: "hot" as const,
        text: `🔥 ${streakDays}-day streak — you're on fire!`,
      };
    }
    if (streakDays >= 2) {
      return {
        tone: "warm" as const,
        text: `🔥 ${streakDays}-day streak — keep it going!`,
      };
    }
    if (streakDays === 0 && wasYesterday(progress?.last_scored_session_at)) {
      return {
        tone: "nudge" as const,
        text: "Drill today to start a streak",
      };
    }
    return null;
  }, [progress?.last_scored_session_at, progress?.streak_days]);

  return (
    <LinearGradient colors={["#FBF9F5", "#EFEEEA", "#E4E2DE"]} style={styles.container}>
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

          {streakBanner ? (
            <Animated.View entering={FadeInDown.delay(120).springify()} style={styles.streakBannerWrap}>
              <View
                style={[
                  styles.streakBanner,
                  streakBanner.tone === "hot" ? styles.streakBannerHot : null,
                  streakBanner.tone === "nudge" ? styles.streakBannerNudge : null,
                ]}
              >
                <Text
                  style={[
                    styles.streakBannerText,
                    streakBanner.tone === "hot" ? styles.streakBannerTextHot : null,
                    streakBanner.tone === "nudge" ? styles.streakBannerTextNudge : null,
                  ]}
                >
                  {streakBanner.text}
                </Text>
              </View>
            </Animated.View>
          ) : null}

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

            {isFirstTimer && Object.keys(scenarios).length > 0 ? (
              <Pressable
                style={({ pressed }) => [styles.firstDrillBanner, pressed && styles.firstDrillBannerPressed]}
                onPress={navigateToScenarioPicker}
                accessibilityLabel="Start your first drill"
              >
                <View style={styles.firstDrillIcon}>
                  <Zap size={22} color={colors.accent} />
                </View>
                <View style={styles.firstDrillText}>
                  <Text style={styles.firstDrillTitle}>Start Your First Drill</Text>
                  <Text style={styles.firstDrillSubtitle}>Takes 3-5 minutes. Your AI homeowner is waiting.</Text>
                </View>
                <ChevronRight size={20} color={colors.accent} />
              </Pressable>
            ) : null}

            {Object.values(scenarios).length > 0 && (
              <Pressable 
                style={({ pressed }) => [styles.quickTrainCard, pressed && styles.quickTrainCardPressed]}
                onPress={navigateToScenarioPicker}
              >
                <LinearGradient colors={["#144227", "#2D5A3D"]} style={styles.quickTrainGradient} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }}>
                  <View style={styles.quickTrainIcon}>
                    <Zap size={24} color="#fff" fill="#fff" />
                  </View>
                  <View style={styles.quickTrainTextContainer}>
                    <Text style={styles.quickTrainTitle}>{isFirstTimer ? "Choose Your First Drill" : "Open Practice"}</Text>
                    <Text style={styles.quickTrainSubtitle}>
                      {isFirstTimer ? "Pick a beginner-friendly conversation to get started" : "Start an unassigned practice session anytime"}
                    </Text>
                  </View>
                </LinearGradient>
              </Pressable>
            )}

            <BlurView intensity={40} tint="light" style={styles.assignmentSectionIntro}>
              <View style={styles.assignmentSectionIcon}>
                <ClipboardList size={18} color={colors.accent} />
              </View>
              <View style={styles.assignmentSectionCopy}>
                <Text style={styles.assignmentSectionTitle}>Manager Assignments</Text>
                <Text style={styles.assignmentSectionSubtitle}>
                  Assigned to you by your manager. Completed drills stay in History.
                </Text>
              </View>
              <View style={styles.assignmentCountChip}>
                <Text style={styles.assignmentCountText}>{openAssignments.length}</Text>
              </View>
            </BlurView>

            {loading && assignments.length === 0 ? (
              <ActivityIndicator size="large" color={colors.accent} style={{ marginTop: 40 }} />
            ) : (
              <>
                {openAssignments.length === 0 ? (
                  <View style={styles.emptyState}>
                    <View style={styles.emptyIconContainer}>
                      <ClipboardList size={32} color={colors.accent} />
                    </View>
                    <Text style={styles.emptyText}>No manager assignments right now.</Text>
                    <Text style={styles.emptySubtext}>
                      When your manager assigns a drill, it will show up here with its due date and score target. Use Open Practice to keep training in the meantime.
                    </Text>
                  </View>
                ) : null}

                {openAssignments.map((assignment) => (
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
  streakBannerWrap: {
    marginBottom: 4,
  },
  streakBanner: {
    alignSelf: "flex-start",
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 10,
    backgroundColor: colors.warningSoft,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(180, 83, 9, 0.24)",
  },
  streakBannerHot: {
    backgroundColor: "rgba(245, 158, 11, 0.18)",
    borderColor: "rgba(245, 158, 11, 0.32)",
  },
  streakBannerNudge: {
    backgroundColor: "rgba(180, 83, 9, 0.08)",
    borderColor: "rgba(180, 83, 9, 0.18)",
  },
  streakBannerText: {
    color: colors.warning,
    fontSize: 13,
    fontFamily: "Poppins_700Bold",
  },
  streakBannerTextHot: {
    color: "#9A3412",
  },
  streakBannerTextNudge: {
    color: colors.muted,
  },
  statsRow: {
    flexDirection: "row",
    gap: 12,
    marginBottom: 8,
  },
  firstDrillBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    padding: 18,
    borderRadius: 22,
    backgroundColor: "rgba(255, 255, 255, 0.72)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(22, 101, 52, 0.16)",
    marginBottom: 6,
  },
  firstDrillBannerPressed: {
    opacity: 0.94,
    transform: [{ scale: 0.988 }],
  },
  firstDrillIcon: {
    width: 48,
    height: 48,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.accentSoft,
  },
  firstDrillText: {
    flex: 1,
  },
  firstDrillTitle: {
    fontSize: 17,
    fontFamily: "Poppins_700Bold",
    color: colors.ink,
    marginBottom: 2,
  },
  firstDrillSubtitle: {
    fontSize: 13,
    lineHeight: 19,
    color: colors.muted,
    fontFamily: "Inter_400Regular",
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
  assignmentSectionIntro: {
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
    paddingHorizontal: 18,
    paddingVertical: 16,
    borderRadius: 22,
    backgroundColor: "rgba(255, 255, 255, 0.62)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    marginTop: 8,
    marginBottom: 4,
  },
  assignmentSectionIcon: {
    width: 40,
    height: 40,
    borderRadius: 14,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.accentSoft,
  },
  assignmentSectionCopy: {
    flex: 1,
  },
  assignmentSectionTitle: {
    fontSize: 17,
    fontFamily: "Poppins_700Bold",
    color: colors.ink,
    marginBottom: 2,
  },
  assignmentSectionSubtitle: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.muted,
    fontFamily: "Inter_400Regular",
  },
  assignmentCountChip: {
    minWidth: 34,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(22, 101, 52, 0.12)",
    borderWidth: 1,
    borderColor: "rgba(22, 101, 52, 0.2)",
  },
  assignmentCountText: {
    fontSize: 13,
    fontFamily: "Poppins_700Bold",
    color: colors.accent,
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
  emptyText: {
    fontSize: 20,
    fontFamily: "Poppins_700Bold",
    color: colors.ink,
    textAlign: "center",
  },
  emptySubtext: {
    fontSize: 14,
    lineHeight: 20,
    color: "rgba(108, 98, 85, 0.8)",
    textAlign: "center",
    paddingHorizontal: 12,
    maxWidth: 320,
  },
});
