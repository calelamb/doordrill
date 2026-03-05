import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { Audio, InterruptionModeAndroid, InterruptionModeIOS } from "expo-av";
import * as FileSystem from "expo-file-system/legacy";
import * as Haptics from "expo-haptics";
import { useEffect, useMemo, useRef, useState } from "react";
import { Animated as RNAnimated, Pressable, SafeAreaView, StyleSheet, Text, View } from "react-native";
import Animated, { 
  useSharedValue, 
  useAnimatedStyle, 
  withSpring, 
  withTiming, 
  withRepeat, 
  withSequence,
  interpolateColor
} from "react-native-reanimated";
import { Activity, Home, Mic, MicOff, Volume2, WifiOff } from "lucide-react-native";

import { RootStackParamList } from "../navigation/types";
import { AudioCaptureService } from "../services/audio";
import { SessionWsClient } from "../services/websocket";
import { colors } from "../theme/tokens";
import { WsInboundEvent } from "../types";

type Props = NativeStackScreenProps<RootStackParamList, "Session">;

const RECONNECT_DELAYS_MS = [500, 1000, 2000];
const HOLD_END_MS = 500;
const NUDGE_DELAY_MS = 4000;
const INTERRUPT_BANNER_MS = 2200;
const WAVE_BAR_COUNT = 12;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function meterToPercent(db: number): number {
  const floor = -70;
  const ceiling = -8;
  return clamp((db - floor) / (ceiling - floor), 0, 1);
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

function formatTimer(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0");
  const remainder = (seconds % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}

async function configurePlaybackAudioMode(): Promise<void> {
  await Audio.setAudioModeAsync({
    allowsRecordingIOS: false,
    interruptionModeIOS: InterruptionModeIOS.DoNotMix,
    playsInSilentModeIOS: true,
    staysActiveInBackground: false,
    shouldDuckAndroid: true,
    interruptionModeAndroid: InterruptionModeAndroid.DuckOthers,
    playThroughEarpieceAndroid: false,
  });
}

function WaveBar({ targetHeight }: { targetHeight: number }) {
  const height = useSharedValue(10);
  
  useEffect(() => {
    height.value = withTiming(targetHeight, { duration: 100 });
  }, [targetHeight]);
  
  const animatedStyle = useAnimatedStyle(() => ({
    height: height.value,
  }));
  
  return <Animated.View style={[styles.waveBar, animatedStyle]} />;
}

function VisualizationRing({ mode }: { mode: 'idle' | 'listening' | 'speaking' }) {
  const scale = useSharedValue(1);
  const opacity = useSharedValue(0.5);

  useEffect(() => {
    if (mode === 'speaking') {
      scale.value = withRepeat(withSequence(withTiming(1.3, { duration: 1000 }), withTiming(1, { duration: 1000 })), -1, true);
      opacity.value = withRepeat(withSequence(withTiming(0, { duration: 1000 }), withTiming(0.5, { duration: 1000 })), -1, true);
    } else if (mode === 'listening') {
      scale.value = withTiming(1.1, { duration: 500 });
      opacity.value = withTiming(0.2, { duration: 500 });
    } else {
      scale.value = withTiming(1, { duration: 500 });
      opacity.value = withTiming(1, { duration: 500 });
    }
  }, [mode]);

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [{ scale: scale.value }],
    opacity: opacity.value,
    borderColor: mode === 'speaking' ? "rgba(200,81,42,0.8)" : mode === 'listening' ? colors.accent : "#E9D7C7"
  }));

  return <Animated.View style={[styles.orbRing, animatedStyle]} />;
}

