import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useEffect, useMemo, useState } from "react";
import { ActivityIndicator, Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View } from "react-native";

import { RootStackParamList } from "../navigation/types";
import { fetchRepSession } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { RepSessionDetail, Scorecard } from "../types";

type Props = NativeStackScreenProps<RootStackParamList, "Score">;

type CategoryKey = "opening" | "pitch_delivery" | "objection_handling" | "closing_technique" | "professionalism";

type CategoryRow = {
  key: CategoryKey;
  label: string;
  score: number;
};

const CATEGORY_ORDER: Array<{ key: CategoryKey; label: string }> = [
  { key: "opening", label: "Opening" },
  { key: "pitch_delivery", label: "Pitch" },
  { key: "objection_handling", label: "Objection Handling" },
  { key: "closing_technique", label: "Closing" },
  { key: "professionalism", label: "Professionalism" },
];

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function scoreValue(value: number | { score?: number } | undefined): number {
  if (typeof value === "number") {
    return clamp(value, 0, 10);
  }
  if (value && typeof value.score === "number") {
    return clamp(value.score, 0, 10);
  }
  return 0;
}

function scoreBand(score: number): { bg: string; border: string; text: string; fill: string } {
  if (score < 5) {
    return { bg: "#FBE5E1", border: "#E5B3AA", text: "#9F3021", fill: "#D2553C" };
  }
  if (score < 7) {
    return { bg: "#FFF2DA", border: "#E4C18B", text: "#8B5C1D", fill: "#D19A2F" };
  }
  return { bg: "#E3F3E8", border: "#B5D9BF", text: "#1E6A3B", fill: "#2E8B57" };
}

function scoreWidth(score: number): `${number}%` {
  return `${clamp((score / 10) * 100, 0, 100)}%`;
}

function managerNoteFromData(data: RepSessionDetail | null): string | null {
  if (!data) {
    return null;
  }
  const reviewNotes = data.manager_review?.notes;
  if (reviewNotes && reviewNotes.trim()) {
    return reviewNotes.trim();
  }
  const managerNote = data.manager_note;
  if (managerNote && managerNote.trim()) {
    return managerNote.trim();
  }
  return null;
}

