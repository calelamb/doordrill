import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View, ActivityIndicator, RefreshControl } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { ClipboardList, BookOpenCheck, TreePine } from "lucide-react-native";

import { AssignmentCard } from "../components/AssignmentCard";
import { BottomTabParamList } from "../navigation/types";
import { fetchRepAssignments, fetchAllScenarios } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { RepAssignment, ScenarioBrief } from "../types";
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
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!repId) return;
    setLoading(true);
    setError(null);
    try {
      const [assignmentsRes, scenariosRes] = await Promise.all([
        fetchRepAssignments(repId),
        fetchAllScenarios(repId)
      ]);
      setAssignments(assignmentsRes);
      
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
            <View style={styles.headerIconContainer}>
              <TreePine size={32} color={colors.accent} strokeWidth={2.5} />
            </View>
            <Text style={styles.title}>Your Drills</Text>
            <Text style={styles.subtitle}>Open a brief, then jump straight in.</Text>
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
            {loading && assignments.length === 0 ? (
              <ActivityIndicator size="large" color={colors.accent} style={{ marginTop: 40 }} />
            ) : (
              <>
                {sortedAssignments.open.length === 0 && sortedAssignments.completed.length === 0 ? (
                  <View style={styles.emptyState}>
                    <View style={styles.emptyIconContainer}>
                      <ClipboardList size={32} color={colors.accent} />
                    </View>
                    <Text style={styles.emptyText}>No drills yet.</Text>
                    <Text style={styles.emptySubtext}>Your manager will assign scenarios here.</Text>
                    
                    {Object.values(scenarios).length > 0 && (
                      <Pressable 
                        style={styles.practiceBtn}
                        onPress={() => {
                          const firstScenarioId = Object.keys(scenarios)[0];
                          if (firstScenarioId) {
                            navigation.navigate("PreSession", {
                              scenarioId: firstScenarioId,
                            });
                          }
                        }}
                      >
                        <Text style={styles.practiceBtnText}>Practice Now</Text>
                      </Pressable>
                    )}
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
  headerRow: { alignItems: "center", marginBottom: 16, marginTop: 16 },
  headerIconContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: "rgba(74, 222, 128, 0.12)",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 12,
    borderWidth: 1,
    borderColor: "rgba(74, 222, 128, 0.3)"
  },
  title: { fontSize: 32, fontFamily: "Poppins_800ExtraBold", color: colors.ink, marginBottom: 4, textAlign: "center" },
  subtitle: { color: colors.muted, fontSize: 16, textAlign: "center" },
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
  list: { gap: 16, paddingBottom: 40 },
  emptyState: { flex: 1, alignItems: "center", justifyContent: "center", marginTop: 80, gap: 12 },
  emptyIconContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.accentSoft,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 8,
    borderWidth: 1,
    borderColor: "rgba(74, 222, 128, 0.2)"
  },
  emptyText: { fontSize: 20, fontFamily: "Poppins_700Bold", color: colors.ink },
  emptySubtext: { fontSize: 15, color: colors.muted, textAlign: "center" },
  practiceBtn: {
    marginTop: 24,
    backgroundColor: colors.accent,
    paddingHorizontal: 32,
    paddingVertical: 16,
    borderRadius: 24, // Apple pill shape
    shadowColor: colors.accent,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.25,
    shadowRadius: 16,
    elevation: 4,
  },
  practiceBtnText: {
    color: "#fff",
    fontSize: 16,
    fontFamily: "Poppins_700Bold",
  },
  completedSection: {
    marginTop: 32,
    gap: 16,
  },
  completedHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    gap: 8,
    marginBottom: 12,
  },
  sectionTitle: {
    fontSize: 18,
    fontFamily: "Poppins_700Bold",
    color: colors.ink,
  }
});
