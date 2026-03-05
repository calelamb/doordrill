import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useEffect, useMemo, useState } from "react";
import { Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View } from "react-native";

import { RootStackParamList } from "../navigation/types";
import { fetchRepSession } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { RepSessionDetail } from "../types";

type Props = NativeStackScreenProps<RootStackParamList, "Score">;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function scorePercent(score: number): number {
  return clamp(score, 0, 100);
}

function highlightTone(type: string): { bg: string; border: string; label: string } {
  const normalized = type.toLowerCase();
  if (normalized.includes("weak") || normalized.includes("risk")) {
    return { bg: "#FCE7E3", border: "#E7B1A7", label: "#9B2F1D" };
  }
  if (normalized.includes("objection") || normalized.includes("critical")) {
    return { bg: "#FFF0DC", border: "#E3C090", label: "#8D5D1B" };
  }
  return { bg: "#E8F2FF", border: "#BCD3F3", label: "#1C4F87" };
}

export function ScoreScreen({ route, navigation }: Props) {
  const { repId } = useSession();
  const [data, setData] = useState<RepSessionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const sessionId = route.params.sessionId;

  useEffect(() => {
    if (!repId) {
      return;
    }
    setLoading(true);
    setError(null);
    fetchRepSession(repId, sessionId)
      .then((result) => setData(result))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "Failed to fetch scorecard"))
      .finally(() => setLoading(false));
  }, [repId, sessionId]);

  const scorecard = data?.scorecard;
  const categoryRows = useMemo(() => Object.entries(scorecard?.category_scores ?? {}), [scorecard]);

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <Text style={styles.title}>Drill Scorecard</Text>
        <Text style={styles.subtitle}>Session {sessionId.slice(0, 8)}</Text>

        {loading ? <Text style={styles.muted}>Scoring in progress...</Text> : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}

        <View style={styles.heroCard}>
          <Text style={styles.heroLabel}>Overall Score</Text>
          <Text style={styles.heroValue}>{scorecard?.overall_score ?? "--"}</Text>
          <Text style={styles.heroHint}>{scorecard?.ai_summary ?? "Manager-grade rationale will appear here."}</Text>
        </View>

        <ScrollView contentContainerStyle={styles.scrollContent}>
          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Category Breakdown</Text>
            {categoryRows.length === 0 ? <Text style={styles.empty}>No category scores yet.</Text> : null}
            {categoryRows.map(([category, score]) => {
              const width = scorePercent(score);
              return (
                <View style={styles.categoryRow} key={category}>
                  <View style={styles.categoryHeader}>
                    <Text style={styles.categoryName}>{category.replaceAll("_", " ")}</Text>
                    <Text style={styles.categoryScore}>{score.toFixed(1)}</Text>
                  </View>
                  <View style={styles.track}>
                    <View style={[styles.trackFill, { width: `${Math.round(width)}%` }]} />
                  </View>
                </View>
              );
            })}
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Highlights</Text>
            {scorecard?.highlights?.length ? null : <Text style={styles.empty}>No highlight events recorded.</Text>}
            {scorecard?.highlights?.map((highlight, index) => {
              const tone = highlightTone(highlight.type);
              return (
                <View key={`${highlight.note}-${index}`} style={[styles.highlight, { backgroundColor: tone.bg, borderColor: tone.border }]}>
                  <Text style={[styles.highlightType, { color: tone.label }]}>{highlight.type.toUpperCase()}</Text>
                  <Text style={styles.highlightText}>{highlight.note}</Text>
                  {highlight.turn_id ? <Text style={styles.turnRef}>Turn {highlight.turn_id.slice(0, 8)}</Text> : null}
                </View>
              );
            })}
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Weakness Tags</Text>
            <View style={styles.tagWrap}>
              {scorecard?.weakness_tags?.length ? null : <Text style={styles.empty}>No weakness tags.</Text>}
              {scorecard?.weakness_tags?.map((tag) => (
                <View key={tag} style={styles.tagChip}>
                  <Text style={styles.tagLabel}>{tag.replaceAll("_", " ")}</Text>
                </View>
              ))}
            </View>
            <Text style={styles.evidenceCount}>Evidence turns linked: {scorecard?.evidence_turn_ids?.length ?? 0}</Text>
          </View>
        </ScrollView>

        <Pressable style={styles.doneBtn} onPress={() => navigation.replace("Assignments")}>
          <Text style={styles.doneLabel}>Back To Assignments</Text>
        </Pressable>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.bg },
  container: { flex: 1, padding: 18, gap: 10 },
  title: { fontSize: 28, fontWeight: "800", color: colors.ink },
  subtitle: { color: colors.muted },
  muted: { color: colors.muted },
  error: { color: "#AF2D18", fontWeight: "700" },
  heroCard: {
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    padding: 14,
    gap: 5
  },
  heroLabel: { color: colors.muted, fontWeight: "700", fontSize: 12, textTransform: "uppercase" },
  heroValue: { color: colors.ink, fontSize: 42, fontWeight: "800", lineHeight: 46 },
  heroHint: { color: colors.ink, fontSize: 13, lineHeight: 18 },
  scrollContent: { gap: 10, paddingBottom: 20 },
  section: {
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    padding: 12,
    gap: 8
  },
  sectionTitle: { color: colors.ink, fontSize: 14, fontWeight: "800" },
  empty: { color: colors.muted, fontSize: 13 },
  categoryRow: { gap: 6 },
  categoryHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  categoryName: { color: colors.ink, fontWeight: "600", textTransform: "capitalize" },
  categoryScore: { color: colors.success, fontWeight: "800" },
  track: {
    width: "100%",
    height: 8,
    borderRadius: 999,
    backgroundColor: "#F0E4D5",
    overflow: "hidden"
  },
  trackFill: { height: "100%", borderRadius: 999, backgroundColor: colors.accent },
  highlight: {
    borderRadius: 12,
    borderWidth: 1,
    padding: 10,
    gap: 3
  },
  highlightType: { fontSize: 11, fontWeight: "800" },
  highlightText: { color: colors.ink, fontSize: 13 },
  turnRef: { color: colors.muted, fontSize: 11, fontWeight: "600" },
  tagWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "center" },
  tagChip: {
    borderRadius: 999,
    backgroundColor: colors.accentSoft,
    borderWidth: 1,
    borderColor: colors.line,
    paddingVertical: 5,
    paddingHorizontal: 10
  },
  tagLabel: { color: colors.ink, fontSize: 12, fontWeight: "700", textTransform: "capitalize" },
  evidenceCount: { color: colors.muted, fontSize: 12, fontWeight: "600" },
  doneBtn: {
    marginTop: "auto",
    borderRadius: 12,
    backgroundColor: colors.accent,
    alignItems: "center",
    paddingVertical: 12
  },
  doneLabel: { color: "white", fontWeight: "800" }
});