export function ScoreScreen({ route, navigation }: Props) {
  const { repId } = useSession();
  const { sessionId } = route.params;
  const [data, setData] = useState<RepSessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollCount, setPollCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    async function loadScorecard() {
      if (!repId) {
        return;
      }

      if (!cancelled) {
        setLoading((current) => (pollCount === 0 ? true : current));
        setRefreshing(pollCount > 0);
        setError(null);
      }

      try {
        const result = await fetchRepSession(repId, sessionId);
        if (cancelled) {
          return;
        }
        setData(result);

        if (!result.scorecard && pollCount < 5) {
          retryTimer = setTimeout(() => {
            setPollCount((current) => current + 1);
          }, 2000);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load scorecard");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    }

    void loadScorecard();

    return () => {
      cancelled = true;
      if (retryTimer) {
        clearTimeout(retryTimer);
      }
    };
  }, [pollCount, repId, sessionId]);

  const scorecard = data?.scorecard;
  const overallScore = scorecard?.overall_score ?? 0;
  const overallBand = scoreBand(overallScore);
  const managerNote = managerNoteFromData(data);

  const categories = useMemo<CategoryRow[]>(() => {
    const scores = scorecard?.category_scores ?? {};
    return CATEGORY_ORDER.map((category) => ({
      ...category,
      score: scoreValue(scores[category.key]),
    }));
  }, [scorecard]);

  const highlights = (scorecard?.highlights ?? []).slice(0, 4);

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
          <View style={[styles.heroCard, { backgroundColor: overallBand.bg, borderColor: overallBand.border }]}> 
            <Text style={[styles.heroKicker, { color: overallBand.text }]}>Drill Score</Text>
            <Text style={[styles.heroValue, { color: overallBand.text }]}>{overallScore.toFixed(1)}</Text>
            <Text style={styles.heroSubtext}>Session {sessionId.slice(0, 8)}</Text>
          </View>

          {loading ? (
            <View style={styles.loadingCard}>
              <ActivityIndicator color={colors.accent} />
              <Text style={styles.loadingText}>Pulling your scorecard...</Text>
            </View>
          ) : null}

          {refreshing && !scorecard ? <Text style={styles.refreshText}>AI grading is still processing...</Text> : null}
          {error ? <Text style={styles.errorText}>{error}</Text> : null}

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Category Breakdown</Text>
            {categories.map((category) => {
              const band = scoreBand(category.score);
              return (
                <View key={category.key} style={styles.categoryRow}>
                  <View style={styles.categoryHeader}>
                    <Text style={styles.categoryName}>{category.label}</Text>
                    <Text style={styles.categoryScore}>{category.score.toFixed(1)}</Text>
                  </View>
                  <View style={styles.track}>
                    <View style={[styles.trackFill, { width: scoreWidth(category.score), backgroundColor: band.fill }]} />
                  </View>
                </View>
              );
            })}
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>Highlight Moments</Text>
            {highlights.length === 0 ? <Text style={styles.emptyText}>No highlights are available yet.</Text> : null}
            {highlights.map((highlight, index) => {
              const band = highlight.type === "strong" ? scoreBand(8) : scoreBand(6);
              const quote = highlight.transcript_quote || highlight.quote || null;
              return (
                <View key={`${highlight.note}-${index}`} style={[styles.highlightCard, { backgroundColor: band.bg, borderColor: band.border }]}> 
                  <View style={styles.highlightHeader}>
                    <Text style={[styles.highlightType, { color: band.text }]}>
                      {highlight.type === "strong" ? "Strong" : "Improve"}
                    </Text>
                    {highlight.turn_id ? <Text style={styles.turnRef}>Turn {highlight.turn_id.slice(0, 8)}</Text> : null}
                  </View>
                  <Text style={styles.highlightNote}>{highlight.note}</Text>
                  {quote ? <Text style={styles.highlightQuote}>"{quote}"</Text> : null}
                </View>
              );
            })}
          </View>

          <View style={styles.section}>
            <Text style={styles.sectionTitle}>AI Summary</Text>
            <Text style={styles.summaryText}>
              {scorecard?.ai_summary ?? "Your scorecard is still being assembled. Check back in a few seconds."}
            </Text>
          </View>

          {managerNote ? (
            <View style={styles.managerNoteCard}>
              <Text style={styles.managerNoteLabel}>Manager Coaching Note</Text>
              <Text style={styles.managerNoteText}>{managerNote}</Text>
            </View>
          ) : null}
        </ScrollView>

        <View style={styles.ctaRow}>
          <Pressable
            style={styles.primaryCta}
            onPress={() => {
              const assignmentId = data?.session.assignment_id;
              const scenarioId = data?.session.scenario_id;
              if (assignmentId && scenarioId) {
                navigation.replace("PreSession", { assignmentId, scenarioId });
              }
            }}
          >
            <Text style={styles.primaryCtaLabel}>Try Again</Text>
          </Pressable>
          <Pressable style={styles.secondaryCta} onPress={() => navigation.replace("Assignments")}>
            <Text style={styles.secondaryCtaLabel}>Back to Drills</Text>
          </Pressable>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.bg },
  container: { flex: 1 },
  content: { paddingHorizontal: 20, paddingTop: 16, paddingBottom: 150, gap: 16 },
  heroCard: {
    borderRadius: 24,
    borderWidth: 1,
    padding: 24,
    alignItems: "center",
    gap: 6,
  },
  heroKicker: { fontSize: 12, fontWeight: "800", textTransform: "uppercase", letterSpacing: 1 },
  heroValue: { fontSize: 56, fontWeight: "900", lineHeight: 60 },
  heroSubtext: { color: colors.muted, fontSize: 13, fontWeight: "600" },
  loadingCard: {
    borderRadius: 18,
    backgroundColor: colors.panel,
    borderWidth: 1,
    borderColor: colors.line,
    padding: 16,
    alignItems: "center",
    gap: 10,
  },
  loadingText: { color: colors.muted, fontSize: 14 },
  refreshText: { color: colors.muted, fontSize: 13, textAlign: "center" },
  errorText: { color: "#AF2D18", fontSize: 14, fontWeight: "700", textAlign: "center" },
  section: {
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    padding: 18,
    gap: 14,
  },
  sectionTitle: { color: colors.ink, fontSize: 16, fontWeight: "800" },
  categoryRow: { gap: 8 },
  categoryHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  categoryName: { color: colors.ink, fontSize: 14, fontWeight: "700" },
  categoryScore: { color: colors.ink, fontSize: 14, fontWeight: "800" },
  track: {
    height: 10,
    borderRadius: 999,
    backgroundColor: "#EFE3D4",
    overflow: "hidden",
  },
  trackFill: {
    height: "100%",
    borderRadius: 999,
  },
  emptyText: { color: colors.muted, fontSize: 14 },
  highlightCard: {
    borderRadius: 16,
    borderWidth: 1,
    padding: 14,
    gap: 8,
  },
  highlightHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  highlightType: { fontSize: 12, fontWeight: "800", textTransform: "uppercase", letterSpacing: 0.8 },
  turnRef: { color: colors.muted, fontSize: 11, fontWeight: "700" },
  highlightNote: { color: colors.ink, fontSize: 15, fontWeight: "700", lineHeight: 21 },
  highlightQuote: {
    color: colors.muted,
    fontSize: 13,
    lineHeight: 19,
    fontStyle: "italic",
  },
  summaryText: { color: colors.ink, fontSize: 15, lineHeight: 23 },
  managerNoteCard: {
    marginHorizontal: 20,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: "#C8D9EA",
    backgroundColor: "#EFF6FD",
    padding: 18,
    gap: 8,
  },
  managerNoteLabel: { color: "#25527A", fontSize: 12, fontWeight: "800", textTransform: "uppercase", letterSpacing: 0.8 },
  managerNoteText: { color: "#163954", fontSize: 15, lineHeight: 22, fontWeight: "600" },
  ctaRow: {
    position: "absolute",
    left: 0,
    right: 0,
    bottom: 0,
    paddingHorizontal: 20,
    paddingTop: 14,
    paddingBottom: 24,
    gap: 10,
    backgroundColor: colors.bg,
    borderTopWidth: 1,
    borderTopColor: colors.line,
  },
  primaryCta: {
    borderRadius: 16,
    backgroundColor: colors.accent,
    alignItems: "center",
    paddingVertical: 16,
  },
  primaryCtaLabel: { color: "#fff", fontSize: 16, fontWeight: "800" },
  secondaryCta: {
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    alignItems: "center",
    paddingVertical: 15,
  },
  secondaryCtaLabel: { color: colors.ink, fontSize: 15, fontWeight: "700" },
});
