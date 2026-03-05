import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useCallback, useEffect, useState } from "react";
import { Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View } from "react-native";

import { AssignmentCard } from "../components/AssignmentCard";
import { createRepSession, fetchRepAssignments } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { RepAssignment } from "../types";
import { RootStackParamList } from "../navigation/types";

type Props = NativeStackScreenProps<RootStackParamList, "Assignments">;

export function AssignmentsScreen({ navigation }: Props) {
  const { repId, clearSession } = useSession();
  const [assignments, setAssignments] = useState<RepAssignment[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        const session = await createRepSession(repId, assignment.id, assignment.scenario_id);
        navigation.navigate("Session", {
          assignmentId: assignment.id,
          scenarioId: assignment.scenario_id,
          sessionId: session.id
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

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <View style={styles.headerRow}>
          <View>
            <Text style={styles.title}>Assignments</Text>
            <Text style={styles.subtitle}>Rep {repId?.slice(0, 8)}</Text>
          </View>
          <Pressable onPress={clearSession}>
            <Text style={styles.signOut}>Sign Out</Text>
          </Pressable>
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
          {assignments.length === 0 ? <Text style={styles.empty}>No assignments loaded yet.</Text> : null}
          {assignments.map((assignment) => (
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
  container: { flex: 1, padding: 20, gap: 12 },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" },
  title: { fontSize: 28, fontWeight: "700", color: colors.ink },
  subtitle: { color: colors.muted },
  signOut: { color: colors.accent, fontWeight: "700", paddingTop: 10 },
  actionRow: { flexDirection: "row", gap: 10 },
  actionBtn: {
    borderRadius: 12,
    backgroundColor: colors.accent,
    paddingVertical: 10,
    paddingHorizontal: 16
  },
  actionLabel: { color: "white", fontWeight: "700" },
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
  error: { color: "#AF2D18" },
  empty: { color: colors.muted },
  list: { gap: 10, paddingBottom: 30 }
});
