import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useEffect, useMemo, useRef, useState } from "react";
import { Pressable, SafeAreaView, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { fetchRepSession } from "../services/api";
import { SessionWsClient } from "../services/websocket";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { WsInboundEvent } from "../types";
import { RootStackParamList } from "../navigation/types";

type Props = NativeStackScreenProps<RootStackParamList, "Session">;
type TimelineEvent = {
  id: number;
  type: string;
  at: string;
  note: string;
};

const MAX_EVENTS = 100;

export function SessionScreen({ route, navigation }: Props) {
  const { repId } = useSession();
  const wsClientRef = useRef<SessionWsClient | null>(null);
  const eventIdRef = useRef(1);
  const [connected, setConnected] = useState(false);
  const [stateLabel, setStateLabel] = useState("idle");
  const [utterance, setUtterance] = useState("");
  const [lastTranscript, setLastTranscript] = useState("");
  const [aiStream, setAiStream] = useState("");
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  const sessionId = route.params.sessionId;
  const canSend = connected && utterance.trim().length > 0;

  const sortedEvents = useMemo(() => events, [events]);

  function addEvent(event: WsInboundEvent) {
    const payloadPreview = event.payload ? JSON.stringify(event.payload).slice(0, 90) : "";
    setEvents((items) => [
      {
        id: eventIdRef.current++,
        type: event.type,
        at: new Date().toISOString(),
        note: payloadPreview
      },
      ...items
    ].slice(0, MAX_EVENTS));
  }

  async function connect() {
    if (wsClientRef.current) {
      wsClientRef.current.close();
    }
    const client = new SessionWsClient(sessionId);
    wsClientRef.current = client;
    setError(null);
    try {
      await client.connect(
        (event) => {
          addEvent(event);

          if (event.type === "server.session.state") {
            const next = String(event.payload.state ?? "running");
            setStateLabel(next);
            if (next === "ai_speaking") {
              setAiStream("");
            }
          }
          if (event.type === "server.stt.final") {
            setLastTranscript(String(event.payload.text ?? ""));
          }
          if (event.type === "server.ai.text.delta") {
            const token = String(event.payload.token ?? "");
            setAiStream((current) => `${current}${token}`);
          }
          if (event.type === "server.error") {
            setError(String(event.payload.message ?? "Session error"));
          }
        },
        () => {
          setConnected(false);
          setStateLabel("closed");
        }
      );
      setConnected(true);
      setStateLabel("connected");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to connect");
      setConnected(false);
      setStateLabel("error");
    }
  }

  async function endSession() {
    const client = wsClientRef.current;
    if (client) {
      client.endSession();
      client.close();
      wsClientRef.current = null;
    }
    setConnected(false);
    setStateLabel("ending");
    if (repId) {
      const detail = await fetchRepSession(repId, sessionId);
      navigation.replace("Score", { sessionId: detail.session.id });
    }
  }

  function sendTurn() {
    if (!canSend || !wsClientRef.current) {
      return;
    }
    wsClientRef.current.sendTextUtterance(utterance);
    setUtterance("");
  }

  useEffect(() => {
    void connect();
    return () => {
      wsClientRef.current?.close();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <Text style={styles.title}>Live Drill</Text>
        <Text style={styles.subtitle}>Session {sessionId.slice(0, 8)}</Text>
        <View style={styles.statusRow}>
          <Text style={styles.statusText}>State: {stateLabel}</Text>
          <Pressable style={styles.reconnect} onPress={() => void connect()}>
            <Text style={styles.reconnectLabel}>Reconnect</Text>
          </Pressable>
        </View>

        {error ? <Text style={styles.error}>{error}</Text> : null}

        <TextInput
          style={styles.input}
          value={utterance}
          onChangeText={setUtterance}
          placeholder="Type what the rep says..."
          multiline
        />
        <View style={styles.actionRow}>
          <Pressable style={[styles.sendBtn, !canSend && styles.disabled]} disabled={!canSend} onPress={sendTurn}>
            <Text style={styles.sendLabel}>Send Turn</Text>
          </Pressable>
          <Pressable style={styles.endBtn} onPress={() => void endSession()}>
            <Text style={styles.endLabel}>End Session</Text>
          </Pressable>
        </View>

        <View style={styles.livePane}>
          <Text style={styles.paneTitle}>Live Transcript</Text>
          <Text style={styles.paneText}>{lastTranscript || "--"}</Text>
        </View>
        <View style={styles.livePane}>
          <Text style={styles.paneTitle}>AI Stream</Text>
          <Text style={styles.paneText}>{aiStream || "--"}</Text>
        </View>

        <Text style={styles.timelineTitle}>Event Stream</Text>
        <ScrollView contentContainerStyle={styles.timeline}>
          {sortedEvents.length === 0 ? <Text style={styles.empty}>No events yet.</Text> : null}
          {sortedEvents.map((event) => (
            <View key={event.id} style={styles.eventRow}>
              <Text style={styles.eventType}>{event.type}</Text>
              <Text style={styles.eventNote}>{event.note}</Text>
            </View>
          ))}
        </ScrollView>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.bg },
  container: { flex: 1, padding: 20, gap: 10 },
  title: { fontSize: 28, fontWeight: "700", color: colors.ink },
  subtitle: { color: colors.muted },
  statusRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  statusText: { color: colors.ink, fontWeight: "700" },
  reconnect: {
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: 10,
    backgroundColor: colors.panel,
    paddingVertical: 7,
    paddingHorizontal: 10
  },
  reconnectLabel: { color: colors.ink, fontWeight: "600" },
  error: { color: "#AF2D18" },
  input: {
    minHeight: 74,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    padding: 12,
    textAlignVertical: "top"
  },
  actionRow: { flexDirection: "row", gap: 10 },
  sendBtn: {
    flex: 1,
    borderRadius: 12,
    backgroundColor: colors.accent,
    alignItems: "center",
    paddingVertical: 12
  },
  sendLabel: { color: "white", fontWeight: "700" },
  endBtn: {
    borderRadius: 12,
    backgroundColor: "#222",
    alignItems: "center",
    paddingVertical: 12,
    paddingHorizontal: 16
  },
  endLabel: { color: "white", fontWeight: "700" },
  disabled: { opacity: 0.4 },
  livePane: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    padding: 10,
    gap: 5
  },
  paneTitle: { color: colors.muted, fontSize: 12, fontWeight: "700", textTransform: "uppercase" },
  paneText: { color: colors.ink },
  timelineTitle: { color: colors.ink, fontWeight: "700" },
  timeline: { gap: 8, paddingBottom: 30 },
  eventRow: {
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    padding: 10
  },
  eventType: { color: colors.accent, fontWeight: "700", fontSize: 12 },
  eventNote: { color: colors.muted, fontSize: 11 },
  empty: { color: colors.muted }
});
