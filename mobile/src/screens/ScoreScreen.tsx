import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useEffect, useMemo, useState, useRef } from "react";
import { ActivityIndicator, Animated as RNAnimated, Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View } from "react-native";
import { UserCircle } from "lucide-react-native";
import Animated, { FadeInDown, FadeInUp, withSpring } from "react-native-reanimated";
import { LinearGradient } from "expo-linear-gradient";
import { BlurView } from "expo-blur";

import { RootStackParamList } from "../navigation/types";
import { fetchRepSession, fetchRepScenario } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { RepSessionDetail, Scorecard, ScenarioBrief } from "../types";

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

function scoreBand(score: number) {
  if (score < 5) return { bg: "rgba(220, 38, 38, 0.12)", text: "#dc2626", border: "rgba(220, 38, 38, 0.2)" };
  if (score < 8) return { bg: "rgba(217, 119, 6, 0.12)", text: "#d97706", border: "rgba(217, 119, 6, 0.2)" };
  return { bg: "rgba(22, 101, 52, 0.12)", text: "#166534", border: "rgba(22, 101, 52, 0.2)" };
}

function CategoryBar({ label, score, index }: { label: string; score: number; index: number }) {
  const widthAnim = useRef(new RNAnimated.Value(0)).current;
  const band = scoreBand(score);

  useEffect(() => {
    RNAnimated.timing(widthAnim, {
      toValue: (score / 10) * 100,
      duration: 700,
      delay: index * 100,
      useNativeDriver: false,
    }).start();
  }, [score, index, widthAnim]);

  return (
    <Animated.View entering={FadeInDown.delay(300 + index * 100).springify()} style={styles.categoryRow}>
      <View style={styles.categoryHeader}>
        <Text style={styles.categoryName}>{label}</Text>
        <Text style={[styles.categoryScore, { color: band.text }]}>{score.toFixed(1)}</Text>
      </View>
      <View style={styles.track}>
        <RNAnimated.View
          style={[
            styles.trackFill,
            { backgroundColor: colors.accent, width: widthAnim.interpolate({ inputRange: [0, 100], outputRange: ["0%", "100%"] }) }
          ]}
        />
      </View>
    </Animated.View>
  );
}

