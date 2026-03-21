import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Animated as RNAnimated,
  Pressable,
  SafeAreaView,
  ScrollView,
  Share,
  StyleProp,
  StyleSheet,
  Text,
  View,
  ViewStyle,
} from "react-native";
import * as Haptics from "expo-haptics";
import { ArrowRight, ChevronDown, ChevronUp, FileText, Share2, Star, TrendingUp, UserCircle } from "lucide-react-native";
import Animated, {
  FadeInDown,
  interpolate,
  useAnimatedStyle,
  useSharedValue,
  withRepeat,
  withSpring,
  withTiming,
} from "react-native-reanimated";
import { LinearGradient } from "expo-linear-gradient";
import { BlurView } from "expo-blur";

import { RootStackParamList } from "../navigation/types";
import { fetchRepPlan, fetchRepProgress, fetchRepScenario, fetchRepSession } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import {
  CategoryScoreDetail,
  GradingMeta,
  RepPlan,
  RepProgress,
  RepSessionDetail,
  ScenarioBrief,
  TechniqueCheck,
  TranscriptTurn,
} from "../types";

type Props = NativeStackScreenProps<RootStackParamList, "Score">;

type TabKey = "scorecard" | "transcript";
type CategoryKey = "opening" | "pitch_delivery" | "objection_handling" | "closing_technique" | "professionalism";
type HeroState = "processing" | "provisional" | "final" | "no_rep_speech" | "unavailable";

type CategoryRow = {
  key: CategoryKey;
  label: string;
  score: number;
  detail?: CategoryScoreDetail;
};

const CATEGORY_ORDER: Array<{ key: CategoryKey; label: string }> = [
  { key: "opening", label: "Opening" },
  { key: "pitch_delivery", label: "Pitch" },
  { key: "objection_handling", label: "Objection Handling" },
  { key: "closing_technique", label: "Closing" },
  { key: "professionalism", label: "Professionalism" },
];

const CATEGORY_INITIALS: Record<CategoryKey, string> = {
  opening: "O",
  pitch_delivery: "P",
  objection_handling: "OH",
  closing_technique: "C",
  professionalism: "PR",
};

const CATEGORY_LABELS: Record<CategoryKey, string> = {
  opening: "Opening",
  pitch_delivery: "Pitch",
  objection_handling: "Objection Handling",
  closing_technique: "Closing",
  professionalism: "Professionalism",
};

const POSITIVE_SIGNALS = new Set([
  "acknowledges_concern",
  "builds_rapport",
  "explains_value",
  "provides_proof",
  "reduces_pressure",
  "personalizes_pitch",
  "invites_dialogue",
]);

const NEGATIVE_SIGNALS = new Set([
  "pushes_close",
  "dismisses_concern",
  "ignores_objection",
  "high_difficulty_backfire",
]);
const SCORECARD_FETCH_TIMEOUT_MS = 20_000;
const SCORECARD_POLL_LIMIT = 10;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function titleCase(value: string): string {
  return value
    .replace(/_/g, " ")
    .split(" ")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function scoreValue(value: CategoryScoreDetail | undefined): number {
  if (value && typeof value.score === "number") {
    return clamp(value.score, 0, 10);
  }
  return 0;
}

function hasNumericScore(value: number | null | undefined): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function scoreBand(score: number) {
  if (score < 5) return { bg: colors.dangerSoft, text: colors.danger, border: "rgba(180, 35, 24, 0.2)" };
  if (score < 8) return { bg: colors.warningSoft, text: colors.warning, border: "rgba(180, 83, 9, 0.2)" };
  return { bg: colors.accentSoft, text: colors.accent, border: "rgba(22, 101, 52, 0.2)" };
}

function difficultyDots(difficulty: number) {
  return Array.from({ length: 5 }, (_, index) => index < clamp(Math.round(difficulty), 0, 5));
}

function formatTurnLabel(turnId: string, turnIndexById: Record<string, number>): string {
  const turnIndex = turnIndexById[turnId];
  return typeof turnIndex === "number" ? `Turn ${turnIndex}` : `Turn ${turnId.slice(0, 4)}`;
}

export function shouldPollScorecard(detail: RepSessionDetail): boolean {
  if (detail.scorecard && detail.grading_meta?.status !== "processing") {
    return false;
  }
  if (detail.grading_meta?.status === "processing") {
    return true;
  }
  return detail.session.status === "processing" && !detail.scorecard;
}

export function shouldRetryScorecardLoadError(
  message: string,
  detail: RepSessionDetail | null,
  pollCount: number
): boolean {
  return message === "Request timed out" && pollCount < SCORECARD_POLL_LIMIT && (!detail || shouldPollScorecard(detail));
}

export function heroStateFor(scorecard: RepSessionDetail["scorecard"], gradingMeta?: GradingMeta | null): HeroState {
  if (gradingMeta?.status === "processing" && !scorecard) {
    return "processing";
  }
  if (gradingMeta?.status === "no_rep_speech") {
    return "no_rep_speech";
  }
  if (scorecard && gradingMeta?.provisional) {
    return "provisional";
  }
  if (scorecard) {
    return "final";
  }
  return "unavailable";
}

function heroStateLabel(heroState: HeroState): string {
  if (heroState === "processing") return "Processing";
  if (heroState === "provisional") return "Provisional";
  if (heroState === "no_rep_speech") return "No Rep Speech";
  if (heroState === "final") return "Final";
  return "Unavailable";
}

function heroStateMessage(heroState: HeroState, gradingMeta?: GradingMeta | null): string {
  if (gradingMeta?.message) {
    return gradingMeta.message;
  }
  if (heroState === "processing") {
    return "We are grounding your scorecard in the playbook and transcript evidence.";
  }
  if (heroState === "provisional") {
    return "This grade is usable now, but the evidence quality leaves room for recalibration.";
  }
  if (heroState === "no_rep_speech") {
    return "No meaningful rep speech was captured, so the score stays at zero.";
  }
  if (heroState === "final") {
    return "Your scorecard is locked to the current transcript evidence.";
  }
  return "This session does not have a scorecard yet.";
}

export function techniqueBuckets(checks: TechniqueCheck[]) {
  const landed = checks.filter((item) => item.kind === "reward" && (item.status === "hit" || item.status === "partial"));
  const missed = checks.filter(
    (item) => (item.kind === "reward" && item.status === "miss") || (item.kind === "cap" && item.status === "hit")
  );
  return {
    landed: landed.slice(0, 3),
    missed: missed.slice(0, 3),
  };
}

function hasMeaningfulDetail(detail?: CategoryScoreDetail): boolean {
  if (!detail?.rationale_summary || !detail.rationale_detail) {
    return false;
  }
  return (
    detail.rationale_detail.trim() !== detail.rationale_summary.trim() &&
    detail.rationale_detail.length > detail.rationale_summary.length + 20
  );
}

function hasDeepDive(detail?: CategoryScoreDetail): boolean {
  return Boolean(
    detail?.rationale_summary ||
      detail?.rationale_detail ||
      detail?.improvement_target ||
      detail?.behavioral_signals?.length ||
      detail?.evidence_turn_ids?.length
  );
}

function emotionTone(emotion: string | null | undefined) {
  const normalized = String(emotion ?? "").trim().toLowerCase();
  if (normalized === "hostile") {
    return { bg: colors.dangerSoft, text: colors.danger, border: "rgba(180, 35, 24, 0.2)" };
  }
  if (normalized === "annoyed") {
    return { bg: colors.warningSoft, text: colors.warning, border: "rgba(180, 83, 9, 0.2)" };
  }
  if (normalized === "skeptical") {
    return { bg: "rgba(217, 119, 6, 0.08)", text: "#9A6700", border: "rgba(217, 119, 6, 0.18)" };
  }
  if (normalized === "neutral") {
    return { bg: "rgba(108, 98, 85, 0.12)", text: colors.muted, border: "rgba(108, 98, 85, 0.16)" };
  }
  return { bg: colors.accentSoft, text: colors.accent, border: "rgba(22, 101, 52, 0.18)" };
}

function formatTranscriptForShare(transcript: TranscriptTurn[], scenarioName: string, startedAt?: string | null) {
  const dateLabel = startedAt ? new Date(startedAt).toLocaleDateString() : new Date().toLocaleDateString();
  const blocks = transcript
    .map((turn) => {
      const lines = [`Turn ${turn.turn_index}`];
      if (turn.rep_text.trim()) {
        lines.push(`You: ${turn.rep_text.trim()}`);
      }
      if (turn.ai_text.trim()) {
        lines.push(`Homeowner: ${turn.ai_text.trim()}`);
      }
      return lines.join("\n");
    })
    .join("\n\n");

  return `[DoorDrill Transcript] ${scenarioName} — ${dateLabel}\n\n${blocks}`;
}

function ShimmerBlock({
  height,
  width = "100%",
  style,
}: {
  height: number;
  width?: number | string;
  style?: StyleProp<ViewStyle>;
}) {
  const shimmerProgress = useSharedValue(0);
  const sizeStyle: ViewStyle = { height, width: width as ViewStyle["width"] };

  useEffect(() => {
    shimmerProgress.value = withRepeat(withTiming(1, { duration: 1250 }), -1, false);
  }, [shimmerProgress]);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: interpolate(shimmerProgress.value, [0, 1], [-220, 220]) }],
  }));

  return (
    <View style={[styles.skeletonBlock, sizeStyle, style]}>
      <Animated.View style={[styles.skeletonShimmerRail, animatedStyle]}>
        <LinearGradient
          colors={["transparent", "rgba(255,255,255,0.6)", "transparent"]}
          start={{ x: 0, y: 0.5 }}
          end={{ x: 1, y: 0.5 }}
          style={styles.skeletonShimmer}
        />
      </Animated.View>
    </View>
  );
}

