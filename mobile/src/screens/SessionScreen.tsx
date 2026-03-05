import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { Audio } from "expo-av";
import * as FileSystem from "expo-file-system";
import { useEffect, useMemo, useRef, useState } from "react";
import { Pressable, SafeAreaView, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { RootStackParamList } from "../navigation/types";
import { fetchRepSession } from "../services/api";
import { AudioCaptureService } from "../services/audio";
import { SessionWsClient } from "../services/websocket";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { WsInboundEvent } from "../types";

type Props = NativeStackScreenProps<RootStackParamList, "Session">;
type TimelineEvent = {
  id: number;
  type: string;
  at: string;
  note: string;
};

const MAX_EVENTS = 120;
const INTERRUPT_BANNER_MS = 2200;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function meterToPercent(db: number): number {
  const floor = -70;
  const ceiling = -10;
  return clamp((db - floor) / (ceiling - floor), 0, 1);
}

function payloadPreview(payload: Record<string, unknown>): string {
  const preview = JSON.stringify(payload);
  return preview.length > 120 ? `${preview.slice(0, 120)}...` : preview;
}

function extForCodec(codec: string): string {
  if (codec === "wav" || codec === "pcm16") {
    return "wav";
  }
  if (codec === "mp3") {
    return "mp3";
  }
  return "m4a";
}

export function SessionScreen({ route, navigation }: Props) {
  const { repId } = useSession();
  const wsClientRef = useRef<SessionWsClient | null>(null);
  const audioCaptureRef = useRef<AudioCaptureService | null>(null);
  const eventIdRef = useRef(1);
  const interruptionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const audioQueueRef = useRef<Array<{ payload: string; codec: string }>>([]);
  const audioDrainRef = useRef(false);

  const [connected, setConnected] = useState(false);
  const [stateLabel, setStateLabel] = useState("idle");
  const [hintText, setHintText] = useState("");
  const [lastTranscript, setLastTranscript] = useState("--");
  const [aiStream, setAiStream] = useState("--");
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [repSpeaking, setRepSpeaking] = useState(false);
  const [meterDb, setMeterDb] = useState(-70);
  const [aiSpeaking, setAiSpeaking] = useState(false);
  const [playingAudio, setPlayingAudio] = useState(false);
  const [interruptionCue, setInterruptionCue] = useState<string | null>(null);

  const sessionId = route.params.sessionId;
  const meterWidth = useMemo(() => meterToPercent(meterDb), [meterDb]);

  function addEvent(event: WsInboundEvent) {
    setEvents((items) =>
      [
        {
          id: eventIdRef.current++,
          type: event.type,
          at: new Date().toISOString(),
          note: payloadPreview(event.payload)
        },
        ...items
      ].slice(0, MAX_EVENTS)
    );
  }

  function showInterruptCue(label: string) {
    setInterruptionCue(label);
    if (interruptionTimerRef.current) {
      clearTimeout(interruptionTimerRef.current);
    }
    interruptionTimerRef.current = setTimeout(() => {
      setInterruptionCue(null);
      interruptionTimerRef.current = null;
    }, INTERRUPT_BANNER_MS);
  }

  async function playAudioChunk(payload: string, codec: string): Promise<void> {
    const baseDir = FileSystem.cacheDirectory || FileSystem.documentDirectory;
    if (!baseDir) {
      return;
    }
    const extension = extForCodec(codec);
    const filePath = `${baseDir}doordrill-ai-${Date.now()}-${Math.random().toString(16).slice(2)}.${extension}`;

    try {
      await FileSystem.writeAsStringAsync(filePath, payload, {
        encoding: FileSystem.EncodingType.Base64
      });

      const sound = new Audio.Sound();
      await sound.loadAsync({ uri: filePath }, { shouldPlay: true, volume: 1.0 });
      await new Promise<void>((resolve) => {
        sound.setOnPlaybackStatusUpdate((status) => {
          if (!status.isLoaded || status.didJustFinish) {
            resolve();
          }
        });
      });
      await sound.unloadAsync();
    } catch {
      // Best-effort playback to keep turn loop moving even if chunk decode fails.
    } finally {
      await FileSystem.deleteAsync(filePath, { idempotent: true }).catch(() => undefined);
    }
  }

  async function drainAudioQueue() {
    if (audioDrainRef.current) {
      return;
    }

    audioDrainRef.current = true;
    setPlayingAudio(true);

    while (audioQueueRef.current.length > 0) {
      const next = audioQueueRef.current.shift();
      if (!next) {
        continue;
      }
      await playAudioChunk(next.payload, next.codec);
    }

    audioDrainRef.current = false;
    setPlayingAudio(false);
  }

  function enqueueAudio(payload: string, codec: string) {
    if (!payload) {
      return;
    }
    audioQueueRef.current.push({ payload, codec });
    void drainAudioQueue();
  }

  function handleInboundEvent(event: WsInboundEvent) {
    addEvent(event);

    if (event.type === "server.session.state") {
      const nextState = String(event.payload.state ?? "running");
      setStateLabel(nextState);

      if (nextState === "ai_speaking") {
        setAiSpeaking(true);
        setAiStream("");
      }
      if (nextState === "ai_idle") {
        setAiSpeaking(false);
      }
      if (nextState === "barge_in_detected") {
        const reason = String(event.payload.reason ?? "interruption");
        showInterruptCue(`You interrupted AI (${reason})`);
      }
    }

    if (event.type === "server.stt.final") {
      const next = String(event.payload.text ?? "").trim();
      if (next) {
        setLastTranscript(next);
      }
    }

    if (event.type === "server.ai.text.delta") {
      const token = String(event.payload.token ?? "");
      if (!token) {
        return;
      }
      setAiStream((current) => (current === "--" ? token : `${current}${token}`));
    }

    if (event.type === "server.ai.audio.chunk") {
      enqueueAudio(String(event.payload.payload ?? ""), String(event.payload.codec ?? "mp3"));
    }

    if (event.type === "server.error") {
      setError(String(event.payload.message ?? "Session error"));
    }
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
          handleInboundEvent(event);
        },
        () => {
          setConnected(false);
          setStateLabel("disconnected");
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

  async function startRecording() {
    if (!connected || recording) {
      return;
    }
    const client = wsClientRef.current;
    const audioCapture = audioCaptureRef.current;
    if (!client || !audioCapture) {
      return;
    }

    setError(null);
    if (aiSpeaking) {
      showInterruptCue("You interrupted AI");
    }

    try {
      client.sendVadState(true);
      await audioCapture.start();
      setRecording(true);
    } catch (err) {
      client.sendVadState(false);
      setRecording(false);
      setError(err instanceof Error ? err.message : "Failed to start microphone capture");
    }
  }

  async function stopRecordingAndSend() {
    if (!recording) {
      return;
    }

    const client = wsClientRef.current;
    const audioCapture = audioCaptureRef.current;
    if (!client || !audioCapture) {
      setRecording(false);
      return;
    }

    try {
      const chunk = await audioCapture.stop();
      client.sendVadState(false);
      if (chunk) {
        client.sendAudioChunk(chunk, hintText);
      }
    } catch (err) {
      client.sendVadState(false);
      setError(err instanceof Error ? err.message : "Failed to send captured audio");
    } finally {
      setRecording(false);
    }
  }

  async function endSession() {
    try {
      if (recording) {
        await stopRecordingAndSend();
      }

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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to end session");
    }
  }

  useEffect(() => {
    const audioCapture = new AudioCaptureService();
    audioCapture.onVadChange((speaking) => setRepSpeaking(speaking));
    audioCapture.onMeter((db) => setMeterDb(db));
    audioCaptureRef.current = audioCapture;

    void connect();

    return () => {
      if (interruptionTimerRef.current) {
        clearTimeout(interruptionTimerRef.current);
      }
      wsClientRef.current?.close();
      wsClientRef.current = null;
      void audioCaptureRef.current?.stop().catch(() => undefined);
      audioCaptureRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <View style={styles.headerRow}>
          <View>
            <Text style={styles.title}>Live Roleplay</Text>
            <Text style={styles.subtitle}>Session {sessionId.slice(0, 8)}</Text>
          </View>
          <Pressable style={styles.reconnect} onPress={() => void connect()}>
            <Text style={styles.reconnectLabel}>Reconnect</Text>
          </Pressable>
        </View>

        <View style={styles.statusRow}>
          <View style={[styles.statusChip, connected ? styles.statusConnected : styles.statusDisconnected]}>
            <Text style={styles.statusChipLabel}>{connected ? "Connected" : "Offline"}</Text>
          </View>
          <View style={[styles.statusChip, aiSpeaking ? styles.statusAiSpeaking : styles.statusIdle]}>
            <Text style={styles.statusChipLabel}>State {stateLabel}</Text>
          </View>
          <View style={[styles.statusChip, repSpeaking ? styles.statusRepSpeaking : styles.statusIdle]}>
            <Text style={styles.statusChipLabel}>{repSpeaking ? "Rep speaking" : "Rep idle"}</Text>
          </View>
        </View>

        {error ? <Text style={styles.error}>{error}</Text> : null}
        {interruptionCue ? <Text style={styles.interrupt}>{interruptionCue}</Text> : null}

        <View style={styles.meterCard}>
          <View style={styles.meterHeader}>
            <Text style={styles.meterTitle}>Microphone level</Text>
            <Text style={styles.meterDb}>{meterDb.toFixed(0)} dB</Text>
          </View>
          <View style={styles.meterTrack}>
            <View style={[styles.meterFill, { width: `${Math.round(meterWidth * 100)}%` }]} />
          </View>
        </View>

        <View style={styles.inputCard}>
          <Text style={styles.inputLabel}>Optional hint</Text>
          <TextInput
            style={styles.input}
            value={hintText}
            onChangeText={setHintText}
            placeholder="Optional transcript cue for STT fallback"
            placeholderTextColor={colors.muted}
          />
        </View>

        <View style={styles.actionRow}>
          <Pressable
            style={[styles.talkButton, (!connected || recording) && styles.disabled]}
            disabled={!connected}
            onPressIn={() => {
              void startRecording();
            }}
            onPressOut={() => {
              void stopRecordingAndSend();
            }}
          >
            <Text style={styles.talkButtonLabel}>{recording ? "Release to send" : "Hold to talk"}</Text>
          </Pressable>

          <Pressable style={styles.endBtn} onPress={() => void endSession()}>
            <Text style={styles.endLabel}>End</Text>
          </Pressable>
        </View>

        <View style={styles.livePane}>
          <Text style={styles.paneTitle}>Rep Transcript</Text>
          <Text style={styles.paneText}>{lastTranscript}</Text>
        </View>

        <View style={styles.livePane}>
          <View style={styles.paneHeader}>
            <Text style={styles.paneTitle}>Homeowner Response</Text>
            <Text style={styles.playbackLabel}>{playingAudio ? "Audio playing" : "Audio idle"}</Text>
          </View>
          <Text style={styles.paneText}>{aiStream}</Text>
        </View>

        <Text style={styles.timelineTitle}>Event Stream</Text>
        <ScrollView contentContainerStyle={styles.timeline}>
          {events.length === 0 ? <Text style={styles.empty}>No events yet.</Text> : null}
          {events.map((event) => (
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
  container: { flex: 1, padding: 18, gap: 10 },
  headerRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  title: { fontSize: 28, fontWeight: "800", color: colors.ink },
  subtitle: { color: colors.muted },
  reconnect: {
    borderColor: colors.line,
    borderWidth: 1,
    borderRadius: 999,
    backgroundColor: colors.panel,
    paddingVertical: 8,
    paddingHorizontal: 14
  },
  reconnectLabel: { color: colors.ink, fontWeight: "700", fontSize: 12 },
  statusRow: { flexDirection: "row", gap: 8, flexWrap: "wrap" },
  statusChip: {
    borderRadius: 999,
    paddingVertical: 6,
    paddingHorizontal: 10
  },
  statusConnected: { backgroundColor: "#D9F4E7" },
  statusDisconnected: { backgroundColor: "#F4DBD6" },
  statusAiSpeaking: { backgroundColor: "#FFE4C8" },
  statusRepSpeaking: { backgroundColor: "#E4E9FF" },
  statusIdle: { backgroundColor: colors.accentSoft },
  statusChipLabel: { color: colors.ink, fontSize: 11, fontWeight: "700" },
  error: { color: "#AF2D18", fontWeight: "600" },
  interrupt: {
    color: "#AF2D18",
    fontWeight: "700",
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#E8B9B0",
    backgroundColor: "#F8E4E0",
    paddingHorizontal: 10,
    paddingVertical: 8
  },
  meterCard: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    padding: 10,
    gap: 6
  },
  meterHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  meterTitle: { color: colors.muted, fontSize: 12, fontWeight: "700", textTransform: "uppercase" },
  meterDb: { color: colors.ink, fontSize: 12, fontWeight: "600" },
  meterTrack: {
    width: "100%",
    height: 8,
    borderRadius: 999,
    backgroundColor: "#EEE2D3",
    overflow: "hidden"
  },
  meterFill: { height: "100%", borderRadius: 999, backgroundColor: colors.accent },
  inputCard: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    padding: 10,
    gap: 5
  },
  inputLabel: { color: colors.muted, fontSize: 12, fontWeight: "700", textTransform: "uppercase" },
  input: {
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: "#FFF8ED",
    color: colors.ink,
    paddingHorizontal: 10,
    paddingVertical: 9
  },
  actionRow: { flexDirection: "row", gap: 10 },
  talkButton: {
    flex: 1,
    borderRadius: 12,
    backgroundColor: colors.accent,
    alignItems: "center",
    paddingVertical: 13
  },
  talkButtonLabel: { color: "white", fontWeight: "800", fontSize: 15 },
  endBtn: {
    borderRadius: 12,
    backgroundColor: "#222",
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 18
  },
  endLabel: { color: "white", fontWeight: "700" },
  disabled: { opacity: 0.45 },
  livePane: {
    borderRadius: 12,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    padding: 10,
    gap: 5
  },
  paneHeader: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  paneTitle: { color: colors.muted, fontSize: 12, fontWeight: "700", textTransform: "uppercase" },
  playbackLabel: { color: colors.accent, fontSize: 11, fontWeight: "700" },
  paneText: { color: colors.ink, fontSize: 13 },
  timelineTitle: { color: colors.ink, fontWeight: "700", marginTop: 2 },
  timeline: { gap: 8, paddingBottom: 30 },
  eventRow: {
    borderRadius: 10,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.panel,
    padding: 10,
    gap: 3
  },
  eventType: { color: colors.accent, fontWeight: "700", fontSize: 12 },
  eventNote: { color: colors.muted, fontSize: 11 },
  empty: { color: colors.muted }
});
