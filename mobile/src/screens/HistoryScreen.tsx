import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useCallback, useEffect, useState } from "react";
import { Pressable, SafeAreaView, StyleSheet, Text, View, ScrollView, ActivityIndicator, RefreshControl } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { History, ChevronRight } from "lucide-react-native";
import { BlurView } from "expo-blur";

import { colors } from "../theme/tokens";
import { BottomTabParamList, RootStackParamList } from "../navigation/types";
import { BottomTabScreenProps } from "@react-navigation/bottom-tabs";
import { CompositeScreenProps } from "@react-navigation/native";
import { useSession } from "../store/session";
import { fetchRepSessionsHistory, fetchAllScenarios } from "../services/api";
import { RepSessionHistoryItem, ScenarioBrief } from "../types";

type Props = CompositeScreenProps<
  BottomTabScreenProps<BottomTabParamList, "HistoryTab">,
  NativeStackScreenProps<RootStackParamList>
>;

function formatDate(iso: string) {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function HistoryScreen({ navigation }: Props) {
  const { repId } = useSession();
  const [history, setHistory] = useState<RepSessionHistoryItem[]>([]);
  const [scenarios, setScenarios] = useState<Record<string, ScenarioBrief>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!repId) return;
    try {
      const [historyRes, scenariosRes] = await Promise.all([
        fetchRepSessionsHistory(repId),
        fetchAllScenarios(repId)
      ]);
      setHistory(historyRes.items);
      const sMap: Record<string, ScenarioBrief> = {};
      scenariosRes.forEach(s => sMap[s.id] = s);
      setScenarios(sMap);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load history");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [repId]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const onRefresh = useCallback(() => {
    setRefreshing(true);
    void loadData();
  }, [loadData]);

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
            {loading && !refreshing ? (
              <ActivityIndicator size="large" color={colors.accent} style={{ marginTop: 40 }} />
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
                const isCompleted = item.status === "completed" || item.status === "graded";
                
                return (
                  <Pressable 
                    key={item.session_id} 
                    style={({pressed}) => [styles.cardWrapper, pressed && styles.cardPressed]}
                    onPress={() => {
                      if (isCompleted || item.overall_score !== null) {
                        navigation.navigate("Score", { sessionId: item.session_id });
                      } else {
                        // Might not have a scorecard if abandoned, but we can still navigate to fallback
                        navigation.navigate("Score", { sessionId: item.session_id });
                      }
                    }}
                  >
                    <BlurView intensity={40} tint="light" style={styles.card}>
                      <View style={styles.cardInfo}>
                        <Text style={styles.scenarioName} numberOfLines={1}>{scenarioName}</Text>
                        <Text style={styles.date}>{item.started_at ? formatDate(item.started_at) : "Unknown Date"}</Text>
                      </View>
                      
                      <View style={styles.scoreContainer}>
                        {item.overall_score !== null ? (
                          <Text style={[styles.scoreValue, { color: item.overall_score >= 8 ? colors.success : item.overall_score >= 5 ? "#d97706" : "#dc2626" }]}>
                            {item.overall_score.toFixed(1)}
                          </Text>
                        ) : (
                          <Text style={styles.pendingScore}>{item.status === 'active' ? 'In Progress' : 'No Score'}</Text>
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
    borderColor: "rgba(74, 222, 128, 0.2)"
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
  }
});