function VisualizationOrb({ mode, hasError }: { mode: 'idle' | 'listening' | 'speaking', hasError: boolean }) {
  const scale = useSharedValue(1);
  const colorProgress = useSharedValue(0);

  useEffect(() => {
    if (mode === 'speaking') {
      scale.value = withRepeat(withSequence(withTiming(1.15, { duration: 800 }), withTiming(1, { duration: 800 })), -1, true);
      colorProgress.value = withRepeat(withTiming(1, { duration: 2000 }), -1, true);
    } else if (mode === 'listening') {
      scale.value = withTiming(1.05, { duration: 300 });
      colorProgress.value = withTiming(0, { duration: 300 });
    } else {
      scale.value = withTiming(1, { duration: 500 });
      colorProgress.value = withTiming(0, { duration: 500 });
    }
  }, [mode]);

  const animatedStyle = useAnimatedStyle(() => {
    const backgroundColor = interpolateColor(
      colorProgress.value,
      [0, 0.5, 1],
      [
        mode === 'listening' ? colors.accent : colors.panel,
        '#A74223', // speaking color 1
        '#D95831'  // speaking color 2
      ]
    );
    const borderColor = mode === 'listening' ? colors.accent : mode === 'speaking' ? '#A74223' : colors.line;

    return {
      transform: [{ scale: scale.value }],
      backgroundColor,
      borderColor,
    };
  });

  return (
    <>
      {/* @ts-ignore */}
      <Animated.View style={[styles.orb, animatedStyle]} sharedTransitionTag="ai-orb">
        {hasError ? (
          <WifiOff color={colors.ink} size={28} />
        ) : mode === 'listening' ? (
          <Mic color="#fff" size={30} />
        ) : mode === 'speaking' ? (
          <Activity color="#fff" size={30} />
        ) : (
          <Home color={colors.ink} size={30} />
        )}
      </Animated.View>
    </>
  );
}

