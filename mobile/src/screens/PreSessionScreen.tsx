import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { Audio } from "expo-av";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View } from "react-native";
import { ChevronLeft } from "lucide-react-native";

import { RootStackParamList } from "../navigation/types";
import { checkApiReachable, createRepSession, fetchRepAssignments, fetchRepScenario } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { RepAssignment, ScenarioBrief } from "../types";

type Props = NativeStackScreenProps<RootStackParamList, "PreSession">;

function formatDifficultyDots(level: number): number[] {
  return [1, 2, 3, 4, 5].map((value) => (value <= Math.max(1, Math.min(5, level)) ? 1 : 0));
}

function targetSkillsForScenario(scenario: ScenarioBrief | null): string[] {
  if (!scenario) {
    return ["Opening", "Objection Handling", "Closing"];
  }

  const rubricSkills = Object.keys(scenario.rubric || {}).map((key) =>
    key.replaceAll("_", " ").replace(/\b\w/g, (match) => match.toUpperCase())
  );
  const stageSkills = (scenario.stages || [])
    .filter((stage) => !["door_knock", "ended"].includes(stage))
    .map((stage) => stage.replaceAll("_", " ").replace(/\b\w/g, (match) => match.toUpperCase()));
  const concernSkills = Array.isArray(scenario.persona?.concerns)
    ? (scenario.persona.concerns as unknown[])
        .slice(0, 2)
        .map((item) => String(item).replace(/\b\w/g, (match) => match.toUpperCase()))
    : [];

  return Array.from(new Set([...rubricSkills, ...stageSkills, ...concernSkills])).filter(Boolean).slice(0, 4);
}

function personaSummary(scenario: ScenarioBrief | null): { name: string; attitude: string; cue: string } {
  const persona = scenario?.persona ?? {};
  return {
    name: String(persona.name || "Homeowner"),
    attitude: String(persona.attitude || "Guarded"),
    cue: String(
      persona.softening_condition ||
        "They will warm up if you sound credible, concise, and focused on the home."
    ),
  };
}

