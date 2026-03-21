import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { BlurView } from "expo-blur";
import { ChevronLeft, ChevronRight, Sparkles, Zap } from "lucide-react-native";

import { RootStackParamList } from "../navigation/types";
import { fetchAllScenarios } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { ScenarioBrief } from "../types";

type Props = NativeStackScreenProps<RootStackParamList, "ScenarioPicker">;

function difficultyLabel(value: number): string {
  if (value <= 1) {
    return "Easy";
  }
  if (value >= 4) {
    return "Advanced";
  }
  return "Moderate";
}

function difficultyDots(difficulty: number): boolean[] {
  return Array.from({ length: 5 }, (_, index) => index < Math.max(1, Math.min(5, Math.round(difficulty))));
}

export function ScenarioPickerScreen({ navigation, route }: Props) {
  const { repId } = useSession();
  const isFirstTimer = Boolean(route.params?.isFirstTimer);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [scenarios, setScenarios] = useState<ScenarioBrief[]>([]);

  useEffect(() => {
    let cancelled = false;

    async function loadScenarios() {
      if (!repId) {
        return;
      }

      setLoading(true);
      setError(null);
      try {
        const result = await fetchAllScenarios(repId);
        if (!cancelled) {
          setScenarios(result);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load scenarios");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadScenarios();
    return () => {
      cancelled = true;
    };
  }, [repId]);

  const sortedScenarios = useMemo(() => {
    const items = [...scenarios];
    items.sort((left, right) => {
      if (isFirstTimer && left.difficulty !== right.difficulty) {
        return left.difficulty - right.difficulty;
      }
      if (left.difficulty !== right.difficulty) {
        return left.difficulty - right.difficulty;
      }
      return left.name.localeCompare(right.name);
    });
    return items;
  }, [isFirstTimer, scenarios]);

  const recommendedScenarioId = useMemo(() => {
    if (!isFirstTimer || sortedScenarios.length === 0) {
      return null;
    }
    return sortedScenarios[0].id;
  }, [isFirstTimer, sortedScenarios]);

  return (
    <LinearGradient colors={["#FBF9F5", "#EFEEEA", "#E4E2DE"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.content}>
          <View style={styles.headerRow}>
            <Pressable
              onPress={() => navigation.goBack()}
              style={styles.backButton}
              accessibilityLabel="Go back"
            >
              <ChevronLeft size={22} color={colors.ink} />
            </Pressable>
            <View style={styles.headerCopy}>
              <Text style={styles.title}>{isFirstTimer ? "Pick Your First Drill" : "Choose a Drill"}</Text>
              <Text style={styles.subtitle}>
                {isFirstTimer
                  ? "Start with a lighter homeowner to get comfortable, then build from there."
                  : "Choose the conversation you want to run right now."}
              </Text>
            </View>
          </View>

          <ScrollView contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>
            {loading ? <ActivityIndicator color={colors.accent} size="large" style={styles.loader} /> : null}

            {!loading && error ? (
              <BlurView intensity={40} tint="light" style={styles.errorCard}>
                <Text style={styles.errorTitle}>Unable to load drills</Text>
                <Text style={styles.errorText}>{error}</Text>
                <Pressable
                  onPress={() => navigation.replace("ScenarioPicker", { isFirstTimer })}
                  accessibilityLabel="Retry loading scenarios"
                >
                  <Text style={styles.retryText}>Retry</Text>
                </Pressable>
              </BlurView>
            ) : null}

            {!loading && !error && sortedScenarios.length === 0 ? (
              <BlurView intensity={40} tint="light" style={styles.emptyCard}>
                <Sparkles size={20} color={colors.accent} />
                <Text style={styles.emptyTitle}>No drills are available yet</Text>
                <Text style={styles.emptyText}>Ask your manager to publish a scenario for your team.</Text>
              </BlurView>
            ) : null}

            {sortedScenarios.map((scenario) => {
              const isRecommended = scenario.id === recommendedScenarioId;

              return (
                <Pressable
                  key={scenario.id}
                  style={({ pressed }) => [styles.cardPressable, pressed && styles.cardPressed]}
                  onPress={() =>
                    navigation.navigate("PreSession", {
                      scenarioId: scenario.id,
                      isFirstSession: isFirstTimer,
                    })
                  }
                  accessibilityLabel={`Start ${scenario.name}`}
                >
                  <BlurView intensity={40} tint="light" style={styles.scenarioCard}>
                    <View style={styles.cardTopRow}>
                      <View style={styles.cardHeaderCopy}>
                        <Text style={styles.scenarioName}>{scenario.name}</Text>
                        <Text style={styles.scenarioDescription}>{scenario.description}</Text>
                      </View>
                      <ChevronRight size={18} color={colors.accent} />
                    </View>

                    {isRecommended ? (
                      <View style={styles.beginnerBadge}>
                        <Zap size={10} color="#FFFFFF" />
                        <Text style={styles.beginnerBadgeText}>Recommended for Beginners</Text>
                      </View>
                    ) : null}

                    <View style={styles.metaRow}>
                      <View style={styles.difficultyPill}>
                        <Text style={styles.difficultyPillText}>{difficultyLabel(scenario.difficulty)}</Text>
                      </View>
                      <View style={styles.difficultyDotsRow}>
                        {difficultyDots(scenario.difficulty).map((filled, index) => (
                          <View
                            key={`${scenario.id}-dot-${index}`}
                            style={[styles.difficultyDot, filled ? styles.difficultyDotFilled : styles.difficultyDotEmpty]}
                          />
                        ))}
                      </View>
                    </View>
                  </BlurView>
                </Pressable>
              );
            })}
          </ScrollView>
        </View>
      </SafeAreaView>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  safeArea: {
    flex: 1,
  },
  content: {
    flex: 1,
    paddingHorizontal: 20,
    paddingTop: 16,
  },
  headerRow: {
    flexDirection: "row",
    gap: 14,
    alignItems: "flex-start",
    marginBottom: 20,
  },
  backButton: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: "rgba(255, 255, 255, 0.72)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    alignItems: "center",
    justifyContent: "center",
  },
  headerCopy: {
    flex: 1,
    paddingTop: 2,
  },
  title: {
    fontFamily: "Poppins_800ExtraBold",
    fontSize: 28,
    lineHeight: 32,
    color: colors.ink,
    marginBottom: 6,
  },
  subtitle: {
    fontFamily: "Inter_400Regular",
    fontSize: 15,
    lineHeight: 22,
    color: colors.muted,
  },
  scrollContent: {
    gap: 14,
    paddingBottom: 32,
  },
  loader: {
    marginTop: 48,
  },
  errorCard: {
    borderRadius: 22,
    padding: 20,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    backgroundColor: "rgba(255, 255, 255, 0.62)",
  },
  errorTitle: {
    fontFamily: "Poppins_700Bold",
    fontSize: 18,
    color: colors.ink,
    marginBottom: 8,
  },
  errorText: {
    fontFamily: "Inter_400Regular",
    fontSize: 14,
    lineHeight: 21,
    color: colors.muted,
    marginBottom: 12,
  },
  retryText: {
    fontFamily: "Inter_700Bold",
    fontSize: 14,
    color: colors.accent,
  },
  emptyCard: {
    borderRadius: 22,
    padding: 24,
    alignItems: "center",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    backgroundColor: "rgba(255, 255, 255, 0.62)",
  },
  emptyTitle: {
    fontFamily: "Poppins_700Bold",
    fontSize: 18,
    color: colors.ink,
    marginTop: 10,
    marginBottom: 6,
  },
  emptyText: {
    fontFamily: "Inter_400Regular",
    fontSize: 14,
    lineHeight: 21,
    color: colors.muted,
    textAlign: "center",
  },
  cardPressable: {
    borderRadius: 24,
  },
  cardPressed: {
    opacity: 0.94,
    transform: [{ scale: 0.988 }],
  },
  scenarioCard: {
    borderRadius: 24,
    padding: 18,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    backgroundColor: "rgba(255, 255, 255, 0.62)",
    gap: 14,
  },
  cardTopRow: {
    flexDirection: "row",
    alignItems: "flex-start",
    gap: 12,
  },
  cardHeaderCopy: {
    flex: 1,
  },
  scenarioName: {
    fontFamily: "Poppins_700Bold",
    fontSize: 20,
    lineHeight: 24,
    color: colors.ink,
    marginBottom: 6,
  },
  scenarioDescription: {
    fontFamily: "Inter_400Regular",
    fontSize: 14,
    lineHeight: 21,
    color: colors.muted,
  },
  beginnerBadge: {
    alignSelf: "flex-start",
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 7,
    borderRadius: 999,
    backgroundColor: colors.accent,
  },
  beginnerBadgeText: {
    fontFamily: "Inter_700Bold",
    fontSize: 12,
    color: "#FFFFFF",
  },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  difficultyPill: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
    backgroundColor: colors.accentSoft,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(22, 101, 52, 0.16)",
  },
  difficultyPillText: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 12,
    color: colors.accent,
  },
  difficultyDotsRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 6,
  },
  difficultyDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  difficultyDotFilled: {
    backgroundColor: colors.accent,
  },
  difficultyDotEmpty: {
    backgroundColor: "rgba(22, 101, 52, 0.14)",
  },
});
