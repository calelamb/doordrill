import { BottomTabScreenProps } from "@react-navigation/bottom-tabs";
import { CompositeScreenProps } from "@react-navigation/native";
import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import { ActivityIndicator, LayoutChangeEvent, Pressable, RefreshControl, SafeAreaView, ScrollView, StyleSheet, Text, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { ArrowDownRight, ArrowUpRight, ChevronRight, History, Minus } from "lucide-react-native";
import Animated, { interpolate, useAnimatedStyle, useSharedValue, withRepeat, withTiming } from "react-native-reanimated";
import Svg, { Circle, Line as SvgLine, Path, Text as SvgText } from "react-native-svg";
import { BlurView } from "expo-blur";

import { BottomTabParamList, RootStackParamList } from "../navigation/types";
import { fetchAllScenarios, fetchRepSessionsHistory, fetchRepTrend } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { RepSessionHistoryItem, RepTrend, ScenarioBrief } from "../types";

type Props = CompositeScreenProps<
  BottomTabScreenProps<BottomTabParamList, "HistoryTab">,
  NativeStackScreenProps<RootStackParamList>
>;

type TrendKey = "opening" | "pitch_delivery" | "objection_handling" | "closing_technique" | "professionalism";

const TREND_SERIES: Array<{ key: TrendKey; label: string; shortLabel: string; color: string; emphasis?: boolean }> = [
  { key: "opening", label: "Opening", shortLabel: "Opening", color: "#7C6F64" },
  { key: "pitch_delivery", label: "Pitch", shortLabel: "Pitch", color: "#9D8C78" },
  { key: "objection_handling", label: "Objection Handling", shortLabel: "Obj.", color: colors.accent, emphasis: true },
  { key: "closing_technique", label: "Closing", shortLabel: "Closing", color: "#B07A2A" },
  { key: "professionalism", label: "Professionalism", shortLabel: "Prof.", color: "#55646F" },
];

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function formatDate(iso: string) {
  const date = new Date(iso);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function buildLinePath(values: Array<number | null>, width: number, height: number) {
  const paddingLeft = 22;
  const paddingRight = 12;
  const paddingTop = 14;
  const paddingBottom = 24;
  const usableWidth = Math.max(1, width - paddingLeft - paddingRight);
  const usableHeight = Math.max(1, height - paddingTop - paddingBottom);
  const denominator = Math.max(1, values.length - 1);
  const points = values
    .map((value, index) => {
      if (typeof value !== "number") {
        return null;
      }
      const x = paddingLeft + (usableWidth * index) / denominator;
      const y = paddingTop + ((10 - clamp(value, 0, 10)) / 10) * usableHeight;
      return { x, y };
    })
    .filter((point): point is { x: number; y: number } => point !== null);

  if (points.length === 0) {
    return { path: "", lastPoint: null, paddingLeft, paddingRight, paddingTop, paddingBottom, usableHeight, usableWidth };
  }

  return {
    path: points.map((point, index) => `${index === 0 ? "M" : "L"} ${point.x} ${point.y}`).join(" "),
    lastPoint: points[points.length - 1],
    paddingLeft,
    paddingRight,
    paddingTop,
    paddingBottom,
    usableHeight,
    usableWidth,
  };
}

function ShimmerBlock({ height }: { height: number }) {
  const shimmerProgress = useSharedValue(0);

  useEffect(() => {
    shimmerProgress.value = withRepeat(withTiming(1, { duration: 1250 }), -1, false);
  }, [shimmerProgress]);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: interpolate(shimmerProgress.value, [0, 1], [-240, 240]) }],
  }));

  return (
    <View style={[styles.skeletonBlock, { height }]}>
      <Animated.View style={[styles.skeletonShimmerRail, animatedStyle]}>
        <LinearGradient
          colors={["transparent", "rgba(255,255,255,0.62)", "transparent"]}
          start={{ x: 0, y: 0.5 }}
          end={{ x: 1, y: 0.5 }}
          style={styles.skeletonShimmer}
        />
      </Animated.View>
    </View>
  );
}