function LoadingSkeleton() {
  return (
    <ScrollView contentContainerStyle={styles.loadingContent} showsVerticalScrollIndicator={false}>
      <View style={styles.loadingCard}>
        <Text style={styles.loadingText}>Pulling your scorecard...</Text>
      </View>

      <View style={styles.heroBlock}>
        <ShimmerBlock height={160} width={160} style={styles.heroSkeletonOrb} />
        <ShimmerBlock height={4} style={styles.heroSkeletonTrack} />
        <ShimmerBlock height={18} width={180} style={styles.heroSkeletonLabel} />
      </View>

      <View style={styles.tabSwitcherShell}>
        <View style={styles.tabSwitcherTrack}>
          <ShimmerBlock height={44} width="50%" style={styles.tabSkeletonIndicator} />
        </View>
      </View>

      <Text style={styles.sectionTitle}>PERFORMANCE BREAKDOWN</Text>
      <View style={styles.categoriesContainer}>
        {Array.from({ length: 5 }, (_, index) => (
          <View key={`skeleton-${index}`} style={styles.categoryRow}>
            <View style={styles.categoryHeader}>
              <ShimmerBlock height={14} width="38%" />
              <ShimmerBlock height={14} width={42} />
            </View>
            <ShimmerBlock height={6} style={styles.track} />
            {index === 1 ? (
              <View style={styles.loadingExpandedCard}>
                <ShimmerBlock height={12} width="92%" />
                <ShimmerBlock height={12} width="68%" />
                <ShimmerBlock height={28} width={180} style={styles.loadingExpandedChip} />
              </View>
            ) : null}
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

function ExpandableCategoryBar({
  label,
  score,
  detail,
  index,
  expanded,
  onPress,
  onEvidencePress,
  turnIndexById,
}: {
  label: string;
  score: number;
  detail?: CategoryScoreDetail;
  index: number;
  expanded: boolean;
  onPress: () => void;
  onEvidencePress: (turnId: string) => void;
  turnIndexById: Record<string, number>;
}) {
  const widthAnim = useRef(new RNAnimated.Value(0)).current;
  const expandProgress = useSharedValue(expanded ? 1 : 0);
  const detailProgress = useSharedValue(0);
  const [showFullDetail, setShowFullDetail] = useState(false);
  const band = scoreBand(score);

  const summaryText = detail?.rationale_summary ?? detail?.rationale_detail ?? "";
  const showMoreLink = hasMeaningfulDetail(detail);
  const hasSignals = Boolean(detail?.behavioral_signals?.length);
  const hasEvidence = Boolean(detail?.evidence_turn_ids?.length);
  const improvementTarget = detail?.improvement_target ?? null;
  const canExpand = hasDeepDive(detail);

  const baseExpandedHeight =
    (summaryText ? 64 : 0) +
    (showMoreLink ? 24 : 0) +
    (improvementTarget ? 44 : 0) +
    (hasSignals ? 68 : 0) +
    (hasEvidence ? 42 : 0) +
    (canExpand ? 20 : 0);
  const fullDetailHeight = showMoreLink && detail?.rationale_detail ? 112 : 0;

  useEffect(() => {
    RNAnimated.timing(widthAnim, {
      toValue: (score / 10) * 100,
      duration: 700,
      delay: index * 100,
      useNativeDriver: false,
    }).start();
  }, [index, score, widthAnim]);

  useEffect(() => {
    expandProgress.value = withSpring(expanded ? 1 : 0, { damping: 18, stiffness: 180 });
    if (!expanded) {
      setShowFullDetail(false);
    }
  }, [expandProgress, expanded]);

  useEffect(() => {
    detailProgress.value = withSpring(showFullDetail ? 1 : 0, { damping: 18, stiffness: 180 });
  }, [detailProgress, showFullDetail]);

  const expandedStyle = useAnimatedStyle(() => ({
    maxHeight: (baseExpandedHeight + fullDetailHeight * detailProgress.value) * expandProgress.value,
    opacity: expandProgress.value,
    marginTop: canExpand ? 8 * expandProgress.value : 0,
  }));

  const detailStyle = useAnimatedStyle(() => ({
    maxHeight: fullDetailHeight * detailProgress.value,
    opacity: detailProgress.value,
  }));

  return (
    <Animated.View entering={FadeInDown.delay(240 + index * 90).springify()} style={styles.categoryRow}>
      <Pressable
        onPress={canExpand ? onPress : undefined}
        disabled={!canExpand}
        style={({ pressed }) => [styles.categoryPressable, pressed && canExpand ? styles.categoryPressablePressed : null]}
      >
        <View style={styles.categoryHeader}>
          <Text style={styles.categoryName}>{label}</Text>
          <View style={styles.categoryRight}>
            <Text style={[styles.categoryScore, { color: band.text }]}>{score.toFixed(1)}</Text>
            {canExpand ? (
              expanded ? <ChevronUp size={15} color={colors.muted} /> : <ChevronDown size={15} color={colors.muted} />
            ) : null}
          </View>
        </View>
        <View style={styles.track}>
          <RNAnimated.View
            style={[
              styles.trackFill,
              {
                backgroundColor: band.text,
                width: widthAnim.interpolate({ inputRange: [0, 100], outputRange: ["0%", "100%"] }),
              },
            ]}
          />
        </View>
      </Pressable>

      <Animated.View style={[styles.categoryExpandedWrap, expandedStyle]}>
        {expanded && canExpand ? (
          <Animated.View entering={FadeInDown.duration(220)} style={styles.categoryExpandedInner}>
            {summaryText ? (
              <View style={styles.categoryRationaleRow}>
                <Text style={styles.categoryRationaleText}>{summaryText}</Text>
                {showMoreLink ? (
                  <>
                    <Pressable onPress={() => setShowFullDetail((current) => !current)} hitSlop={8}>
                      <Text style={styles.moreLink}>{showFullDetail ? "Less" : "More"}</Text>
                    </Pressable>
                    <Animated.View style={[styles.categoryDetailWrap, detailStyle]}>
                      {detail?.rationale_detail ? <Text style={styles.categoryDetailText}>{detail.rationale_detail}</Text> : null}
                    </Animated.View>
                  </>
                ) : null}
              </View>
            ) : null}

            {improvementTarget ? (
              <View style={styles.improvementChip}>
                <ArrowRight size={12} color={colors.warning} />
                <Text style={styles.improvementChipText}>{improvementTarget}</Text>
              </View>
            ) : null}

            {hasSignals ? (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.signalChipRow}>
                {(detail?.behavioral_signals ?? []).map((signal) => {
                  const normalizedSignal = String(signal);
                  const positive = POSITIVE_SIGNALS.has(normalizedSignal);
                  const negative = NEGATIVE_SIGNALS.has(normalizedSignal);

                  return (
                    <View
                      key={`${label}-${normalizedSignal}`}
                      style={[
                        styles.signalChip,
                        positive ? styles.signalChipPositive : null,
                        negative ? styles.signalChipNegative : null,
                        !positive && !negative ? styles.signalChipNeutral : null,
                      ]}
                    >
                      <Text
                        style={[
                          styles.signalChipText,
                          positive ? styles.signalChipTextPositive : null,
                          negative ? styles.signalChipTextNegative : null,
                          !positive && !negative ? styles.signalChipTextNeutral : null,
                        ]}
                      >
                        {titleCase(normalizedSignal)}
                      </Text>
                    </View>
                  );
                })}
              </ScrollView>
            ) : null}

            {hasEvidence ? (
              <View style={styles.evidenceRow}>
                <Text style={styles.evidencePrefix}>Evidence:</Text>
                <View style={styles.evidenceLinks}>
                  {(detail?.evidence_turn_ids ?? []).map((turnId) => (
                    <Pressable key={turnId} onPress={() => onEvidencePress(turnId)} hitSlop={8}>
                      <Text style={styles.evidenceLink}>{formatTurnLabel(turnId, turnIndexById)}</Text>
                    </Pressable>
                  ))}
                </View>
              </View>
            ) : null}
          </Animated.View>
        ) : null}
      </Animated.View>
    </Animated.View>
  );
}

function TranscriptTurnCard({
  turn,
  evidenceLabels,
  focused,
  onLayout,
}: {
  turn: TranscriptTurn;
  evidenceLabels: string[];
  focused: boolean;
  onLayout: (y: number) => void;
}) {
  const repText = turn.rep_text.trim();
  const aiText = turn.ai_text.trim();
  if (!repText && !aiText) {
    return null;
  }
  const emotion = turn.emotion ? emotionTone(turn.emotion) : null;

  return (
    <Animated.View
      entering={FadeInDown.springify()}
      onLayout={(event) => onLayout(event.nativeEvent.layout.y)}
      style={styles.transcriptEntry}
    >
      <Text style={styles.turnDivider}>{`Turn ${turn.turn_index}`}</Text>
      {turn.stage || emotion ? (
        <View style={styles.turnMetaRow}>
          {turn.stage ? <Text style={styles.transcriptStage}>{titleCase(turn.stage)}</Text> : null}
          {emotion ? (
            <View style={[styles.emotionChip, { backgroundColor: emotion.bg, borderColor: emotion.border }]}>
              <Text style={[styles.emotionChipText, { color: emotion.text }]}>{titleCase(turn.emotion ?? "")}</Text>
            </View>
          ) : null}
        </View>
      ) : null}

      {repText ? (
        <View style={[styles.transcriptBubbleRow, styles.transcriptBubbleRowRep]}>
          <View
            style={[
              styles.transcriptBubble,
              styles.transcriptBubbleRep,
              evidenceLabels.length > 0 ? styles.transcriptEvidenceBubble : null,
              focused ? styles.transcriptFocusedBubble : null,
            ]}
          >
            <View style={styles.transcriptBubbleHeader}>
              <Text style={styles.transcriptBubbleSpeaker}>You</Text>
            </View>
            <Text style={styles.transcriptText}>{repText}</Text>
            {evidenceLabels.length > 0 ? (
              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.transcriptEvidenceChipRow}>
                {evidenceLabels.map((label) => (
                  <View key={`${turn.turn_id}-${label}`} style={[styles.signalChip, styles.signalChipPositive]}>
                    <Text style={[styles.signalChipText, styles.signalChipTextPositive]}>{label}</Text>
                  </View>
                ))}
              </ScrollView>
            ) : null}
          </View>
        </View>
      ) : null}

      {aiText ? (
        <View style={[styles.transcriptBubbleRow, styles.transcriptBubbleRowAi]}>
          <View style={[styles.transcriptBubble, styles.transcriptBubbleAi]}>
            <View style={styles.transcriptBubbleHeader}>
              <Text style={styles.transcriptBubbleSpeaker}>Homeowner</Text>
            </View>
            <Text style={styles.transcriptText}>{aiText}</Text>
          </View>
        </View>
      ) : null}
    </Animated.View>
  );
}

export function ScoreScreen({ route, navigation }: Props) {
  const { repId } = useSession();
  const { sessionId, isFirstDrill = false } = route.params;
  const [data, setData] = useState<RepSessionDetail | null>(null);
  const [plan, setPlan] = useState<RepPlan | null>(null);
  const [progress, setProgress] = useState<RepProgress | null>(null);
  const [scenario, setScenario] = useState<ScenarioBrief | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [processingFallback, setProcessingFallback] = useState(false);
  const [pollCount, setPollCount] = useState(0);
  const [activeTab, setActiveTab] = useState<TabKey>("scorecard");
  const [expandedCategoryKey, setExpandedCategoryKey] = useState<CategoryKey | null>(null);
  const [focusedTranscriptTurnId, setFocusedTranscriptTurnId] = useState<string | null>(null);
  const [pendingTranscriptTurnId, setPendingTranscriptTurnId] = useState<string | null>(null);
  const [tabSwitcherWidth, setTabSwitcherWidth] = useState(0);

  const heroBarAnim = useRef(new RNAnimated.Value(0)).current;
  const celebratedPersonalBestRef = useRef<string | null>(null);
  const transcriptScrollRef = useRef<ScrollView | null>(null);
  const transcriptTurnOffsetsRef = useRef<Record<string, number>>({});

  const tabIndicatorOffset = useSharedValue(0);
  const tabIndicatorWidth = useSharedValue(0);

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
        const result = await fetchRepSession(repId, sessionId, { timeoutMs: SCORECARD_FETCH_TIMEOUT_MS });
        if (cancelled) return;
        setData(result);
        setProcessingFallback(false);
        setError(null);

        if (result.session.scenario_id && !scenario) {
          const scenarioResult = await fetchRepScenario(repId, result.session.scenario_id);
          if (!cancelled) setScenario(scenarioResult);
        }

        if (shouldPollScorecard(result) && pollCount < SCORECARD_POLL_LIMIT) {
          retryTimer = setTimeout(() => {
            if (!cancelled) setPollCount((current) => current + 1);
          }, 2000);
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to load scorecard";
        const shouldRetryAsProcessing = shouldRetryScorecardLoadError(message, data, pollCount);
        if (!cancelled && shouldRetryAsProcessing) {
          setProcessingFallback(true);
          setError(null);
          retryTimer = setTimeout(() => {
            if (!cancelled) setPollCount((current) => current + 1);
          }, 2000);
        } else if (!cancelled && pollCount === 0) {
          setError(message);
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
  }, [pollCount, repId, scenario, sessionId]);

  const scorecard = data?.scorecard;
  const gradingMeta = data?.grading_meta ?? null;
  const transcript = data?.transcript ?? [];
  const overallScore = hasNumericScore(scorecard?.overall_score) ? scorecard.overall_score : null;
  const overallBand = scoreBand(overallScore ?? 0);
  const heroState = processingFallback && !scorecard ? "processing" : heroStateFor(scorecard ?? null, gradingMeta);
  const managerNote = data?.manager_coaching_note?.note ?? data?.manager_note ?? data?.manager_review?.notes ?? null;
  const improvementTargets = scorecard?.improvement_targets ?? [];
  const highlights = (scorecard?.highlights ?? []).slice(0, 4);
  const weaknessTags = scorecard?.weakness_tags ?? [];
  const { landed: landedChecks, missed: missedChecks } = techniqueBuckets(scorecard?.technique_checks ?? []);
  const nextScenarioSuggestion = plan?.next_scenario_suggestion ?? null;
  const focusSkills = plan?.focus_skills ?? [];
  const personalBestScore = progress?.personal_best ?? null;
  const showPersonalBestBanner = Boolean(
    scorecard &&
      hasNumericScore(overallScore) &&
      heroState !== "no_rep_speech" &&
      progress &&
      (personalBestScore === null || overallScore >= personalBestScore)
  );
  const showFirstDrillCongrats = Boolean(isFirstDrill && scorecard && heroState !== "processing");
  const mostImprovedBadge =
    progress?.most_improved_category && typeof progress.most_improved_delta === "number" && progress.most_improved_delta > 1
      ? {
          label: CATEGORY_LABELS[progress.most_improved_category as CategoryKey] ?? titleCase(progress.most_improved_category),
          delta: progress.most_improved_delta,
        }
      : null;

  const readinessHint = useMemo(() => {
    if (!plan) {
      return null;
    }

    for (const skill of plan.focus_skills) {
      const trajectory = plan.readiness_trajectory?.[skill];
      const remaining = trajectory?.sessions_to_readiness;
      if (typeof remaining === "number" && remaining > 0 && remaining <= 20) {
        return {
          skillLabel: titleCase(skill),
          remaining,
        };
      }
    }

    return null;
  }, [plan]);

  useEffect(() => {
    if (scorecard && hasNumericScore(overallScore)) {
      RNAnimated.timing(heroBarAnim, {
        toValue: (overallScore / 10) * 100,
        duration: 800,
        useNativeDriver: false,
      }).start();
    }
  }, [heroBarAnim, overallScore, scorecard]);

  useEffect(() => {
    if (!scorecard) {
      setExpandedCategoryKey(null);
    }
  }, [scorecard]);

  useEffect(() => {
    let cancelled = false;

    async function loadPlan() {
      if (!repId) {
        return;
      }

      try {
        const result = await fetchRepPlan(repId);
        if (!cancelled) {
          setPlan(result);
        }
      } catch {
        if (!cancelled) {
          setPlan(null);
        }
      }
    }

    void loadPlan();

    return () => {
      cancelled = true;
    };
  }, [repId]);

  useEffect(() => {
    let cancelled = false;

    async function loadProgress() {
      if (!repId) {
        return;
      }

      try {
        const result = await fetchRepProgress(repId);
        if (!cancelled) {
          setProgress(result);
        }
      } catch {
        if (!cancelled) {
          setProgress(null);
        }
      }
    }

    void loadProgress();

    return () => {
      cancelled = true;
    };
  }, [repId]);

  useEffect(() => {
    if (!showPersonalBestBanner || !scorecard?.id || celebratedPersonalBestRef.current === scorecard.id) {
      return;
    }

    celebratedPersonalBestRef.current = scorecard.id;
    void Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
  }, [scorecard?.id, showPersonalBestBanner]);

  useEffect(() => {
    const width = Math.max(0, (tabSwitcherWidth - 8) / 2);
    tabIndicatorWidth.value = withSpring(width, { damping: 18, stiffness: 180 });
    tabIndicatorOffset.value = withSpring(activeTab === "scorecard" ? 0 : width, { damping: 18, stiffness: 180 });
  }, [activeTab, tabIndicatorOffset, tabIndicatorWidth, tabSwitcherWidth]);

  function scrollToTranscriptTurn(turnId: string) {
    const offset = transcriptTurnOffsetsRef.current[turnId];
    if (typeof offset !== "number") {
      return false;
    }
    transcriptScrollRef.current?.scrollTo({ y: Math.max(0, offset - 20), animated: true });
    setPendingTranscriptTurnId(null);
    return true;
  }

  useEffect(() => {
    if (activeTab !== "transcript" || !pendingTranscriptTurnId) {
      return;
    }

    const timer = setTimeout(() => {
      scrollToTranscriptTurn(pendingTranscriptTurnId);
    }, 160);

    return () => clearTimeout(timer);
  }, [activeTab, pendingTranscriptTurnId, transcript.length]);

  const tabIndicatorStyle = useAnimatedStyle(() => ({
    width: tabIndicatorWidth.value,
    transform: [{ translateX: tabIndicatorOffset.value }],
  }));

  const turnIndexById = useMemo<Record<string, number>>(
    () =>
      transcript.reduce<Record<string, number>>((accumulator, turn) => {
        accumulator[turn.turn_id] = turn.turn_index;
        return accumulator;
      }, {}),
    [transcript]
  );

  const evidenceLabelsByTurnId = useMemo<Record<string, string[]>>(() => {
    const labelsByTurnId: Record<string, string[]> = {};

    function addLabel(turnId: string, label: string) {
      if (!turnId) {
        return;
      }
      if (!labelsByTurnId[turnId]) {
        labelsByTurnId[turnId] = [];
      }
      if (!labelsByTurnId[turnId].includes(label)) {
        labelsByTurnId[turnId].push(label);
      }
    }

    for (const turnId of scorecard?.evidence_turn_ids ?? []) {
      addLabel(turnId, "Overall");
    }

    for (const category of CATEGORY_ORDER) {
      const evidenceTurnIds = scorecard?.category_scores?.[category.key]?.evidence_turn_ids ?? [];
      for (const turnId of evidenceTurnIds) {
        addLabel(turnId, category.label);
      }
    }

    return labelsByTurnId;
  }, [scorecard]);

  const categories = useMemo<CategoryRow[]>(() => {
    const categoryScores = scorecard?.category_scores ?? {};
    return CATEGORY_ORDER.map((category) => ({
      ...category,
      detail: categoryScores[category.key],
      score: scoreValue(categoryScores[category.key]),
    }));
  }, [scorecard]);

  const transcriptShareText = useMemo(
    () => formatTranscriptForShare(transcript, scenario?.name ?? "Scenario", data?.session.started_at),
    [data?.session.started_at, scenario?.name, transcript]
  );

  async function handleShareTranscript() {
    if (!transcript.length) {
      return;
    }

    try {
      await Share.share({
        title: `${scenario?.name ?? "DoorDrill"} Transcript`,
        message: transcriptShareText,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to share transcript");
    }
  }

  function handleEvidencePress(turnId: string) {
    setFocusedTranscriptTurnId(turnId);
    setPendingTranscriptTurnId(turnId);
    setActiveTab("transcript");
    if (activeTab === "transcript") {
      requestAnimationFrame(() => {
        scrollToTranscriptTurn(turnId);
      });
    }
  }

  function renderScorecardTab() {
    if (!scorecard) {
      return (
        <View style={styles.emptyStateCard}>
          {heroState === "processing" || refreshing ? <ActivityIndicator color={colors.accent} /> : null}
          <Text style={styles.emptyStateTitle}>{heroState === "processing" || refreshing ? "Grading in progress" : "Scorecard not available"}</Text>
          <Text style={styles.emptyStateText}>
            {heroStateMessage(heroState, gradingMeta)}
          </Text>
        </View>
      );
    }

    return (
      <>
        <Text style={styles.sectionTitle}>PERFORMANCE BREAKDOWN</Text>
        {mostImprovedBadge ? (
          <Animated.View entering={FadeInDown.delay(300).springify()} style={styles.mostImprovedBadgeWrap}>
            <View style={styles.mostImprovedBadge}>
              <TrendingUp size={14} color={colors.accent} />
              <Text style={styles.mostImprovedBadgeText}>
                {`Most improved: ${mostImprovedBadge.label} +${mostImprovedBadge.delta.toFixed(1)} vs your first sessions`}
              </Text>
            </View>
          </Animated.View>
        ) : null}
        <BlurView intensity={40} tint="light" style={styles.categoriesContainer}>
          {categories.map((category, index) => (
            <ExpandableCategoryBar
              key={category.key}
              label={category.label}
              score={category.score}
              detail={category.detail}
              index={index}
              expanded={expandedCategoryKey === category.key}
              onPress={() => setExpandedCategoryKey((current) => (current === category.key ? null : category.key))}
              onEvidencePress={handleEvidencePress}
              turnIndexById={turnIndexById}
            />
          ))}
        </BlurView>

        {readinessHint ? (
          <Animated.View entering={FadeInDown.delay(480).springify()} style={styles.readinessHintWrap}>
            <Text style={styles.readinessHintText}>
              {`At this rate, you'll hit target on ${readinessHint.skillLabel} in ~${readinessHint.remaining} more drills`}
            </Text>
          </Animated.View>
        ) : null}

        {(landedChecks.length > 0 || missedChecks.length > 0) ? (
          <>
            <Text style={styles.sectionTitle}>PLAYBOOK CHECKS</Text>
            <BlurView intensity={40} tint="light" style={styles.techniqueSummaryCard}>
              {landedChecks.length > 0 ? (
                <View style={styles.techniqueSummaryBlock}>
                  <Text style={styles.techniqueSummaryHeading}>What Landed</Text>
                  {landedChecks.map((item) => (
                    <Pressable
                      key={item.id}
                      onPress={() => item.evidence_turn_ids[0] ? handleEvidencePress(item.evidence_turn_ids[0]) : undefined}
                      disabled={!item.evidence_turn_ids[0]}
                      style={({ pressed }) => [styles.techniqueRow, pressed ? styles.techniqueRowPressed : null]}
                    >
                      <View style={[styles.techniqueDot, styles.techniqueDotPositive]} />
                      <View style={styles.techniqueTextWrap}>
                        <Text style={styles.techniqueLabel}>{item.label}</Text>
                        <Text style={styles.techniqueStatus}>
                          {item.evidence_turn_ids[0]
                            ? `${item.status === "partial" ? "Partially landed" : "Supported"} · ${formatTurnLabel(item.evidence_turn_ids[0], turnIndexById)}`
                            : item.status === "partial"
                              ? "Partially landed"
                              : "Supported"}
                        </Text>
                      </View>
                    </Pressable>
                  ))}
                </View>
              ) : null}

              {missedChecks.length > 0 ? (
                <View style={styles.techniqueSummaryBlock}>
                  <Text style={styles.techniqueSummaryHeading}>What Missed</Text>
                  {missedChecks.map((item) => (
                    <Pressable
                      key={item.id}
                      onPress={() => item.evidence_turn_ids[0] ? handleEvidencePress(item.evidence_turn_ids[0]) : undefined}
                      disabled={!item.evidence_turn_ids[0]}
                      style={({ pressed }) => [styles.techniqueRow, pressed ? styles.techniqueRowPressed : null]}
                    >
                      <View style={[styles.techniqueDot, styles.techniqueDotNegative]} />
                      <View style={styles.techniqueTextWrap}>
                        <Text style={styles.techniqueLabel}>{item.label}</Text>
                        <Text style={styles.techniqueStatus}>
                          {item.evidence_turn_ids[0]
                            ? `Coach this next · ${formatTurnLabel(item.evidence_turn_ids[0], turnIndexById)}`
                            : "Coach this next"}
                        </Text>
                      </View>
                    </Pressable>
                  ))}
                </View>
              ) : null}
            </BlurView>
          </>
        ) : null}

        {improvementTargets.length > 0 ? (
          <>
            <Text style={styles.sectionTitle}>WHAT TO WORK ON</Text>
            <Text style={styles.sectionSubtitle}>Focus on these in your next drill</Text>
            <BlurView intensity={40} tint="light" style={styles.categoriesContainer}>
              {improvementTargets.slice(0, 3).map((target, index) => {
                const band = scoreBand(target.score);
                const categoryKey = target.category as CategoryKey;
                const initials = CATEGORY_INITIALS[categoryKey] ?? target.label.slice(0, 2).toUpperCase();

                return (
                  <Animated.View
                    key={`${target.category}-${index}`}
                    entering={FadeInDown.delay(520 + index * 90).springify()}
                    style={styles.improvementRow}
                  >
                    <View style={[styles.improvementInitial, { backgroundColor: band.bg, borderColor: band.border }]}>
                      <Text style={[styles.improvementInitialText, { color: band.text }]}>{initials}</Text>
                    </View>
                    <View style={styles.improvementBody}>
                      <Text style={styles.improvementLabel}>{target.label}</Text>
                      <Text style={styles.improvementTarget}>{target.target}</Text>
                    </View>
                    <View style={[styles.scoreBadge, { backgroundColor: band.bg, borderColor: band.border }]}>
                      <Text style={[styles.scoreBadgeText, { color: band.text }]}>{target.score.toFixed(1)}</Text>
                    </View>
                  </Animated.View>
                );
              })}
            </BlurView>
          </>
        ) : null}

        <Text style={styles.sectionTitle}>KEY MOMENTS</Text>
        {highlights.length === 0 ? <Text style={styles.emptyText}>No highlights available.</Text> : null}
        {highlights.map((highlight, index) => {
          const isStrong = highlight.type === "strong";
          const highlightBand = isStrong ? scoreBand(8.2) : scoreBand(6.2);
          const quote = highlight.transcript_quote || highlight.quote || null;

          return (
            <Animated.View
              key={`${highlight.type}-${index}`}
              entering={FadeInDown.delay(700 + index * 100).springify()}
              style={styles.highlightCardWrapper}
            >
              <BlurView intensity={40} tint="light" style={styles.highlightCard}>
                <View style={styles.highlightHeader}>
                  <View style={[styles.highlightTag, { backgroundColor: highlightBand.bg, borderColor: highlightBand.border }]}>
                    <Text style={[styles.highlightTagText, { color: highlightBand.text }]}>{isStrong ? "Strong" : "Improve"}</Text>
                  </View>
                  {highlight.turn_id ? <Text style={styles.turnRef}>{formatTurnLabel(highlight.turn_id, turnIndexById)}</Text> : null}
                </View>
                <Text style={styles.highlightNote}>{highlight.note}</Text>
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

        {weaknessTags.length > 0 ? (
          <>
            <Text style={styles.sectionTitle}>AREAS TO WATCH</Text>
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.weaknessScroll}>
              {weaknessTags.map((tag) => (
                <View key={tag} style={styles.weaknessChip}>
                  <Text style={styles.weaknessChipText}>{titleCase(tag)}</Text>
                </View>
              ))}
            </ScrollView>
          </>
        ) : null}

        {nextScenarioSuggestion && focusSkills.length > 0 ? (
          <Animated.View entering={FadeInDown.delay(1180).springify()} style={styles.nextDrillWrapper}>
            <BlurView intensity={40} tint="light" style={styles.nextDrillCard}>
              <Text style={styles.sectionTitleCompact}>RECOMMENDED NEXT DRILL</Text>
              <Text style={styles.nextDrillName}>{nextScenarioSuggestion.name}</Text>

              <View style={styles.difficultyDotsRow}>
                {difficultyDots(nextScenarioSuggestion.difficulty || plan?.recommended_difficulty || 1).map((filled, index) => (
                  <View
                    key={`difficulty-dot-${index}`}
                    style={[
                      styles.difficultyDot,
                      filled ? styles.difficultyDotFilled : styles.difficultyDotEmpty,
                    ]}
                  />
                ))}
              </View>

              <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.nextDrillSkillsRow}>
                {focusSkills.map((skill) => (
                  <View key={skill} style={[styles.signalChip, styles.signalChipPositive]}>
                    <Text style={[styles.signalChipText, styles.signalChipTextPositive]}>{titleCase(skill)}</Text>
                  </View>
                ))}
              </ScrollView>

              <Text style={styles.nextDrillReason}>{nextScenarioSuggestion.reason}</Text>

              <Pressable
                disabled={!nextScenarioSuggestion.scenario_id}
                style={({ pressed }) => [
                  styles.nextDrillButton,
                  !nextScenarioSuggestion.scenario_id ? styles.nextDrillButtonDisabled : null,
                  pressed && nextScenarioSuggestion.scenario_id ? styles.nextDrillButtonPressed : null,
                ]}
                onPress={() => {
                  if (!nextScenarioSuggestion.scenario_id) {
                    return;
                  }
                  navigation.navigate("PreSession", { scenarioId: nextScenarioSuggestion.scenario_id });
                }}
              >
                <Text style={styles.nextDrillButtonText}>Start This Drill</Text>
                <ArrowRight size={16} color="#fff" />
              </Pressable>
            </BlurView>
          </Animated.View>
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
    );
  }

  function renderTranscriptTab() {
    if (loading || refreshing) {
      return (
        <View style={styles.transcriptLoadingState}>
          <ActivityIndicator color={colors.accent} />
          <Text style={styles.loadingText}>Loading transcript...</Text>
        </View>
      );
    }

    if (transcript.length === 0) {
      return (
        <View style={styles.emptyStateCard}>
          <FileText size={26} color={colors.muted} />
          <Text style={styles.emptyStateTitle}>Transcript not available for this session</Text>
          <Text style={styles.emptyStateText}>Conversation turns were not saved for this drill.</Text>
        </View>
      );
    }

    return (
      <>
        <View style={styles.transcriptTabHeader}>
          <View>
            <Text style={styles.sectionTitleCompact}>FULL TRANSCRIPT</Text>
            <Text style={styles.sectionSubtitle}>Evidence-highlighted moments from your drill</Text>
          </View>
          <Pressable
            style={({ pressed }) => [styles.shareButton, pressed ? styles.shareButtonPressed : null]}
            onPress={() => void handleShareTranscript()}
          >
            <Share2 size={16} color={colors.accent} />
            <Text style={styles.shareButtonText}>Share</Text>
          </Pressable>
        </View>

        <BlurView intensity={40} tint="light" style={styles.transcriptContainer}>
          {transcript.map((turn) => (
            <TranscriptTurnCard
              key={`${turn.turn_id}-${turn.turn_index}`}
              turn={turn}
              evidenceLabels={evidenceLabelsByTurnId[turn.turn_id] ?? []}
              focused={focusedTranscriptTurnId === turn.turn_id}
              onLayout={(y) => {
                transcriptTurnOffsetsRef.current[turn.turn_id] = y;
                if (pendingTranscriptTurnId === turn.turn_id && activeTab === "transcript") {
                  requestAnimationFrame(() => {
                    scrollToTranscriptTurn(turn.turn_id);
                  });
                }
              }}
            />
          ))}
        </BlurView>
      </>
    );
  }

  if (loading && !data) {
    return (
      <LinearGradient colors={["#FDFDFD", "#F7F4EE", "#EBE5D9"]} style={styles.container}>
        <SafeAreaView style={styles.safeArea}>
          <LoadingSkeleton />
        </SafeAreaView>
      </LinearGradient>
    );
  }

  return (
    <LinearGradient colors={["#FDFDFD", "#F7F4EE", "#EBE5D9"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.screenBody}>
          <View style={styles.headerShell}>
            {showFirstDrillCongrats ? (
              <Animated.View entering={FadeInDown.delay(100).springify()} style={styles.firstDrillCongrats}>
                <Text style={styles.congratsEmoji}>🎉</Text>
                <Text style={styles.congratsTitle}>First Drill Complete!</Text>
                <Text style={styles.congratsBody}>Nice work. Here&apos;s how you did.</Text>
              </Animated.View>
            ) : null}
            <View style={styles.heroBlock}>
              {hasNumericScore(overallScore) ? (
                // @ts-ignore
                <Animated.View sharedTransitionTag="ai-orb" style={[styles.heroOrb, { backgroundColor: overallBand.bg, borderColor: overallBand.border }]}>
                  <Text style={[styles.heroValue, { color: overallBand.text }]}>{overallScore.toFixed(1)}</Text>
                  <Text style={styles.heroLabel}>Overall Score</Text>
                </Animated.View>
              ) : (
                <View style={styles.heroStatusCard}>
                  {heroState === "processing" ? <ActivityIndicator color={colors.accent} /> : <FileText size={22} color={colors.muted} />}
                  <Text style={styles.heroStatusTitle}>{heroStateLabel(heroState)}</Text>
                  <Text style={styles.heroStatusMessage}>{heroStateMessage(heroState, gradingMeta)}</Text>
                </View>
              )}
              {showPersonalBestBanner ? (
                <Animated.View entering={FadeInDown.delay(180).springify()} style={styles.personalBestBannerWrap}>
                  <LinearGradient colors={["#FDE68A", "#F59E0B"]} start={{ x: 0, y: 0 }} end={{ x: 1, y: 1 }} style={styles.personalBestBanner}>
                    <Star size={14} color="#7C2D12" fill="#FDE68A" />
                    <Text style={styles.personalBestBannerText}>NEW PERSONAL BEST</Text>
                  </LinearGradient>
                </Animated.View>
              ) : null}
              {hasNumericScore(overallScore) ? (
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
              ) : null}
              <View style={styles.heroMetaRow}>
                <View style={[styles.heroMetaChip, heroState === "provisional" ? styles.heroMetaChipWarning : styles.heroMetaChipNeutral]}>
                  <Text style={[styles.heroMetaChipText, heroState === "provisional" ? styles.heroMetaChipTextWarning : null]}>
                    {heroStateLabel(heroState)}
                  </Text>
                </View>
                {typeof gradingMeta?.confidence === "number" ? (
                  <View style={styles.heroMetaChip}>
                    <Text style={styles.heroMetaChipText}>{`Confidence ${(gradingMeta.confidence * 100).toFixed(0)}%`}</Text>
                  </View>
                ) : null}
                {gradingMeta?.call_quality ? (
                  <View style={styles.heroMetaChip}>
                    <Text style={styles.heroMetaChipText}>{`${titleCase(gradingMeta.call_quality)} evidence`}</Text>
                  </View>
                ) : null}
              </View>
              <Text style={styles.scenarioName}>{scenario?.name ?? "Scenario"}</Text>
            </View>

            <View style={styles.tabSwitcherShell}>
              <View
                style={styles.tabSwitcherTrack}
                onLayout={(event) => setTabSwitcherWidth(event.nativeEvent.layout.width)}
              >
                <Animated.View style={[styles.tabIndicator, tabIndicatorStyle]} />
                <Pressable
                  style={styles.tabButton}
                  onPress={() => setActiveTab("scorecard")}
                >
                  <Text style={[styles.tabLabel, activeTab === "scorecard" ? styles.tabLabelActive : styles.tabLabelInactive]}>
                    Scorecard
                  </Text>
                </Pressable>
                <Pressable
                  style={styles.tabButton}
                  onPress={() => setActiveTab("transcript")}
                >
                  <Text style={[styles.tabLabel, activeTab === "transcript" ? styles.tabLabelActive : styles.tabLabelInactive]}>
                    Transcript
                  </Text>
                </Pressable>
              </View>
            </View>

            {error ? <Text style={styles.errorText}>{error}</Text> : null}
          </View>

          {activeTab === "scorecard" ? (
            <ScrollView contentContainerStyle={styles.tabContent} showsVerticalScrollIndicator={false}>
              {renderScorecardTab()}
            </ScrollView>
          ) : (
            <ScrollView ref={transcriptScrollRef} contentContainerStyle={styles.tabContent} showsVerticalScrollIndicator={false}>
              {renderTranscriptTab()}
            </ScrollView>
          )}
        </View>
      </SafeAreaView>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  safeArea: { flex: 1 },
  screenBody: { flex: 1 },
  headerShell: {
    paddingHorizontal: 20,
    paddingTop: 8,
  },
  firstDrillCongrats: {
    alignItems: "center",
    marginBottom: 14,
    paddingVertical: 16,
    paddingHorizontal: 18,
    borderRadius: 24,
    backgroundColor: "rgba(255, 255, 255, 0.72)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(22, 101, 52, 0.16)",
  },
  congratsEmoji: {
    fontSize: 24,
    marginBottom: 6,
  },
  congratsTitle: {
    fontSize: 22,
    lineHeight: 26,
    color: colors.ink,
    fontFamily: "Poppins_800ExtraBold",
    marginBottom: 4,
  },
  congratsBody: {
    fontSize: 14,
    lineHeight: 20,
    color: colors.muted,
    fontFamily: "Inter_400Regular",
    textAlign: "center",
  },
  tabContent: {
    paddingHorizontal: 20,
    paddingBottom: 40,
  },
  loadingContent: {
    paddingHorizontal: 20,
    paddingBottom: 40,
  },

  loadingCard: {
    marginTop: 18,
    marginBottom: 8,
    alignItems: "center",
  },
  loadingText: {
    color: colors.muted,
    fontSize: 15,
    fontFamily: "Poppins_600SemiBold",
  },
  skeletonBlock: {
    overflow: "hidden",
    borderRadius: 999,
    backgroundColor: "rgba(108, 98, 85, 0.12)",
  },
  skeletonShimmerRail: {
    ...StyleSheet.absoluteFillObject,
    width: 160,
  },
  skeletonShimmer: {
    flex: 1,
  },
  heroSkeletonOrb: {
    borderRadius: 999,
    marginBottom: 12,
  },
  heroSkeletonTrack: {
    width: "100%",
    borderRadius: 4,
  },
  heroSkeletonLabel: {
    marginTop: 16,
  },
  tabSkeletonIndicator: {
    borderRadius: 999,
  },
  loadingExpandedCard: {
    gap: 10,
    marginTop: 10,
    padding: 12,
    borderRadius: 18,
    backgroundColor: "rgba(255,255,255,0.45)",
  },
  loadingExpandedChip: {
    borderRadius: 14,
  },

  errorText: {
    color: colors.danger,
    fontSize: 14,
    fontWeight: "700",
    textAlign: "center",
    marginTop: 12,
  },

  heroBlock: {
    alignItems: "center",
    paddingTop: 12,
    marginBottom: 20,
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
  heroStatusCard: {
    width: "100%",
    borderRadius: 28,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(22, 101, 52, 0.14)",
    backgroundColor: "rgba(255,255,255,0.72)",
    paddingHorizontal: 20,
    paddingVertical: 22,
    alignItems: "center",
    gap: 8,
  },
  heroStatusTitle: {
    fontSize: 20,
    color: colors.ink,
    fontFamily: "Poppins_700Bold",
  },
  heroStatusMessage: {
    fontSize: 13,
    lineHeight: 19,
    color: colors.muted,
    textAlign: "center",
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
  personalBestBannerWrap: {
    marginBottom: 10,
  },
  personalBestBanner: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 9,
    shadowColor: "#F59E0B",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.18,
    shadowRadius: 18,
    elevation: 4,
  },
  personalBestBannerText: {
    fontSize: 12,
    color: "#7C2D12",
    fontFamily: "Poppins_800ExtraBold",
    letterSpacing: 0.6,
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
  heroMetaRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "center",
    gap: 8,
    marginTop: 12,
  },
  heroMetaChip: {
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    backgroundColor: "rgba(255,255,255,0.78)",
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  heroMetaChipWarning: {
    borderColor: "rgba(180, 83, 9, 0.24)",
    backgroundColor: colors.warningSoft,
  },
  heroMetaChipNeutral: {
    borderColor: "rgba(22, 101, 52, 0.16)",
    backgroundColor: "rgba(255,255,255,0.82)",
  },
  heroMetaChipText: {
    fontSize: 11,
    color: colors.muted,
    fontFamily: "Poppins_600SemiBold",
    letterSpacing: 0.3,
  },
  heroMetaChipTextWarning: {
    color: colors.warning,
  },

  tabSwitcherShell: {
    marginBottom: 16,
  },
  tabSwitcherTrack: {
    position: "relative",
    flexDirection: "row",
    alignItems: "center",
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    backgroundColor: "rgba(255,255,255,0.7)",
    padding: 4,
  },
  tabIndicator: {
    position: "absolute",
    left: 4,
    top: 4,
    bottom: 4,
    borderRadius: 999,
    backgroundColor: colors.accent,
  },
  tabButton: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 11,
    zIndex: 1,
  },
  tabLabel: {
    fontSize: 14,
    fontFamily: "Poppins_600SemiBold",
  },
  tabLabelActive: {
    color: "#fff",
  },
  tabLabelInactive: {
    color: colors.muted,
  },

  sectionTitle: {
    fontSize: 12,
    fontWeight: "700",
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 1,
    marginTop: 28,
    marginBottom: 8,
  },
  mostImprovedBadgeWrap: {
    marginBottom: 10,
  },
  mostImprovedBadge: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: colors.accentSoft,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(22, 101, 52, 0.2)",
  },
  mostImprovedBadgeText: {
    fontSize: 12,
    color: colors.accent,
    fontFamily: "Poppins_600SemiBold",
  },
  sectionTitleCompact: {
    fontSize: 12,
    fontWeight: "700",
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 1,
    marginBottom: 6,
  },
  sectionSubtitle: {
    fontSize: 13,
    color: colors.muted,
    lineHeight: 18,
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
  techniqueSummaryCard: {
    gap: 16,
    borderRadius: 24,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    backgroundColor: "rgba(255, 255, 255, 0.6)",
    padding: 20,
    overflow: "hidden",
  },
  techniqueSummaryBlock: {
    gap: 10,
  },
  techniqueSummaryHeading: {
    fontSize: 13,
    color: colors.ink,
    fontFamily: "Poppins_700Bold",
  },
  techniqueRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 10,
  },
  techniqueRowPressed: {
    opacity: 0.82,
  },
  techniqueDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    marginTop: 6,
  },
  techniqueDotPositive: {
    backgroundColor: colors.accent,
  },
  techniqueDotNegative: {
    backgroundColor: colors.warning,
  },
  techniqueTextWrap: {
    flex: 1,
    gap: 2,
  },
  techniqueLabel: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.ink,
    fontFamily: "Poppins_600SemiBold",
  },
  techniqueStatus: {
    fontSize: 12,
    lineHeight: 17,
    color: colors.muted,
  },
  readinessHintWrap: {
    marginTop: 10,
  },
  readinessHintText: {
    fontSize: 13,
    color: colors.muted,
    lineHeight: 19,
  },
  categoryRow: {
    gap: 6,
  },
  categoryPressable: {
    gap: 6,
  },
  categoryPressablePressed: {
    opacity: 0.85,
  },
  categoryHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  categoryName: {
    fontSize: 13,
    color: colors.ink,
    flex: 1,
  },
  categoryRight: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
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
  categoryExpandedWrap: {
    overflow: "hidden",
  },
  categoryExpandedInner: {
    gap: 12,
    paddingTop: 2,
  },
  categoryRationaleRow: {
    gap: 6,
  },
  categoryRationaleText: {
    fontSize: 12,
    lineHeight: 18,
    color: colors.muted,
  },
  moreLink: {
    fontSize: 12,
    color: colors.accent,
    fontFamily: "Poppins_600SemiBold",
  },
  categoryDetailWrap: {
    overflow: "hidden",
  },
  categoryDetailText: {
    fontSize: 13,
    lineHeight: 20,
    color: colors.ink,
    paddingTop: 2,
  },
  improvementChip: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: colors.warningSoft,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(180, 83, 9, 0.24)",
  },
  improvementChipText: {
    fontSize: 12,
    color: colors.warning,
    fontFamily: "Poppins_600SemiBold",
  },
  signalChipRow: {
    gap: 8,
    paddingRight: 12,
  },
  signalChip: {
    borderRadius: 999,
    paddingHorizontal: 10,
    paddingVertical: 7,
    borderWidth: StyleSheet.hairlineWidth,
  },
  signalChipPositive: {
    backgroundColor: colors.accentSoft,
    borderColor: "rgba(22, 101, 52, 0.2)",
  },
  signalChipNegative: {
    backgroundColor: colors.dangerSoft,
    borderColor: "rgba(180, 35, 24, 0.2)",
  },
  signalChipNeutral: {
    backgroundColor: colors.warningSoft,
    borderColor: "rgba(180, 83, 9, 0.2)",
  },
  signalChipText: {
    fontSize: 11,
    fontFamily: "Poppins_600SemiBold",
  },
  signalChipTextPositive: {
    color: colors.accent,
  },
  signalChipTextNegative: {
    color: colors.danger,
  },
  signalChipTextNeutral: {
    color: colors.warning,
  },
  evidenceRow: {
    flexDirection: "row",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 6,
  },
  evidencePrefix: {
    fontSize: 12,
    color: colors.muted,
  },
  evidenceLinks: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 10,
  },
  evidenceLink: {
    fontSize: 12,
    color: colors.accent,
    textDecorationLine: "underline",
  },

  improvementRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  improvementInitial: {
    width: 38,
    height: 38,
    borderRadius: 19,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: StyleSheet.hairlineWidth,
  },
  improvementInitialText: {
    fontSize: 12,
    fontFamily: "Poppins_700Bold",
  },
  improvementBody: {
    flex: 1,
  },
  improvementLabel: {
    fontSize: 14,
    color: colors.ink,
    fontFamily: "Poppins_600SemiBold",
  },
  improvementTarget: {
    fontSize: 13,
    color: colors.muted,
    lineHeight: 19,
    marginTop: 2,
  },
  scoreBadge: {
    minWidth: 48,
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 10,
    paddingVertical: 7,
  },
  scoreBadgeText: {
    fontSize: 12,
    fontFamily: "Poppins_700Bold",
  },

  emptyText: {
    color: colors.muted,
    fontSize: 14,
    fontStyle: "italic",
  },
  emptyStateCard: {
    marginTop: 20,
    alignItems: "center",
    justifyContent: "center",
    gap: 10,
    borderRadius: 24,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    backgroundColor: "rgba(255, 255, 255, 0.6)",
    paddingHorizontal: 24,
    paddingVertical: 32,
  },
  emptyStateTitle: {
    fontSize: 16,
    color: colors.ink,
    fontFamily: "Poppins_600SemiBold",
    textAlign: "center",
  },
  emptyStateText: {
    fontSize: 13,
    lineHeight: 19,
    color: colors.muted,
    textAlign: "center",
  },

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
    borderWidth: StyleSheet.hairlineWidth,
  },
  highlightTagText: {
    fontSize: 11,
    fontWeight: "700",
    textTransform: "uppercase",
  },
  turnRef: {
    color: colors.muted,
    fontSize: 11,
  },
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
  weaknessScroll: {
    gap: 10,
    paddingRight: 20,
  },
  weaknessChip: {
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 9,
    backgroundColor: colors.dangerSoft,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(180, 35, 24, 0.22)",
  },
  weaknessChipText: {
    color: colors.danger,
    fontSize: 12,
    fontFamily: "Poppins_600SemiBold",
  },
  nextDrillWrapper: {
    marginTop: 28,
  },
  nextDrillCard: {
    gap: 14,
    borderRadius: 24,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    backgroundColor: "rgba(255, 255, 255, 0.62)",
    padding: 22,
    overflow: "hidden",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.04,
    shadowRadius: 16,
    elevation: 3,
  },
  nextDrillName: {
    fontSize: 22,
    color: colors.ink,
    fontFamily: "Poppins_700Bold",
    lineHeight: 28,
  },
  difficultyDotsRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  difficultyDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    borderWidth: StyleSheet.hairlineWidth,
  },
  difficultyDotFilled: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  difficultyDotEmpty: {
    backgroundColor: "rgba(255,255,255,0.75)",
    borderColor: "rgba(108, 98, 85, 0.2)",
  },
  nextDrillSkillsRow: {
    gap: 8,
    paddingRight: 10,
  },
  nextDrillReason: {
    fontSize: 13,
    color: colors.muted,
    lineHeight: 20,
  },
  nextDrillButton: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: colors.accent,
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  nextDrillButtonDisabled: {
    opacity: 0.45,
  },
  nextDrillButtonPressed: {
    opacity: 0.86,
  },
  nextDrillButtonText: {
    color: "#fff",
    fontSize: 14,
    fontFamily: "Poppins_700Bold",
  },

  transcriptLoadingState: {
    paddingTop: 48,
    alignItems: "center",
    gap: 12,
  },
  transcriptTabHeader: {
    marginTop: 24,
    marginBottom: 14,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  shareButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 14,
    paddingVertical: 10,
    borderRadius: 999,
    backgroundColor: "rgba(255,255,255,0.72)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
  },
  shareButtonPressed: {
    opacity: 0.82,
  },
  shareButtonText: {
    fontSize: 12,
    color: colors.accent,
    fontFamily: "Poppins_600SemiBold",
  },
  transcriptContainer: {
    gap: 10,
    borderRadius: 24,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    backgroundColor: "rgba(255, 255, 255, 0.6)",
    padding: 20,
    overflow: "hidden",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.04,
    shadowRadius: 16,
    elevation: 3,
  },
  transcriptEntry: {
    gap: 10,
  },
  turnDivider: {
    alignSelf: "center",
    fontSize: 11,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 1,
  },
  turnMetaRow: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    flexWrap: "wrap",
    gap: 8,
  },
  transcriptBubbleRow: {
    flexDirection: "row",
  },
  transcriptBubbleRowRep: {
    justifyContent: "flex-end",
  },
  transcriptBubbleRowAi: {
    justifyContent: "flex-start",
  },
  transcriptBubble: {
    width: "88%",
    borderRadius: 22,
    paddingHorizontal: 14,
    paddingVertical: 14,
    borderWidth: StyleSheet.hairlineWidth,
  },
  transcriptBubbleRep: {
    backgroundColor: colors.accentSoft,
    borderColor: "rgba(22, 101, 52, 0.14)",
  },
  transcriptBubbleAi: {
    backgroundColor: "rgba(255,255,255,0.8)",
    borderColor: colors.line,
  },
  transcriptEvidenceBubble: {
    borderLeftWidth: 3,
    borderLeftColor: colors.accent,
  },
  transcriptFocusedBubble: {
    shadowColor: colors.accent,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.08,
    shadowRadius: 18,
    elevation: 3,
  },
  transcriptBubbleHeader: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 8,
  },
  transcriptStage: {
    fontSize: 11,
    color: colors.muted,
    textTransform: "uppercase",
    letterSpacing: 0.8,
  },
  transcriptBubbleSpeaker: {
    fontSize: 12,
    color: colors.ink,
    fontFamily: "Poppins_700Bold",
  },
  emotionChip: {
    borderRadius: 999,
    paddingHorizontal: 9,
    paddingVertical: 4,
    borderWidth: StyleSheet.hairlineWidth,
  },
  emotionChipText: {
    fontSize: 10,
    fontFamily: "Poppins_600SemiBold",
  },
  transcriptText: {
    marginTop: 10,
    fontSize: 14,
    color: colors.ink,
    lineHeight: 21,
  },
  transcriptEvidenceChipRow: {
    gap: 8,
    paddingTop: 10,
    paddingRight: 8,
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
