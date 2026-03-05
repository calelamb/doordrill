import { Pressable, StyleSheet, Text, View } from "react-native";

import { colors } from "../theme/tokens";
import { RepAssignment, ScenarioBrief } from "../types";

type Props = {
  assignment: RepAssignment;
  scenario?: ScenarioBrief;
  disabled?: boolean;
  onStart: () => void;
};

function DifficultyBadge({ level }: { level: number }) {
  const dots = Array.from({ length: 5 }, (_, i) => i + 1);
  return (
    <View style={styles.difficultyBadge}>
      {dots.map((i) => (
        <View key={i} style={[styles.dot, i <= level ? styles.dotFilled : styles.dotEmpty]} />
      ))}
    </View>
  );
}

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
    day: "numeric"
  });
}

export function AssignmentCard({ assignment, scenario, disabled = false, onStart }: Props) {
  const statusTone = statusStyles(assignment.status);
  const target = assignment.min_score_target ?? 80;

  return (
    <View style={[styles.card, assignment.status === "completed" && styles.cardCompleted]}>
      <View style={styles.headerRow}>
        <View style={styles.titleContainer}>
          <Text style={styles.scenarioName} numberOfLines={1}>
            {scenario?.name || `Scenario ${assignment.scenario_id.slice(0, 8)}`}
          </Text>
          {scenario && <DifficultyBadge level={scenario.difficulty} />}
        </View>
        <View style={[styles.statusChip, statusTone.chip]}>
          <Text style={[styles.statusLabel, statusTone.label]}>{assignment.status.replaceAll("_", " ")}</Text>
        </View>
      </View>

      <View style={styles.metaGrid}>
        <View style={styles.metaCell}>
          <Text style={styles.metaLabel}>Due Date</Text>
          <Text style={styles.metaValue}>{fmtDue(assignment.due_at)}</Text>
        </View>
        <View style={styles.metaCell}>
          <Text style={styles.metaLabel}>Target Score</Text>
          <Text style={styles.metaValue}>{target}</Text>
        </View>
      </View>

      <Pressable style={[styles.button, disabled && styles.disabled]} disabled={disabled} onPress={onStart}>
        <Text style={styles.buttonLabel}>{assignment.status === "completed" ? "Practice Again" : "Start Drill"}</Text>
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
    padding: 16,
    gap: 12
  },
  cardCompleted: {
    opacity: 0.85,
    backgroundColor: "#FDFDFD",
  },
  headerRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 8
  },
  titleContainer: {
    flex: 1,
    gap: 4,
    marginRight: 8,
  },
  scenarioName: {
    fontWeight: "800",
    color: colors.ink,
    fontSize: 16,
  },
  difficultyBadge: {
    flexDirection: "row",
    gap: 2,
    alignItems: "center"
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  dotFilled: {
    backgroundColor: colors.accent,
  },
  dotEmpty: {
    backgroundColor: colors.accentSoft,
    opacity: 0.6,
  },
  statusChip: { borderRadius: 999, paddingVertical: 4, paddingHorizontal: 8 },
  statusLabel: { fontSize: 10, fontWeight: "800", textTransform: "uppercase" },
  metaGrid: { flexDirection: "row", gap: 10 },
  metaCell: {
    flex: 1,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.bg,
    padding: 10,
    gap: 4
  },
  metaLabel: { color: colors.muted, fontSize: 11, fontWeight: "700", textTransform: "uppercase" },
  metaValue: { color: colors.ink, fontSize: 14, fontWeight: "700" },
  button: {
    borderRadius: 12,
    backgroundColor: colors.accent,
    alignItems: "center",
    paddingVertical: 12,
    marginTop: 2
  },
  disabled: { opacity: 0.5 },
  buttonLabel: { color: "white", fontWeight: "800", fontSize: 15 }
});
