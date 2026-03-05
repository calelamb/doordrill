import { Pressable, StyleSheet, Text, View } from "react-native";

import { RepAssignment } from "../types";
import { colors } from "../theme/tokens";

type Props = {
  assignment: RepAssignment;
  disabled?: boolean;
  onStart: () => void;
};

export function AssignmentCard({ assignment, disabled = false, onStart }: Props) {
  return (
    <View style={styles.card}>
      <Text style={styles.id}>Assignment {assignment.id.slice(0, 8)}</Text>
      <Text style={styles.meta}>Scenario {assignment.scenario_id.slice(0, 8)}</Text>
      <Text style={styles.meta}>Status {assignment.status}</Text>
      <Pressable style={[styles.button, disabled && styles.disabled]} disabled={disabled} onPress={onStart}>
        <Text style={styles.buttonLabel}>Start Drill</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    padding: 14,
    gap: 6
  },
  id: { fontWeight: "700", color: colors.ink },
  meta: { color: colors.muted, fontSize: 13 },
  button: {
    marginTop: 6,
    borderRadius: 10,
    backgroundColor: colors.accent,
    alignItems: "center",
    paddingVertical: 10
  },
  disabled: { opacity: 0.5 },
  buttonLabel: { color: "white", fontWeight: "700" }
});
