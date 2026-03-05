import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useEffect, useState } from "react";
import { Pressable, SafeAreaView, ScrollView, StyleSheet, Text, View } from "react-native";

import { fetchRepSession } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { RepSessionDetail } from "../types";
import { RootStackParamList } from "../navigation/types";

type Props = NativeStackScreenProps<RootStackParamList, "Score">;

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

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <Text style={styles.title}>Scorecard</Text>
        <Text style={styles.subtitle}>Session {sessionId.slice(0, 8)}</Text>
        {loading ? <Text style={styles.muted}>Loading...</Text> : null}
        {error ? <Text style={styles.error}>{error}</Text> : null}
        <View style={styles.metricCard}>
          <Text style={styles.metricLabel}>Overall Score</Text>
          <Text style={styles.metricValue}>{scorecard?.overall_score ?? "--"}</Text>
        </View>
        <ScrollView contentContainerStyle={styles.scoreList}>
          {Object.entries(scorecard?.category_scores ?? {}).map(([category, score]) => (
            <View style={styles.row} key={category}>
              <Text style={styles.category}>{category}</Text>
              <Text style={styles.categoryScore}>{score.toFixed(1)}</Text>
            </View>
          ))}
          {scorecard?.highlights?.map((highlight, index) => (
            <View style={styles.highlight} key={`${highlight.note}-${index}`}>
              <Text style={styles.highlightType}>{highlight.type.toUpperCase()}</Text>
              <Text style={styles.highlightText}>{highlight.note}</Text>
            </View>
          ))}
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
  container: { flex: 1, padding: 20, gap: 10 },
  title: { fontSize: 28, fontWeight: "700", color: colors.ink },
  subtitle: { color: colors.muted },
  muted: { color: colors.muted },
  error: { color: "#AF2D18" },
  metricCard: {
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    padding: 14
  },
  metricLabel: { color: colors.muted, fontWeight: "700", fontSize: 12 },
  metricValue: { color: colors.ink, fontSize: 36, fontWeight: "800" },
  scoreList: { gap: 8, paddingBottom: 20 },
  row: {
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    paddingHorizontal: 12,
    paddingVertical: 10,
    flexDirection: "row",
    justifyContent: "space-between"
  },
  category: { color: colors.ink, textTransform: "capitalize" },
  categoryScore: { color: colors.success, fontWeight: "700" },
  highlight: {
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.accentSoft,
    padding: 10,
    gap: 4
  },
  highlightType: { color: colors.accent, fontSize: 11, fontWeight: "700" },
  highlightText: { color: colors.ink },
  doneBtn: {
    marginTop: "auto",
    borderRadius: 12,
    backgroundColor: colors.accent,
    alignItems: "center",
    paddingVertical: 12
  },
  doneLabel: { color: "white", fontWeight: "700" }
});