export function HistoryScreen({ navigation }: Props) {
  const { repId } = useSession();
  const [history, setHistory] = useState<RepSessionHistoryItem[]>([]);
  const [scenarios, setScenarios] = useState<Record<string, ScenarioBrief>>({});
  const [trend, setTrend] = useState<RepTrend | null>(null);
  const [chartWidth, setChartWidth] = useState(0);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [trendLoading, setTrendLoading] = useState(true);
  const [trendError, setTrendError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!repId) return;

    setError(null);
    setTrendLoading(true);
    setTrendError(null);

    const [historyResult, scenariosResult, trendResult] = await Promise.allSettled([
      fetchRepSessionsHistory(repId),
      fetchAllScenarios(repId),
      fetchRepTrend(repId, 8),
    ]);

    if (historyResult.status === "fulfilled") {
      setHistory(historyResult.value.items);
    }

    if (scenariosResult.status === "fulfilled") {
      const scenarioMap: Record<string, ScenarioBrief> = {};
      scenariosResult.value.forEach((scenario) => {
        scenarioMap[scenario.id] = scenario;
      });
      setScenarios(scenarioMap);
    }

    if (trendResult.status === "fulfilled") {
      setTrend(trendResult.value);
    } else {
      setTrend(null);
      setTrendError(trendResult.reason instanceof Error ? trendResult.reason.message : "Trend unavailable");
    }

    if (historyResult.status === "rejected" || scenariosResult.status === "rejected") {
      const reason = historyResult.status === "rejected"
        ? historyResult.reason
        : scenariosResult.status === "rejected"
          ? scenariosResult.reason
          : "Failed to load history";
      setError(reason instanceof Error ? reason.message : "Failed to load history");
    }

    setLoading(false);
    setRefreshing(false);
    setTrendLoading(false);
  }, [repId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    void loadData();
  }, [loadData]);

  const trendDescriptor = useMemo(() => {
    if (trend?.overall_trend === "improving") {
      return {
        label: "Overall: Improving",
        color: colors.accent,
        bg: colors.accentSoft,
        border: "rgba(22, 101, 52, 0.18)",
        icon: ArrowUpRight,
      };
    }
    if (trend?.overall_trend === "declining") {
      return {
        label: "Overall: Needs Attention",
        color: colors.danger,
        bg: colors.dangerSoft,
        border: "rgba(180, 35, 24, 0.18)",
        icon: ArrowDownRight,
      };
    }
    return {
      label: "Overall: Steady",
      color: colors.muted,
      bg: "rgba(108, 98, 85, 0.12)",
      border: "rgba(108, 98, 85, 0.16)",
      icon: Minus,
    };
  }, [trend?.overall_trend]);

  const weakestAverageKey = useMemo(() => {
    const averages = trend?.category_averages ?? {};
    const ranked = Object.entries(averages)
      .filter((entry): entry is [TrendKey, number] => typeof entry[1] === "number")
      .sort((left, right) => left[1] - right[1]);
    return ranked[0]?.[0] ?? null;
  }, [trend?.category_averages]);

  const chartSeries = useMemo(
    () =>
      TREND_SERIES.map((series) => ({
        ...series,
        values: (trend?.sessions ?? []).map((session) => {
          const score = session.category_scores?.[series.key];
          return typeof score === "number" ? score : null;
        }),
      })),
    [trend?.sessions]
  );

  function renderTrendSection() {
    if (trendLoading && !trend && !refreshing) {
      return (
        <BlurView intensity={40} tint="light" style={styles.trendCard}>
          <View style={styles.trendHeader}>
            <Text style={styles.trendEyebrow}>TREND</Text>
            <Text style={styles.trendDescription}>Loading your scoring pattern...</Text>
          </View>
          <ShimmerBlock height={140} />
        </BlurView>
      );
    }

    if (trendError && !trend) {
      return (
        <BlurView intensity={40} tint="light" style={styles.trendCard}>
          <Text style={styles.trendEyebrow}>TREND</Text>
          <Text style={styles.trendDescription}>Trend unavailable right now</Text>
        </BlurView>
      );
    }

    if (!trend || trend.sessions.length < 2) {
      return (
        <BlurView intensity={40} tint="light" style={styles.trendCard}>
          <Text style={styles.trendEyebrow}>TREND</Text>
          <Text style={styles.trendDescription}>Complete 2 drills to see your trend</Text>
        </BlurView>
      );
    }

    const TrendIcon = trendDescriptor.icon;
    const chartHeight = 140;
    const { paddingLeft, paddingRight, paddingTop, paddingBottom, usableHeight } = buildLinePath(
      chartSeries[0]?.values ?? [],
      Math.max(chartWidth, 1),
      chartHeight
    );

    return (
      <BlurView intensity={40} tint="light" style={styles.trendCard}>
        <View style={styles.trendIndicatorRow}>
          <View style={[styles.trendIndicatorPill, { backgroundColor: trendDescriptor.bg, borderColor: trendDescriptor.border }]}>
            <TrendIcon size={14} color={trendDescriptor.color} />
            <Text style={[styles.trendIndicatorText, { color: trendDescriptor.color }]}>{trendDescriptor.label}</Text>
          </View>
        </View>

        <View
          style={styles.chartShell}
          onLayout={(event: LayoutChangeEvent) => setChartWidth(event.nativeEvent.layout.width)}
        >
          {chartWidth > 0 ? (
            <Svg width={chartWidth} height={chartHeight}>
              {[0, 5, 10].map((tick) => {
                const y = paddingTop + ((10 - tick) / 10) * usableHeight;
                return (
                  <Fragment key={`tick-${tick}`}>
                    <SvgLine
                      x1={paddingLeft}
                      x2={chartWidth - paddingRight}
                      y1={y}
                      y2={y}
                      stroke="rgba(108, 98, 85, 0.14)"
                      strokeWidth={1}
                    />
                    <SvgText x={4} y={y + 4} fill={colors.muted} fontSize={10}>
                      {tick}
                    </SvgText>
                  </Fragment>
                );
              })}

              {trend.sessions.map((session, index) => {
                const x =
                  paddingLeft +
                  ((Math.max(0, chartWidth - paddingLeft - paddingRight) * index) / Math.max(1, trend.sessions.length - 1));
                return (
                  <SvgText key={session.session_id} x={x} y={chartHeight - 6} fill={colors.muted} fontSize={10} textAnchor="middle">
                    {index + 1}
                  </SvgText>
                );
              })}

              {chartSeries.map((series) => {
                const line = buildLinePath(series.values, chartWidth, chartHeight);
                if (!line.path) {
                  return null;
                }
                return (
                  <Fragment key={series.key}>
                    <Path
                      d={line.path}
                      fill="none"
                      stroke={series.color}
                      strokeWidth={series.emphasis ? 3 : 2}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    {line.lastPoint ? <Circle cx={line.lastPoint.x} cy={line.lastPoint.y} r={series.emphasis ? 4 : 3} fill={series.color} /> : null}
                  </Fragment>
                );
              })}
            </Svg>
          ) : null}
        </View>

        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.legendRow}>
          {TREND_SERIES.map((series) => (
            <View key={series.key} style={styles.legendChip}>
              <View style={[styles.legendDot, { backgroundColor: series.color }]} />
              <Text style={styles.legendText}>{series.label}</Text>
            </View>
          ))}
        </ScrollView>

        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.averageRow}>
          {TREND_SERIES.map((series) => {
            const average = trend.category_averages?.[series.key];
            const isWeakest = weakestAverageKey === series.key;
            return (
              <View
                key={`${series.key}-average`}
                style={[
                  styles.averageChip,
                  isWeakest ? styles.averageChipWeakest : null,
                ]}
              >
                <Text style={[styles.averageLabel, isWeakest ? styles.averageLabelWeakest : null]}>{series.shortLabel}</Text>
                <Text style={[styles.averageValue, isWeakest ? styles.averageValueWeakest : null]}>
                  {typeof average === "number" ? average.toFixed(1) : "--"}
                </Text>
              </View>
            );
          })}
        </ScrollView>
      </BlurView>
    );
  }

  return (
    <LinearGradient colors={["#FDFDFD", "#F7F4EE", "#EBE5D9"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.content}>
          <Text style={styles.title}>History</Text>
          <Text style={styles.subtitle}>Review your past drill performance.</Text>

          {error ? (
            <View style={styles.errorContainer}>
              <Text style={styles.error}>{error}</Text>
              <Pressable onPress={loadData}>
                <Text style={styles.retryText}>Retry</Text>
              </Pressable>
            </View>
          ) : null}

          <ScrollView
            contentContainerStyle={styles.list}
            showsVerticalScrollIndicator={false}
            refreshControl={
              <RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} colors={[colors.accent]} />
            }
          >
            {renderTrendSection()}

            {loading && !refreshing ? (
              <ActivityIndicator size="large" color={colors.accent} style={styles.loader} />
            ) : history.length === 0 ? (
              <View style={styles.emptyState}>
                <View style={styles.emptyIconContainer}>
                  <History size={32} color={colors.accent} />
                </View>
                <Text style={styles.emptyText}>No history yet.</Text>
                <Text style={styles.emptySubtext}>Complete your first drill to see your scorecard history here.</Text>
              </View>
            ) : (
              history.map((item) => {
                const scenario = scenarios[item.scenario_id];
                const scenarioName = scenario?.name ?? "Unknown Scenario";
                const scoreColor =
                  item.overall_score === null
                    ? colors.muted
                    : item.overall_score >= 8
                      ? colors.success
                      : item.overall_score >= 5
                        ? colors.warning
                        : colors.danger;

                return (
                  <Pressable
                    key={item.session_id}
                    style={({ pressed }) => [styles.cardWrapper, pressed ? styles.cardPressed : null]}
                    onPress={() => navigation.navigate("Score", { sessionId: item.session_id })}
                  >
                    <BlurView intensity={40} tint="light" style={styles.card}>
                      <View style={styles.cardInfo}>
                        <Text style={styles.scenarioName} numberOfLines={1}>
                          {scenarioName}
                        </Text>
                        <Text style={styles.date}>{item.started_at ? formatDate(item.started_at) : "Unknown Date"}</Text>
                      </View>

                      <View style={styles.scoreContainer}>
                        {item.overall_score !== null ? (
                          <Text style={[styles.scoreValue, { color: scoreColor }]}>{item.overall_score.toFixed(1)}</Text>
                        ) : (
                          <Text style={styles.pendingScore}>{item.status === "active" ? "In Progress" : "No Score"}</Text>
                        )}
                        <ChevronRight size={20} color={colors.muted} />
                      </View>
                    </BlurView>
                  </Pressable>
                );
              })
            )}
          </ScrollView>
        </View>
      </SafeAreaView>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  safeArea: { flex: 1 },
  content: { flex: 1, padding: 20, gap: 16 },
  title: { fontSize: 32, fontFamily: "Poppins_800ExtraBold", color: colors.ink, marginBottom: 4, marginTop: 10 },
  subtitle: { color: colors.muted, fontSize: 16, marginBottom: 8 },
  errorContainer: {
    backgroundColor: "#FEE2E2",
    borderWidth: 1,
    borderColor: "#FECACA",
    padding: 16,
    borderRadius: 14,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  error: { color: "#991B1B", fontWeight: "600", flex: 1 },
  retryText: { color: "#991B1B", fontWeight: "800", textDecorationLine: "underline" },
  list: { paddingBottom: 40, gap: 12 },
  loader: { marginTop: 24 },
  trendCard: {
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
  trendHeader: {
    gap: 4,
    marginBottom: 14,
  },
  trendEyebrow: {
    fontSize: 12,
    color: colors.muted,
    letterSpacing: 1,
    textTransform: "uppercase",
    fontFamily: "Poppins_700Bold",
  },
  trendDescription: {
    fontSize: 14,
    color: colors.muted,
    lineHeight: 20,
  },
  trendIndicatorRow: {
    marginBottom: 14,
  },
  trendIndicatorPill: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    borderRadius: 999,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  trendIndicatorText: {
    fontSize: 12,
    fontFamily: "Poppins_700Bold",
  },
  chartShell: {
    height: 140,
    marginBottom: 14,
  },
  legendRow: {
    gap: 8,
    paddingRight: 20,
    marginBottom: 12,
  },
  legendChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 10,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: "rgba(255,255,255,0.76)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
  },
  legendDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  legendText: {
    fontSize: 12,
    color: colors.ink,
    fontFamily: "Poppins_600SemiBold",
  },
  averageRow: {
    gap: 8,
    paddingRight: 20,
  },
  averageChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 12,
    paddingVertical: 9,
    borderRadius: 999,
    backgroundColor: "rgba(255,255,255,0.76)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
  },
  averageChipWeakest: {
    backgroundColor: colors.warningSoft,
    borderColor: "rgba(180, 83, 9, 0.22)",
  },
  averageLabel: {
    fontSize: 12,
    color: colors.muted,
    fontFamily: "Poppins_600SemiBold",
  },
  averageLabelWeakest: {
    color: colors.warning,
  },
  averageValue: {
    fontSize: 12,
    color: colors.ink,
    fontFamily: "Poppins_700Bold",
  },
  averageValueWeakest: {
    color: colors.warning,
  },
  skeletonBlock: {
    overflow: "hidden",
    borderRadius: 18,
    backgroundColor: "rgba(108, 98, 85, 0.12)",
  },
  skeletonShimmerRail: {
    ...StyleSheet.absoluteFillObject,
    width: 180,
  },
  skeletonShimmer: {
    flex: 1,
  },
  emptyState: { flex: 1, alignItems: "center", justifyContent: "center", gap: 12, marginTop: 80 },
  emptyIconContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.accentSoft,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 8,
    borderWidth: 1,
    borderColor: "rgba(74, 222, 128, 0.2)",
  },
  emptyText: { fontSize: 20, fontFamily: "Poppins_700Bold", color: colors.ink },
  emptySubtext: { fontSize: 15, color: colors.muted, textAlign: "center", paddingHorizontal: 20, lineHeight: 22 },
  cardWrapper: {
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
  cardPressed: {
    opacity: 0.85,
    transform: [{ scale: 0.98 }],
  },
  card: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    padding: 20,
  },
  cardInfo: {
    flex: 1,
    gap: 4,
    marginRight: 16,
  },
  scenarioName: {
    fontSize: 17,
    fontFamily: "Poppins_700Bold",
    color: colors.ink,
  },
  date: {
    fontSize: 14,
    color: colors.muted,
  },
  scoreContainer: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  scoreValue: {
    fontSize: 22,
    fontFamily: "Poppins_800ExtraBold",
  },
  pendingScore: {
    fontSize: 13,
    fontWeight: "600",
    color: colors.muted,
    fontStyle: "italic",
  },
});
