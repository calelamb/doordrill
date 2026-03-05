import { Pressable, StyleSheet, Text, View } from "react-native";
import { BlurView } from "expo-blur";
import { Calendar, Target, Play, RotateCcw } from "lucide-react-native";

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
      chip: { backgroundColor: "rgba(74, 222, 128, 0.15)", borderWidth: 1, borderColor: "rgba(74, 222, 128, 0.3)" },
      label: { color: "#4ade80" }
    };
  }
  if (normalized === "in_progress") {
    return {
      chip: { backgroundColor: "rgba(59, 130, 246, 0.15)", borderWidth: 1, borderColor: "rgba(59, 130, 246, 0.3)" },
      label: { color: "#60a5fa" }
    };
  }
  return {
    chip: { backgroundColor: "rgba(245, 158, 11, 0.15)", borderWidth: 1, borderColor: "rgba(245, 158, 11, 0.3)" },
    label: { color: "#fbbf24" }
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
    <View style={[styles.cardWrapper, assignment.status === "completed" && styles.cardWrapperCompleted]}>
      <BlurView intensity={40} tint="light" style={[styles.card, assignment.status === "completed" && styles.cardCompleted]}>
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
            <View style={styles.metaLabelRow}>
              <Calendar size={12} color={colors.muted} />
              <Text style={styles.metaLabel}>Due Date</Text>
            </View>
            <Text style={styles.metaValue}>{fmtDue(assignment.due_at)}</Text>
          </View>
          <View style={styles.metaCell}>
            <View style={styles.metaLabelRow}>
              <Target size={12} color={colors.muted} />
              <Text style={styles.metaLabel}>Target Score</Text>
            </View>
            <Text style={styles.metaValue}>{target}</Text>
          </View>
        </View>

        <Pressable 
          style={({ pressed }) => [
            styles.button, 
            disabled && styles.disabled,
            pressed && !disabled && styles.buttonPressed
          ]} 
          disabled={disabled} 
          onPress={onStart}
        >
          {assignment.status === "completed" ? (
            <RotateCcw size={16} color="#fff" />
          ) : (
            <Play size={16} color="#fff" fill="#fff" />
          )}
          <Text style={styles.buttonLabel}>{assignment.status === "completed" ? "Practice Again" : "Start Drill"}</Text>
        </Pressable>
      </BlurView>
    </View>
  );
}

const styles = StyleSheet.create({
  cardWrapper: {
    borderRadius: 24, // Increased for squircle look
    overflow: "hidden",
    borderWidth: StyleSheet.hairlineWidth, // Apple style thin border
    borderColor: colors.line,
    backgroundColor: "rgba(255, 255, 255, 0.6)",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.04, // Ultra soft shadow
    shadowRadius: 16,
    elevation: 3,
  },
  cardWrapperCompleted: {
    opacity: 0.85,
  },
  card: {
    padding: 18,
    gap: 14,
  },
  cardCompleted: {
    backgroundColor: "rgba(255, 255, 255, 0.8)",
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
    backgroundColor: "rgba(255, 255, 255, 0.4)",
    padding: 12,
    gap: 6
  },
  metaLabelRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6
  },
  metaLabel: { color: colors.muted, fontSize: 11, fontWeight: "700", textTransform: "uppercase" },
  metaValue: { color: colors.ink, fontSize: 14, fontWeight: "700" },
  button: {
    flexDirection: "row",
    gap: 8,
    justifyContent: "center",
    borderRadius: 14,
    backgroundColor: colors.accent,
    alignItems: "center",
    paddingVertical: 14,
    marginTop: 4,
    borderWidth: 1,
    borderColor: "rgba(0, 0, 0, 0.05)",
  },
  buttonPressed: {
    opacity: 0.85,
    transform: [{ scale: 0.98 }]
  },
  disabled: { opacity: 0.5 },
  buttonLabel: { color: "white", fontWeight: "800", fontSize: 15 }
});