export function PreSessionScreen({ route, navigation }: Props) {
  const { assignmentId, scenarioId } = route.params;
  const { repId } = useSession();
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assignment, setAssignment] = useState<RepAssignment | null>(null);
  const [scenario, setScenario] = useState<ScenarioBrief | null>(null);

  useEffect(() => {
    async function loadBrief() {
      if (!repId) {
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const [assignments, scenarioResult] = await Promise.all([
          fetchRepAssignments(repId),
          fetchRepScenario(repId, scenarioId),
        ]);
        setAssignment(assignments.find((item) => item.id === assignmentId) ?? null);
        setScenario(scenarioResult);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load drill brief");
      } finally {
        setLoading(false);
      }
    }

    void loadBrief();
  }, [assignmentId, repId, scenarioId]);

  const difficulty = scenario?.difficulty ?? 3;
  const difficultyDots = useMemo(() => formatDifficultyDots(difficulty), [difficulty]);
  const skills = useMemo(() => targetSkillsForScenario(scenario), [scenario]);
  const persona = useMemo(() => personaSummary(scenario), [scenario]);

  const startDrill = useCallback(async () => {
    if (!repId || !assignment) {
      return;
    }

    setStarting(true);
    setError(null);
    try {
      const reachable = await checkApiReachable();
      if (!reachable) {
        throw new Error("No internet connection. Reconnect before starting a drill.");
      }

      const permission = await Audio.getPermissionsAsync();
      const granted = permission.granted ? permission : await Audio.requestPermissionsAsync();
      if (!granted.granted) {
        throw new Error("Microphone access is required to run a live drill.");
      }

      const session = await createRepSession(repId, assignment.id, assignment.scenario_id);
      navigation.replace("Session", {
        assignmentId: assignment.id,
        scenarioId: assignment.scenario_id,
        sessionId: session.id,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start drill");
    } finally {
      setStarting(false);
    }
  }, [assignment, navigation, repId]);

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <View style={styles.header}>
          <Pressable onPress={() => navigation.goBack()} style={styles.backBtn}>
            <ChevronLeft color={colors.ink} size={22} />
          </Pressable>
          <Text style={styles.headerLabel}>Drill Brief</Text>
        </View>

        <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
          <View style={styles.heroCard}>
            <Text style={styles.kicker}>Up next</Text>
            <View style={styles.titleRow}>
              <Text style={styles.scenarioName}>{scenario?.name ?? "Loading scenario..."}</Text>
              <View style={styles.difficultyBadge}>
                {difficultyDots.map((active, index) => (
                  <View key={index} style={[styles.dot, active ? styles.dotActive : styles.dotInactive]} />
                ))}
              </View>
            </View>
            <Text style={styles.description}>
              {scenario?.description ??
                "We are loading the scenario brief and preparing the live homeowner drill."}
            </Text>
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionLabel}>Target Skills</Text>
            <View style={styles.chipRow}>
              {skills.map((skill) => (
                <View key={skill} style={styles.skillChip}>
                  <Text style={styles.skillChipLabel}>{skill}</Text>
                </View>
              ))}
            </View>
          </View>

          <View style={styles.personaCard}>
            <Text style={styles.sectionLabel}>Homeowner</Text>
            <Text style={styles.personaName}>
              {persona.name} · {persona.attitude}
            </Text>
            <Text style={styles.personaHint}>{persona.cue}</Text>
          </View>

          {assignment?.min_score_target ? (
            <View style={styles.targetCard}>
              <Text style={styles.targetLabel}>Score target</Text>
              <Text style={styles.targetValue}>{assignment.min_score_target.toFixed(1)} / 10</Text>
            </View>
          ) : null}

          {loading ? (
            <View style={styles.loadingCard}>
              <ActivityIndicator color={colors.accent} />
              <Text style={styles.loadingText}>Preparing your drill brief...</Text>
            </View>
          ) : null}

          {error ? <Text style={styles.errorText}>{error}</Text> : null}
        </ScrollView>

        <Pressable
          style={[styles.startBtn, (starting || loading || !assignment) && styles.startBtnDisabled]}
          onPress={() => {
            void startDrill();
          }}
          disabled={starting || loading || !assignment}
        >
          {starting ? <ActivityIndicator color="#fff" size="small" /> : <Text style={styles.startBtnLabel}>Start Drill</Text>}
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.bg },
  container: { flex: 1, paddingHorizontal: 20 },
  header: {
    paddingTop: 8,
    flexDirection: "row",
    alignItems: "center",
    gap: 10,
  },
  backBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: colors.panel,
    borderWidth: 1,
    borderColor: colors.line,
  },
  headerLabel: { color: colors.muted, fontSize: 13, fontWeight: "700", textTransform: "uppercase", letterSpacing: 0.8 },
  content: { paddingTop: 18, paddingBottom: 150, gap: 16 },
  heroCard: {
    borderRadius: 24,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    padding: 22,
    gap: 14,
  },
  kicker: { color: colors.accent, fontSize: 12, fontWeight: "800", textTransform: "uppercase", letterSpacing: 1 },
  titleRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start", gap: 12 },
  scenarioName: { flex: 1, color: colors.ink, fontSize: 28, fontWeight: "800", lineHeight: 32 },
  difficultyBadge: { flexDirection: "row", gap: 5, paddingTop: 8 },
  dot: { width: 9, height: 9, borderRadius: 99 },
  dotActive: { backgroundColor: colors.accent },
  dotInactive: { backgroundColor: "#E7C6B8" },
  description: { color: colors.muted, fontSize: 16, lineHeight: 24 },
  section: {
    gap: 12,
  },
  sectionLabel: { color: colors.muted, fontSize: 12, fontWeight: "800", textTransform: "uppercase", letterSpacing: 0.8 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  skillChip: {
    borderRadius: 999,
    backgroundColor: colors.accentSoft,
    borderWidth: 1,
    borderColor: "#EAC0AF",
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  skillChipLabel: { color: colors.accent, fontSize: 13, fontWeight: "700" },
  personaCard: {
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: "#FFF6EA",
    padding: 18,
    gap: 8,
  },
  personaName: { color: colors.ink, fontSize: 18, fontWeight: "800" },
  personaHint: { color: colors.muted, fontSize: 14, lineHeight: 21 },
  targetCard: {
    borderRadius: 18,
    borderWidth: 1,
    borderColor: "#D8C7B2",
    backgroundColor: "#F1E6D7",
    padding: 16,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  targetLabel: { color: colors.muted, fontSize: 12, fontWeight: "800", textTransform: "uppercase" },
  targetValue: { color: colors.ink, fontSize: 18, fontWeight: "800" },
  loadingCard: {
    borderRadius: 16,
    backgroundColor: colors.panel,
    borderWidth: 1,
    borderColor: colors.line,
    padding: 16,
    alignItems: "center",
    gap: 10,
  },
  loadingText: { color: colors.muted, fontSize: 14 },
  errorText: { color: "#AF2D18", fontSize: 14, fontWeight: "700", lineHeight: 20 },
  startBtn: {
    position: "absolute",
    left: 20,
    right: 20,
    bottom: 24,
    borderRadius: 18,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 18,
    shadowColor: colors.accent,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.24,
    shadowRadius: 14,
  },
  startBtnDisabled: { opacity: 0.55 },
  startBtnLabel: { color: "#fff", fontSize: 17, fontWeight: "800" },
});
