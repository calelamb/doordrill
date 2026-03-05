import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View, ActivityIndicator, RefreshControl } from "react-native";

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
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <View style={styles.headerRow}>
          <View>
            <Text style={styles.title}>Your Drills</Text>
            <Text style={styles.subtitle}>Open a brief, then jump straight in.</Text>
          </View>
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
                  <Text style={styles.emptyText}>No drills yet.</Text>
                  <Text style={styles.emptySubtext}>Your manager will assign scenarios here.</Text>
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
                  <Text style={styles.sectionTitle}>Completed Drills</Text>
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
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.bg },
  container: { flex: 1, padding: 20, gap: 16 },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 },
  title: { fontSize: 32, fontFamily: "Poppins_800ExtraBold", color: colors.ink, marginBottom: 4 },
  subtitle: { color: colors.muted, fontSize: 15 },
  errorContainer: {
    backgroundColor: "#FEE2E2",
    padding: 12,
    borderRadius: 12,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center"
  },
  error: { color: "#991B1B", fontWeight: "600", flex: 1 },
  retryText: { color: "#991B1B", fontWeight: "800", textDecorationLine: "underline" },
  list: { gap: 16, paddingBottom: 20 },
  emptyState: { flex: 1, alignItems: "center", justifyContent: "center", marginTop: 60, gap: 8 },
  emptyText: { fontSize: 18, fontWeight: "700", color: colors.ink },
  emptySubtext: { fontSize: 14, color: colors.muted },
  completedSection: {
    marginTop: 24,
    gap: 16,
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: "800",
    color: colors.ink,
    marginTop: 8,
  }
});
