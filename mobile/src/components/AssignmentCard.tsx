import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "../theme/tokens";
import { RepAssignment } from "../types";

type Props = {
  assignment: RepAssignment;
  disabled?: boolean;
  onStart: () => void;
};

function statusStyles(status: string): { chip: object; label: object } {
  const normalized = status.toLowerCase();
  if (normalized === "completed") {
    return {
      chip: { backgroundColor: "#D9F4E7" },
      label: { color: "#165A36" }
    };
  }
  if (normalized === "in_progress") {
    return {
      chip: { backgroundColor: "#E2E8FF" },
      label: { color: "#273D8A" }
    };
  }
  return {
    chip: { backgroundColor: "#FFE7CF" },
    label: { color: "#8D461A" }
  };
}

function fmtDue(dueAt: string | null): string {
  if (!dueAt) {
    return "No deadline";
  }
  const parsed = new Date(dueAt);
  if (Number.isNaN(parsed.getTime())) {
    return "No deadline";
  }
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit"
  });
}

export function AssignmentCard({ assignment, disabled = false, onStart }: Props) {
  const statusTone = statusStyles(assignment.status);
  const target = assignment.min_score_target ?? 80;

  return (
    <View style={styles.card}>
      <View style={styles.headerRow}>
        <Text style={styles.id}>Assignment {assignment.id.slice(0, 8)}</Text>
        <View style={[styles.statusChip, statusTone.chip]}>
          <Text style={[styles.statusLabel, statusTone.label]}>{assignment.status.replaceAll("_", " ")}</Text>
        </View>
      </View>

      <View style={styles.metaGrid}>
        <View style={styles.metaCell}>
          <Text style={styles.metaLabel}>Scenario</Text>
          <Text style={styles.metaValue}>{assignment.scenario_id.slice(0, 8)}</Text>
        </View>
        <View style={styles.metaCell}>
          <Text style={styles.metaLabel}>Due</Text>
          <Text style={styles.metaValue}>{fmtDue(assignment.due_at)}</Text>
        </View>
      </View>

      <View style={styles.targetRow}>
        <Text style={styles.targetLabel}>Target Score</Text>
        <Text style={styles.targetValue}>{target}</Text>
      </View>

      <Pressable style={[styles.button, disabled && styles.disabled]} disabled={disabled} onPress={onStart}>
        <Text style={styles.buttonLabel}>{assignment.status === "in_progress" ? "Resume Drill" : "Start Drill"}</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    padding: 14,
    gap: 10
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 8
  },
  id: { fontWeight: "800", color: colors.ink, fontSize: 15 },
  statusChip: { borderRadius: 999, paddingVertical: 5, paddingHorizontal: 10 },
  statusLabel: { fontSize: 11, fontWeight: "700", textTransform: "capitalize" },
  metaGrid: { flexDirection: "row", gap: 10 },
  metaCell: {
    flex: 1,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: "#FFF9EF",
    padding: 9,
    gap: 3
  },
  metaLabel: { color: colors.muted, fontSize: 11, fontWeight: "700", textTransform: "uppercase" },
  metaValue: { color: colors.ink, fontSize: 13, fontWeight: "600" },
  targetRow: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.accentSoft,
    paddingHorizontal: 10,
    paddingVertical: 8,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center"
  },
  targetLabel: { color: colors.ink, fontSize: 12, fontWeight: "700" },
  targetValue: { color: colors.accent, fontSize: 18, fontWeight: "800" },
  button: {
    borderRadius: 12,
    backgroundColor: colors.accent,
    alignItems: "center",
    paddingVertical: 11
  },
  disabled: { opacity: 0.5 },
  buttonLabel: { color: "white", fontWeight: "800", fontSize: 14 }
});