export function SessionScreen({ route, navigation }: Props) {
  const { sessionId } = route.params;

  const wsClientRef = useRef<SessionWsClient | null>(null);
  const audioCaptureRef = useRef<AudioCaptureService | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const waitingNudgeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const interruptionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentSoundRef = useRef<Audio.Sound | null>(null);
  const audioQueueRef = useRef<Array<{ payload: string; codec: string }>>([]);
  const drainingAudioRef = useRef(false);
  const reconnectAttemptRef = useRef(0);
  const recordingRef = useRef(false);
  const ignoreNextCloseRef = useRef(false);
  const manualCloseRef = useRef(false);
  const speechDetectedRef = useRef(false);
  const endHoldProgress = useRef(new RNAnimated.Value(0)).current;
  const holdIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [connected, setConnected] = useState(false);
  const [recording, setRecording] = useState(false);
  const [repSpeaking, setRepSpeaking] = useState(false);
  const [aiSpeaking, setAiSpeaking] = useState(false);
  const [playingAudio, setPlayingAudio] = useState(false);
  const [meterDb, setMeterDb] = useState(-70);
  const [sessionSeconds, setSessionSeconds] = useState(0);
  const [statusLabel, setStatusLabel] = useState("Connecting...");
  const [error, setError] = useState<string | null>(null);
  const [liveTranscript, setLiveTranscript] = useState("Press and hold the mic to start.");
  const [homeownerPreview, setHomeownerPreview] = useState("");
  const [interruptionCue, setInterruptionCue] = useState<string | null>(null);
  const [reconnectAttempt, setReconnectAttempt] = useState(0);
  const [showSavePartial, setShowSavePartial] = useState(false);
  const [showWaitingNudge, setShowWaitingNudge] = useState(false);
  const [endingSession, setEndingSession] = useState(false);

  const meterPercent = useMemo(() => meterToPercent(meterDb), [meterDb]);
  const waveHeights = useMemo(
    () =>
      Array.from({ length: WAVE_BAR_COUNT }, (_, index) => {
        const centerOffset = Math.abs(index - (WAVE_BAR_COUNT - 1) / 2);
        const falloff = 1 - centerOffset / ((WAVE_BAR_COUNT - 1) / 2 + 0.5);
        const activeHeight = 16 + meterPercent * 96 * Math.max(0.18, falloff);
        return repSpeaking || recording ? activeHeight : 10 + (index % 3) * 3;
      }),
    [meterPercent, recording, repSpeaking]
  );

  useEffect(() => {
    const timer = setInterval(() => {
      setSessionSeconds((current) => current + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  function clearReconnectTimer() {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }

  function clearWaitingNudgeTimer() {
    if (waitingNudgeTimerRef.current) {
      clearTimeout(waitingNudgeTimerRef.current);
      waitingNudgeTimerRef.current = null;
    }
    setShowWaitingNudge(false);
  }

  function scheduleWaitingNudge() {
    clearWaitingNudgeTimer();
    if (!connected || recordingRef.current || repSpeaking || aiSpeaking || playingAudio || showSavePartial || endingSession) {
      return;
    }
    waitingNudgeTimerRef.current = setTimeout(() => {
      setShowWaitingNudge(true);
    }, NUDGE_DELAY_MS);
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

  async function stopCurrentSound() {
    const currentSound = currentSoundRef.current;
    currentSoundRef.current = null;
    if (!currentSound) {
      return;
    }
    try {
      await currentSound.stopAsync();
    } catch {
      // Ignore stop failures for best-effort barge-in behavior.
    }
    try {
      await currentSound.unloadAsync();
    } catch {
      // Ignore unload failures.
    }
  }

  async function cancelAudioPlayback() {
    audioQueueRef.current = [];
    await stopCurrentSound();
    drainingAudioRef.current = false;
    setPlayingAudio(false);
  }

  async function playAudioChunk(payload: string, codec: string): Promise<void> {
    const baseDir = FileSystem.cacheDirectory || FileSystem.documentDirectory;
    if (!baseDir || !payload) {
      return;
    }

    const extension = extForCodec(codec);
    const filePath = `${baseDir}doordrill-ai-${Date.now()}-${Math.random().toString(16).slice(2)}.${extension}`;

    try {
      await configurePlaybackAudioMode();
      await FileSystem.writeAsStringAsync(filePath, payload, {
        encoding: FileSystem.EncodingType.Base64,
      });

      const { sound } = await Audio.Sound.createAsync(
        { uri: filePath },
        { shouldPlay: true, volume: 1.0 }
      );
      currentSoundRef.current = sound;

      await new Promise<void>((resolve) => {
        sound.setOnPlaybackStatusUpdate((status) => {
          if (!status.isLoaded || status.didJustFinish) {
            resolve();
          }
        });
      });
    } catch {
      // Best-effort playback only.
    } finally {
      await stopCurrentSound();
      await FileSystem.deleteAsync(filePath, { idempotent: true }).catch(() => undefined);
    }
  }

  async function drainAudioQueue() {
    if (drainingAudioRef.current) {
      return;
    }

    drainingAudioRef.current = true;
    setPlayingAudio(true);

    while (audioQueueRef.current.length > 0) {
      const nextChunk = audioQueueRef.current.shift();
      if (!nextChunk) {
        continue;
      }
      await playAudioChunk(nextChunk.payload, nextChunk.codec);
    }

    drainingAudioRef.current = false;
    setPlayingAudio(false);
  }

  function enqueueAudio(payload: string, codec: string) {
    if (!payload) {
      return;
    }
    audioQueueRef.current.push({ payload, codec });
    void drainAudioQueue();
  }

  function scheduleReconnect(message: string) {
    if (manualCloseRef.current || reconnectTimerRef.current || showSavePartial || endingSession) {
      return;
    }

    const nextAttempt = reconnectAttemptRef.current + 1;
    if (nextAttempt > RECONNECT_DELAYS_MS.length) {
      setConnected(false);
      setStatusLabel("Connection lost");
      setError("Connection lost. Save your partial session and finish later.");
      setShowSavePartial(true);
      clearWaitingNudgeTimer();
      return;
    }

    reconnectAttemptRef.current = nextAttempt;
    setReconnectAttempt(nextAttempt);
    setConnected(false);
    setStatusLabel(`Reconnecting (${nextAttempt}/3)...`);
    setError(message);
    clearWaitingNudgeTimer();
    void cancelAudioPlayback();

    reconnectTimerRef.current = setTimeout(() => {
      reconnectTimerRef.current = null;
      void connectSocket();
    }, RECONNECT_DELAYS_MS[nextAttempt - 1]);
  }

  function handleSocketClosed() {
    if (ignoreNextCloseRef.current) {
      ignoreNextCloseRef.current = false;
      return;
    }
    if (manualCloseRef.current) {
      return;
    }
    scheduleReconnect("Connection dropped. Attempting to reconnect...");
  }

  function handleInboundEvent(event: WsInboundEvent) {
    if (event.type === "server.session.state") {
      const nextState = String(event.payload.state ?? "");

      if (nextState === "connected") {
        setConnected(true);
        setStatusLabel("Listening...");
        setError(null);
        setShowSavePartial(false);
        reconnectAttemptRef.current = 0;
        setReconnectAttempt(0);
        scheduleWaitingNudge();
        return;
      }

      if (nextState === "ai_speaking") {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        setAiSpeaking(true);
        setStatusLabel("AI is responding...");
        setHomeownerPreview("");
        clearWaitingNudgeTimer();
        return;
      }

      if (nextState === "ai_idle") {
        setAiSpeaking(false);
        setStatusLabel("Listening...");
        scheduleWaitingNudge();
        return;
      }

      if (nextState === "rep_speaking") {
        setStatusLabel("Listening...");
        clearWaitingNudgeTimer();
        return;
      }

      if (nextState === "rep_idle") {
        setStatusLabel("Listening...");
        scheduleWaitingNudge();
        return;
      }

      if (nextState === "barge_in_detected") {
        Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
        showInterruptCue("You interrupted the homeowner");
        void cancelAudioPlayback();
        return;
      }
    }

    if (event.type === "server.stt.partial") {
      const partialText = String(event.payload.text ?? "").trim();
      if (partialText) {
        setLiveTranscript(partialText);
      }
      return;
    }

    if (event.type === "server.stt.final") {
      const finalText = String(event.payload.text ?? "").trim();
      if (finalText) {
        setLiveTranscript(finalText);
      }
      return;
    }

    if (event.type === "server.ai.text.delta") {
      const token = String(event.payload.token ?? "");
      if (token) {
        setHomeownerPreview((current) => `${current}${token}`.trimStart());
      }
      return;
    }

    if (event.type === "server.ai.audio.chunk") {
      enqueueAudio(String(event.payload.payload ?? ""), String(event.payload.codec ?? "mp3"));
      return;
    }

    if (event.type === "server.error") {
      setError(String(event.payload.message ?? "Session error"));
    }
  }

  async function connectSocket() {
    if (manualCloseRef.current) {
      return;
    }

    clearReconnectTimer();
    if (wsClientRef.current) {
      ignoreNextCloseRef.current = true;
      wsClientRef.current.close();
    }

    const client = new SessionWsClient(sessionId);
    wsClientRef.current = client;

    try {
      await client.connect(
        (event) => {
          handleInboundEvent(event);
        },
        () => {
          handleSocketClosed();
        }
      );
      setConnected(true);
      setError(null);
      setStatusLabel(aiSpeaking || playingAudio ? "AI is responding..." : "Listening...");
      setShowSavePartial(false);
      reconnectAttemptRef.current = 0;
      setReconnectAttempt(0);
      scheduleWaitingNudge();
    } catch (err) {
      scheduleReconnect(err instanceof Error ? err.message : "Failed to reconnect");
    }
  }

  async function startRecording() {
    if (endingSession || showSavePartial) {
      return;
    }
    if (!connected) {
      setError("Connection unavailable. Reconnecting now...");
      scheduleReconnect("Connection unavailable. Reconnecting now...");
      return;
    }

    const audioCapture = audioCaptureRef.current;
    if (!audioCapture || recordingRef.current) {
      return;
    }

    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
    speechDetectedRef.current = false;
    setError(null);
    clearWaitingNudgeTimer();
    if (aiSpeaking || playingAudio) {
      showInterruptCue("You interrupted the homeowner");
      await cancelAudioPlayback();
    }

    try {
      await audioCapture.start();
      recordingRef.current = true;
      setRecording(true);
      setStatusLabel("Listening...");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start microphone capture");
      recordingRef.current = false;
      setRecording(false);
    }
  }

  async function stopRecordingAndSend() {
    if (!recordingRef.current) {
      return;
    }

    const client = wsClientRef.current;
    const audioCapture = audioCaptureRef.current;
    recordingRef.current = false;
    setRecording(false);

    if (!audioCapture) {
      return;
    }

    try {
      const chunk = await audioCapture.stop();
      if (chunk && speechDetectedRef.current && client?.isConnected()) {
        client.sendAudioChunk(chunk);
        Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        setStatusLabel("AI is responding...");
      } else if (!speechDetectedRef.current) {
        setError("No speech detected. Hold the mic and speak clearly.");
        scheduleWaitingNudge();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send captured audio");
    }
  }

  async function completeSessionFlow() {
    setEndingSession(true);
    manualCloseRef.current = true;
    clearReconnectTimer();
    clearWaitingNudgeTimer();
    if (recordingRef.current) {
      await stopRecordingAndSend();
    }
    try {
      wsClientRef.current?.endSession();
    } catch {
      // Ignore send failures during shutdown.
    }
    ignoreNextCloseRef.current = true;
    wsClientRef.current?.close();
    wsClientRef.current = null;
    await cancelAudioPlayback();
    navigation.replace("Score", { sessionId });
  }

  async function savePartialSession() {
    setEndingSession(true);
    manualCloseRef.current = true;
    clearReconnectTimer();
    clearWaitingNudgeTimer();
    ignoreNextCloseRef.current = true;
    wsClientRef.current?.close();
    wsClientRef.current = null;
    await cancelAudioPlayback();
    navigation.replace("Score", { sessionId });
  }

  useEffect(() => {
    const audioCapture = new AudioCaptureService();
    audioCapture.onMeter((db) => setMeterDb(db));
    audioCapture.onVadChange((speaking) => {
      setRepSpeaking(speaking);
      if (!recordingRef.current) {
        return;
      }
      if (speaking) {
        speechDetectedRef.current = true;
        setShowWaitingNudge(false);
      }
      wsClientRef.current?.sendVadState(speaking);
    });
    audioCaptureRef.current = audioCapture;

    void configurePlaybackAudioMode();
    void connectSocket();

    return () => {
      manualCloseRef.current = true;
      clearReconnectTimer();
      clearWaitingNudgeTimer();
      if (interruptionTimerRef.current) {
        clearTimeout(interruptionTimerRef.current);
      }
      ignoreNextCloseRef.current = true;
      wsClientRef.current?.close();
      wsClientRef.current = null;
      void cancelAudioPlayback();
      void audioCaptureRef.current?.stop().catch(() => undefined);
      audioCaptureRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const statusTone = !connected || reconnectAttempt > 0 ? styles.statusWarn : aiSpeaking || playingAudio ? styles.statusHot : styles.statusCool;

  return (
    <LinearGradient colors={["#FDFDFD", "#F7F4EE", "#EBE5D9"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.topBar}>
          <View>
            <Text style={styles.topLabel}>Live Drill</Text>
            <Text style={[styles.statusLabel, statusTone]}>{statusLabel}</Text>
          </View>
          <Text style={styles.timer}>{formatTimer(sessionSeconds)}</Text>
        </View>

        <View style={styles.centerStage}>
          {interruptionCue ? (
            <View style={styles.interruptionBanner}>
              <Text style={styles.interruptionText}>{interruptionCue}</Text>
            </View>
          ) : null}

          <View style={styles.orbShell}>
            <VisualizationRing mode={aiSpeaking || playingAudio ? 'speaking' : repSpeaking || recording ? 'listening' : 'idle'} />
            <VisualizationOrb 
              mode={aiSpeaking || playingAudio ? 'speaking' : repSpeaking || recording ? 'listening' : 'idle'} 
              hasError={reconnectAttempt > 0} 
            />
          </View>

          <View style={styles.waveformRow}>
            {waveHeights.map((height, index) => (
              <WaveBar key={index} targetHeight={height} />
            ))}
          </View>

          <Text style={styles.waveformHint}>Mic level reacts only when you speak.</Text>
        </View>

        <BlurView intensity={40} tint="light" style={styles.captionCard}>
          <Text style={styles.captionLabel}>Live Transcript</Text>
          <Text style={styles.captionText} numberOfLines={3}>
            {liveTranscript}
          </Text>
          {homeownerPreview ? (
            <View style={styles.homeownerPreview}>
              <Volume2 color={colors.accent} size={14} />
              <Text style={styles.homeownerPreviewText} numberOfLines={2}>
                {homeownerPreview}
              </Text>
            </View>
          ) : null}
          {showWaitingNudge ? <Text style={styles.waitingNudge}>The homeowner is waiting...</Text> : null}
          {error ? <Text style={styles.errorText}>{error}</Text> : null}
        </BlurView>

        {showSavePartial ? (
          <BlurView intensity={40} tint="light" style={styles.savePartialCard}>
            <Text style={styles.savePartialTitle}>Connection not recovered</Text>
            <Text style={styles.savePartialBody}>We tried three reconnect attempts. Save the partial session and review what was captured.</Text>
            <View style={styles.savePartialActions}>
              <Pressable
                style={styles.retryNowButton}
                onPress={() => {
                  setShowSavePartial(false);
                  reconnectAttemptRef.current = 0;
                  setReconnectAttempt(0);
                  setError(null);
                  void connectSocket();
                }}
              >
                <Text style={styles.retryNowLabel}>Retry now</Text>
              </Pressable>
              <Pressable style={styles.savePartialButton} onPress={() => void savePartialSession()}>
                <Text style={styles.savePartialLabel}>Save partial session</Text>
              </Pressable>
            </View>
          </BlurView>
        ) : null}

        <View style={styles.bottomBar}>
          <Pressable
            disabled={!connected || endingSession || showSavePartial}
            onPressIn={() => {
              void startRecording();
            }}
            onPressOut={() => {
              void stopRecordingAndSend();
            }}
            style={[styles.micButton, (!connected || endingSession || showSavePartial) && styles.micButtonDisabled, recording && styles.micButtonActive]}
          >
            {connected ? <Mic color="#fff" size={36} strokeWidth={2.5} /> : <MicOff color={colors.muted} size={32} />}
          </Pressable>

          <Pressable
            disabled={endingSession}
            delayLongPress={HOLD_END_MS}
            onLongPress={() => {
              if (holdIntervalRef.current) clearInterval(holdIntervalRef.current);
              Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
              void completeSessionFlow();
            }}
            onPressIn={() => {
              Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
              let ticks = 0;
              holdIntervalRef.current = setInterval(() => {
                ticks++;
                if (ticks < 5) Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
              }, HOLD_END_MS / 5);

              RNAnimated.timing(endHoldProgress, {
                toValue: 1,
                duration: HOLD_END_MS,
                useNativeDriver: false,
              }).start();
            }}
            onPressOut={() => {
              if (holdIntervalRef.current) clearInterval(holdIntervalRef.current);
              RNAnimated.timing(endHoldProgress, {
                toValue: 0,
                duration: 120,
                useNativeDriver: false,
              }).start();
            }}
            style={styles.endButton}
          >
            <RNAnimated.View
              style={[
                styles.endButtonFill,
                {
                  width: endHoldProgress.interpolate({
                    inputRange: [0, 1],
                    outputRange: ["0%", "100%"],
                  }),
                },
              ]}
            />
            <Text style={styles.endButtonLabel}>{endingSession ? "Saving..." : "Press and hold to end"}</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.bg },
  container: { flex: 1, paddingHorizontal: 20, paddingTop: 12, paddingBottom: 20 },
  topBar: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
  },
  topLabel: {
    color: colors.muted,
    fontSize: 12,
    fontWeight: "800",
    textTransform: "uppercase",
    letterSpacing: 0.8,
  },
  statusLabel: {
    marginTop: 8,
    fontSize: 22,
    fontWeight: "800",
  },
  statusCool: { color: colors.ink },
  statusHot: { color: colors.accent },
  statusWarn: { color: "#8D5D1B" },
  timer: {
    color: colors.ink,
    fontSize: 18,
    fontWeight: "800",
    fontVariant: ["tabular-nums"],
  },
  centerStage: {
    flex: 1,
    alignItems: "center",
    justifyContent: "center",
    gap: 22,
  },
  interruptionBanner: {
    position: "absolute",
    top: 20,
    borderRadius: 999,
    backgroundColor: "#FFF2E4",
    borderWidth: 1,
    borderColor: "#E7C39B",
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  interruptionText: { color: "#8D5D1B", fontSize: 13, fontWeight: "700" },
  orbShell: {
    width: 224,
    height: 224,
    alignItems: "center",
    justifyContent: "center",
  },
  orbRing: {
    position: "absolute",
    width: 224,
    height: 224,
    borderRadius: 112,
    borderWidth: 1,
    borderColor: "rgba(0,0,0,0.1)",
  },
  orbRingActive: {
    borderColor: "rgba(200,81,42,0.3)",
  },
  orb: {
    width: 152,
    height: 152,
    borderRadius: 76,
    backgroundColor: "rgba(255, 255, 255, 0.8)",
    borderWidth: 1,
    borderColor: colors.line,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.08,
    shadowRadius: 18,
    elevation: 4,
  },
  orbCool: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  orbHot: {
    backgroundColor: "#A74223",
    borderColor: "#A74223",
  },
  waveformRow: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: 8,
    height: 110,
  },
  waveBar: {
    width: 8,
    borderRadius: 999,
    backgroundColor: colors.accent,
    opacity: 0.88,
  },
  waveformHint: { color: colors.muted, fontSize: 12, fontWeight: "600" },
  captionCard: {
    borderRadius: 22,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: "rgba(255,255,255,0.5)",
    padding: 18,
    gap: 10,
    overflow: "hidden",
  },
  captionLabel: { color: colors.muted, fontSize: 12, fontWeight: "800", textTransform: "uppercase", letterSpacing: 0.8 },
  captionText: { color: colors.ink, fontSize: 18, fontWeight: "700", lineHeight: 24 },
  homeownerPreview: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    borderRadius: 14,
    backgroundColor: colors.accentSoft,
    paddingHorizontal: 12,
    paddingVertical: 10,
  },
  homeownerPreviewText: { flex: 1, color: colors.accent, fontSize: 14, lineHeight: 20, fontWeight: "600" },
  waitingNudge: { color: colors.muted, fontSize: 13, fontStyle: "italic" },
  errorText: { color: "#AF2D18", fontSize: 13, fontWeight: "700", lineHeight: 19 },
  savePartialCard: {
    marginTop: 14,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: "#E2C9B3",
    backgroundColor: "#FFF5EA",
    padding: 18,
    gap: 10,
    overflow: "hidden",
  },
  savePartialTitle: { color: colors.ink, fontSize: 16, fontWeight: "800" },
  savePartialBody: { color: colors.muted, fontSize: 14, lineHeight: 20 },
  savePartialActions: { flexDirection: "row", gap: 10 },
  retryNowButton: {
    flex: 1,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: "rgba(255,255,255,0.5)",
    paddingVertical: 14,
    alignItems: "center",
  },
  retryNowLabel: { color: colors.ink, fontWeight: "700" },
  savePartialButton: {
    flex: 1,
    borderRadius: 14,
    backgroundColor: colors.accent,
    paddingVertical: 14,
    alignItems: "center",
  },
  savePartialLabel: { color: "#fff", fontWeight: "800" },
  bottomBar: {
    paddingTop: 18,
    alignItems: "center",
    gap: 16,
  },
  micButton: {
    width: 108,
    height: 108,
    borderRadius: 54,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: colors.accent,
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.28,
    shadowRadius: 18,
  },
  micButtonActive: {
    backgroundColor: "#A74223",
  },
  micButtonDisabled: {
    backgroundColor: "#E7DDD2",
    borderWidth: 0,
    shadowOpacity: 0,
  },
  endButton: {
    width: "100%",
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: "rgba(255, 255, 255, 0.5)",
    overflow: "hidden",
    alignItems: "center",
    justifyContent: "center",
    minHeight: 54,
  },
  endButtonFill: {
    ...StyleSheet.absoluteFillObject,
    width: "0%",
    backgroundColor: "rgba(200,81,42,0.16)",
  },
  endButtonLabel: {
    color: colors.ink,
    fontSize: 14,
    fontWeight: "800",
    paddingVertical: 16,
  },
});
