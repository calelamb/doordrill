import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View } from "react-native";

import { AssignmentCard } from "../components/AssignmentCard";
import { RootStackParamList } from "../navigation/types";
import { fetchRepAssignments } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { RepAssignment } from "../types";

type Props = NativeStackScreenProps<RootStackParamList, "Assignments">;
type AssignmentFilter = "all" | "open" | "due_soon" | "completed";

function isDueSoon(dueAt: string | null): boolean {
  if (!dueAt) {
    return false;
  }
  const dueMs = new Date(dueAt).getTime();
  if (Number.isNaN(dueMs)) {
    return false;
  }
  const now = Date.now();
  return dueMs > now && dueMs - now <= 1000 * 60 * 60 * 48;
}

function filterAssignments(assignments: RepAssignment[], filter: AssignmentFilter): RepAssignment[] {
  if (filter === "all") {
    return assignments;
  }
  if (filter === "completed") {
    return assignments.filter((assignment) => assignment.status === "completed");
  }
  if (filter === "due_soon") {
    return assignments.filter((assignment) => assignment.status !== "completed" && isDueSoon(assignment.due_at));
  }
  return assignments.filter((assignment) => assignment.status !== "completed");
}

export function AssignmentsScreen({ navigation }: Props) {
  const { repId, clearSession } = useSession();
  const [assignments, setAssignments] = useState<RepAssignment[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<AssignmentFilter>("open");

  const loadAssignments = useCallback(async () => {
    if (!repId) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await fetchRepAssignments(repId);
      setAssignments(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load assignments");
    } finally {
      setLoading(false);
    }
  }, [repId]);

  const startDrill = useCallback(
    async (assignment: RepAssignment) => {
      if (!repId) {
        return;
      }
      setLoading(true);
      setError(null);
      try {
        navigation.navigate("PreSession", {
          assignmentId: assignment.id,
          scenarioId: assignment.scenario_id,
        });
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to start session");
      } finally {
        setLoading(false);
      }
    },
    [navigation, repId]
  );

  useEffect(() => {
    void loadAssignments();
  }, [loadAssignments]);

  const openCount = useMemo(() => assignments.filter((assignment) => assignment.status !== "completed").length, [assignments]);
  const completedCount = useMemo(() => assignments.filter((assignment) => assignment.status === "completed").length, [assignments]);
  const dueSoonCount = useMemo(
    () => assignments.filter((assignment) => assignment.status !== "completed" && isDueSoon(assignment.due_at)).length,
    [assignments]
  );
  const filteredAssignments = useMemo(() => filterAssignments(assignments, filter), [assignments, filter]);

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <View style={styles.headerRow}>
          <View>
            <Text style={styles.title}>Your Drills</Text>
            <Text style={styles.subtitle}>Open a brief, then jump straight into the roleplay.</Text>
          </View>
          <Pressable onPress={clearSession}>
            <Text style={styles.signOut}>Sign Out</Text>
          </Pressable>
        </View>

        <View style={styles.metricRow}>
          <View style={styles.metricCard}>
            <Text style={styles.metricLabel}>Open</Text>
            <Text style={styles.metricValue}>{openCount}</Text>
          </View>
          <View style={styles.metricCard}>
            <Text style={styles.metricLabel}>Due Soon</Text>
            <Text style={styles.metricValue}>{dueSoonCount}</Text>
          </View>
          <View style={styles.metricCard}>
            <Text style={styles.metricLabel}>Completed</Text>
            <Text style={styles.metricValue}>{completedCount}</Text>
          </View>
        </View>

        <View style={styles.filterRow}>
          {([
            ["open", "Open"],
            ["due_soon", "Due Soon"],
            ["completed", "Completed"],
            ["all", "All"]
          ] as const).map(([value, label]) => {
            const active = filter === value;
            return (
              <Pressable key={value} style={[styles.filterChip, active && styles.filterChipActive]} onPress={() => setFilter(value)}>
                <Text style={[styles.filterLabel, active && styles.filterLabelActive]}>{label}</Text>
              </Pressable>
            );
          })}
        </View>

        <View style={styles.actionRow}>
          <Pressable style={[styles.actionBtn, loading && styles.disabled]} disabled={loading} onPress={loadAssignments}>
            <Text style={styles.actionLabel}>{loading ? "Loading..." : "Refresh"}</Text>
          </Pressable>
          <Pressable style={styles.ghostBtn} onPress={() => navigation.navigate("History")}>
            <Text style={styles.ghostLabel}>History</Text>
          </Pressable>
        </View>

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <ScrollView contentContainerStyle={styles.list}>
          {filteredAssignments.length === 0 ? <Text style={styles.empty}>No assignments for this filter.</Text> : null}
          {filteredAssignments.map((assignment) => (
            <AssignmentCard
              key={assignment.id}
              assignment={assignment}
              disabled={loading}
              onStart={() => {
                void startDrill(assignment);
              }}
            />
          ))}
        </ScrollView>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.bg },
  container: { flex: 1, padding: 18, gap: 12 },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  title: { fontSize: 28, fontWeight: "800", color: colors.ink },
  subtitle: { color: colors.muted },
  signOut: { color: colors.accent, fontWeight: "700", paddingTop: 10 },
  metricRow: { flexDirection: "row", gap: 8 },
  metricCard: {
    flex: 1,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    padding: 10
  },
  metricLabel: { color: colors.muted, fontSize: 11, fontWeight: "700", textTransform: "uppercase" },
  metricValue: { color: colors.ink, fontSize: 24, fontWeight: "800", marginTop: 3 },
  filterRow: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  filterChip: {
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    paddingVertical: 6,
    paddingHorizontal: 11
  },
  filterChipActive: {
    backgroundColor: colors.accent,
    borderColor: colors.accent
  },
  filterLabel: { color: colors.ink, fontSize: 12, fontWeight: "700" },
  filterLabelActive: { color: "white" },
  actionRow: { flexDirection: "row", gap: 10 },
  actionBtn: {
    borderRadius: 12,
    backgroundColor: colors.accent,
    paddingVertical: 10,
    paddingHorizontal: 16
  },
  actionLabel: { color: "white", fontWeight: "800" },
  ghostBtn: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.line,
    paddingVertical: 10,
    paddingHorizontal: 16,
    backgroundColor: colors.panel
  },
  ghostLabel: { color: colors.ink, fontWeight: "700" },
  disabled: { opacity: 0.5 },
  error: { color: "#AF2D18", fontWeight: "600" },
  empty: { color: colors.muted },
  list: { gap: 10, paddingBottom: 30 }
});