export function ScoreScreen({ route, navigation }: Props) {
  const { repId } = useSession();
  const { sessionId } = route.params;
  const [data, setData] = useState<RepSessionDetail | null>(null);
  const [scenario, setScenario] = useState<ScenarioBrief | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pollCount, setPollCount] = useState(0);

  const heroBarAnim = useRef(new RNAnimated.Value(0)).current;

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    async function loadData() {
      if (!repId) return;

      if (!cancelled && pollCount === 0) {
        setLoading(true);
      } else if (!cancelled) {
        setRefreshing(true);
      }

      try {
        const result = await fetchRepSession(repId, sessionId);
        if (cancelled) return;
        setData(result);

        if (result.session.scenario_id && !scenario) {
          const sc = await fetchRepScenario(repId, result.session.scenario_id);
          if (!cancelled) setScenario(sc);
        }

        if (!result.scorecard && pollCount < 5) {
          retryTimer = setTimeout(() => {
            if (!cancelled) setPollCount((c) => c + 1);
          }, 2000);
        }
      } catch (err) {
        if (!cancelled && pollCount === 0) {
          setError(err instanceof Error ? err.message : "Failed to load scorecard");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          setRefreshing(false);
        }
      }
    }

    void loadData();

    return () => {
      cancelled = true;
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [pollCount, repId, sessionId, scenario]);

  const scorecard = data?.scorecard;
  const overallScore = scorecard?.overall_score ?? 0;
  const overallBand = scoreBand(overallScore);

  useEffect(() => {
    if (scorecard) {
      RNAnimated.timing(heroBarAnim, {
        toValue: (overallScore / 10) * 100,
        duration: 800,
        useNativeDriver: false,
      }).start();
    }
  }, [scorecard, overallScore, heroBarAnim]);

  const managerNote = data?.manager_note || data?.manager_review?.notes;

  const categories = useMemo<CategoryRow[]>(() => {
    const scores = scorecard?.category_scores ?? {};
    return CATEGORY_ORDER.map((cat) => ({
      ...cat,
      score: scoreValue(scores[cat.key]),
    }));
  }, [scorecard]);

  const highlights = (scorecard?.highlights ?? []).slice(0, 4);

  return (
    <LinearGradient colors={["#FDFDFD", "#F7F4EE", "#EBE5D9"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {loading ? (
          <View style={styles.loadingCard}>
            <ActivityIndicator color={colors.accent} />
            <Text style={styles.loadingText}>Pulling your scorecard...</Text>
          </View>
        ) : (
          <>
            <View style={styles.heroBlock}>
              {/* @ts-ignore */}
              <Animated.View sharedTransitionTag="ai-orb" style={[styles.heroOrb, { backgroundColor: overallBand.bg, borderColor: overallBand.border }]}>
                <Text style={[styles.heroValue, { color: overallBand.text }]}>{overallScore.toFixed(1)}</Text>
                <Text style={styles.heroLabel}>Overall Score</Text>
              </Animated.View>
              <View style={styles.heroBarTrack}>
                <RNAnimated.View
                  style={[
                    styles.heroBarFill,
                    {
                      backgroundColor: overallBand.text,
                      width: heroBarAnim.interpolate({ inputRange: [0, 100], outputRange: ["0%", "100%"] }),
                    },
                  ]}
                />
              </View>
              <Text style={styles.scenarioName}>{scenario?.name ?? "Scenario"}</Text>
            </View>

            {refreshing && !scorecard ? <Text style={styles.refreshText}>AI grading is still processing...</Text> : null}
            {error ? <Text style={styles.errorText}>{error}</Text> : null}

            {scorecard ? (
              <>
                <Text style={styles.sectionTitle}>PERFORMANCE BREAKDOWN</Text>
                <BlurView intensity={40} tint="light" style={styles.categoriesContainer}>
                  {categories.map((cat, idx) => (
                    <CategoryBar key={cat.key} label={cat.label} score={cat.score} index={idx} />
                  ))}
                </BlurView>

                <Text style={styles.sectionTitle}>KEY MOMENTS</Text>
                {highlights.length === 0 ? <Text style={styles.emptyText}>No highlights available.</Text> : null}
                {highlights.map((hl, idx) => {
                  const isStrong = hl.type === "strong";
                  const hlBand = isStrong ? scoreBand(8) : scoreBand(6);
                  const quote = hl.transcript_quote || hl.quote || null;

                  return (
                    <Animated.View key={idx} entering={FadeInDown.delay(700 + idx * 100).springify()} style={styles.highlightCardWrapper}>
                      <BlurView intensity={40} tint="light" style={styles.highlightCard}>
                        <View style={styles.highlightHeader}>
                          <View style={[styles.highlightTag, { backgroundColor: isStrong ? colors.accentSoft : "#FEF3C7" }]}> 
                            <Text style={[styles.highlightTagText, { color: isStrong ? colors.accent : "#92400E" }]}>
                              {isStrong ? "Strong" : "Improve"}
                            </Text>
                          </View>
                          {hl.turn_id ? <Text style={styles.turnRef}>Turn {hl.turn_id.slice(0, 8)}</Text> : null}
                        </View>
                        <Text style={styles.highlightNote}>{hl.note}</Text>
                        {quote ? <Text style={styles.highlightQuote}>"{quote}"</Text> : null}
                      </BlurView>
                    </Animated.View>
                  );
                })}

                <Text style={styles.sectionTitle}>FEEDBACK</Text>
                <Animated.View entering={FadeInDown.delay(1000).springify()} style={styles.summaryCardWrapper}>
                  <BlurView intensity={40} tint="light" style={styles.summaryCard}>
                    <Text style={styles.summaryText}>{scorecard.ai_summary}</Text>
                  </BlurView>
                </Animated.View>

                {managerNote ? (
                  <Animated.View entering={FadeInDown.delay(1100).springify()} style={styles.managerNoteCard}>
                    <View style={styles.managerNoteHeader}>
                      <UserCircle size={16} color={colors.accent} />
                      <Text style={styles.managerNoteLabel}>Manager Note</Text>
                    </View>
                    <Text style={styles.managerNoteText}>{managerNote}</Text>
                  </Animated.View>
                ) : null}
              </>
            ) : null}

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
          <Pressable style={styles.secondaryCta} onPress={() => navigation.replace("MainTabs", { screen: "AssignmentsTab" })}>
            <Text style={styles.secondaryCtaLabel}>Back to Drills</Text>
          </Pressable>
            </View>
          </>
        )}
      </ScrollView>
    </SafeAreaView>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  safeArea: { flex: 1 },
  content: { padding: 20, paddingBottom: 40 },
  loadingCard: {
    marginTop: 40,
    padding: 20,
    alignItems: "center",
    gap: 12,
  },
  loadingText: { color: colors.muted, fontSize: 15 },
  refreshText: { color: colors.muted, fontSize: 13, textAlign: "center", marginBottom: 12 },
  errorText: { color: "#AF2D18", fontSize: 14, fontWeight: "700", textAlign: "center", marginBottom: 12 },
  
  heroBlock: {
    alignItems: "center",
    paddingTop: 12,
    marginBottom: 24,
  },
  heroOrb: {
    width: 160,
    height: 160,
    borderRadius: 80,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 12,
    borderWidth: StyleSheet.hairlineWidth,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.08,
    shadowRadius: 24,
    elevation: 4,
  },
  heroValue: {
    fontSize: 64,
    fontFamily: "Poppins_800ExtraBold",
  },
  heroLabel: {
    fontSize: 13,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 1.5,
    marginTop: 4,
  },
  heroBarTrack: {
    width: "100%",
    height: 4,
    backgroundColor: colors.line,
    borderRadius: 2,
    marginTop: 12,
    overflow: "hidden",
  },
  heroBarFill: {
    height: "100%",
    borderRadius: 2,
  },
  scenarioName: {
    fontSize: 15,
    fontWeight: "600",
    color: colors.ink,
    marginTop: 16,
  },
  
  sectionTitle: {
    fontSize: 12,
    fontWeight: "700",
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 1,
    marginTop: 28,
    marginBottom: 12,
  },
  categoriesContainer: {
    gap: 12,
    borderRadius: 24,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    backgroundColor: "rgba(255, 255, 255, 0.6)",
    padding: 24,
    overflow: "hidden",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.04,
    shadowRadius: 16,
    elevation: 3,
  },
  categoryRow: {
    gap: 6,
  },
  categoryHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  categoryName: {
    fontSize: 13,
    color: colors.ink,
  },
  categoryScore: {
    fontSize: 13,
    fontWeight: "700",
  },
  track: {
    height: 6,
    backgroundColor: colors.line,
    borderRadius: 3,
    overflow: "hidden",
  },
  trackFill: {
    height: "100%",
    borderRadius: 3,
  },
  
  emptyText: { color: colors.muted, fontSize: 14, fontStyle: "italic" },
  
  highlightCardWrapper: {
    marginBottom: 12,
    borderRadius: 24,
    overflow: "hidden",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    backgroundColor: "rgba(255, 255, 255, 0.6)",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.04,
    shadowRadius: 16,
    elevation: 3,
  },
  highlightCard: {
    padding: 20,
  },
  highlightHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  highlightTag: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
  },
  highlightTagText: {
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  turnRef: { color: colors.muted, fontSize: 11 },
  highlightNote: {
    fontSize: 14,
    fontWeight: "600",
    color: colors.ink,
    marginTop: 8,
  },
  highlightQuote: {
    fontSize: 13,
    color: colors.muted,
    fontStyle: "italic",
    marginTop: 6,
    lineHeight: 20,
  },
  
  summaryCardWrapper: {
    borderRadius: 24,
    overflow: "hidden",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    backgroundColor: "rgba(255, 255, 255, 0.6)",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.04,
    shadowRadius: 16,
    elevation: 3,
  },
  summaryCard: {
    padding: 24,
  },
  summaryText: {
    fontSize: 15,
    color: colors.ink,
    lineHeight: 24,
  },
  
  managerNoteCard: {
    backgroundColor: colors.accentSoft,
    borderLeftWidth: 3,
    borderLeftColor: colors.accent,
    borderRadius: 12,
    padding: 14,
    marginTop: 8,
  },
  managerNoteHeader: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  managerNoteLabel: {
    fontSize: 12,
    fontWeight: "700",
    color: colors.accent,
  },
  managerNoteText: {
    fontSize: 13,
    color: colors.ink,
    marginTop: 6,
    lineHeight: 18,
  },
  
  ctaRow: {
    flexDirection: "row",
    gap: 12,
    marginTop: 32,
  },
  primaryCta: {
    flex: 1,
    backgroundColor: colors.accent,
    borderRadius: 24,
    paddingVertical: 16,
    alignItems: "center",
    shadowColor: colors.accent,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.25,
    shadowRadius: 16,
    elevation: 4,
  },
  primaryCtaLabel: {
    color: "#fff",
    fontSize: 16,
    fontFamily: "Poppins_700Bold",
  },
  secondaryCta: {
    flex: 1,
    backgroundColor: "rgba(255, 255, 255, 0.6)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    borderRadius: 24,
    paddingVertical: 16,
    alignItems: "center",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.04,
    shadowRadius: 12,
    elevation: 2,
  },
  secondaryCtaLabel: {
    color: colors.ink,
    fontSize: 16,
    fontFamily: "Poppins_700Bold",
  },
});
