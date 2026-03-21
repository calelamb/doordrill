import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { Audio } from "expo-av";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { ChevronLeft, Radar, Radio, TreePine } from "lucide-react-native";
import BottomSheet, { BottomSheetBackdrop, BottomSheetView } from "@gorhom/bottom-sheet";
import * as Haptics from "expo-haptics";
import Animated, { FadeIn, FadeOut, useSharedValue, useAnimatedStyle, withRepeat, withTiming, Easing, withDelay } from "react-native-reanimated";
import { LinearGradient } from "expo-linear-gradient";

import { RootStackParamList } from "../navigation/types";
import { checkApiReachable, createRepSession, fetchRepAssignments, fetchRepScenario } from "../services/api";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { RepAssignment, ScenarioBrief } from "../types";

type Props = NativeStackScreenProps<RootStackParamList, "PreSession">;

function personaSummary(scenario: ScenarioBrief | null): { name: string; attitude: string; cue: string } {
  const persona = scenario?.persona ?? {};
  return {
    name: String(persona.name || "Homeowner"),
    attitude: String(persona.attitude || "Guarded"),
    cue: String(
      persona.softening_condition ||
        "They will warm up if you sound credible, concise, and focused on the home."
    ),
  };
}

function PulsingOrb({ isReady, isStarting }: { isReady: boolean, isStarting: boolean }) {
  const pulse1 = useSharedValue(0);
  const pulse2 = useSharedValue(0);

  useEffect(() => {
    if (!isReady && !isStarting) {
      pulse1.value = withRepeat(withTiming(1, { duration: 2000, easing: Easing.out(Easing.ease) }), -1, false);
      pulse2.value = withDelay(1000, withRepeat(withTiming(1, { duration: 2000, easing: Easing.out(Easing.ease) }), -1, false));
    } else {
      pulse1.value = withTiming(0);
      pulse2.value = withTiming(0);
    }
  }, [isReady, isStarting, pulse1, pulse2]);

  const ring1Style = useAnimatedStyle(() => ({
    transform: [{ scale: 1 + pulse1.value * 1.5 }],
    opacity: 1 - pulse1.value,
  }));

  const ring2Style = useAnimatedStyle(() => ({
    transform: [{ scale: 1 + pulse2.value * 1.5 }],
    opacity: 1 - pulse2.value,
  }));

  return (
    <View style={styles.animationContainer}>
      <View style={styles.orbWrapper}>
        <Animated.View style={[styles.pulseRing, ring1Style]} />
        <Animated.View style={[styles.pulseRing, ring2Style]} />
        <Animated.View 
          style={[
            styles.orb, 
            isReady ? styles.orbReady : undefined,
            isStarting && styles.orbStarting
          ]} 
        >
          <Radio size={32} color={isReady ? "#fff" : colors.accent} />
        </Animated.View>
      </View>
    </View>
  );
}

export function PreSessionScreen({ route, navigation }: Props) {
  const { assignmentId, scenarioId, isFirstSession = false } = route.params;
  const { repId } = useSession();
  
  const bottomSheetRef = useRef<BottomSheet>(null);
  
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assignment, setAssignment] = useState<RepAssignment | null>(null);
  const [scenario, setScenario] = useState<ScenarioBrief | null>(null);
  const [tipsDismissed, setTipsDismissed] = useState(!isFirstSession);
  
  // Fake status loading stages for AirPods effect
  const [statusStage, setStatusStage] = useState(0); 
  // 0 = Establishing connection...
  // 1 = Loading persona...
  // 2 = Homeowner is ready

  useEffect(() => {
    if (!isFirstSession) {
      setTipsDismissed(true);
      return;
    }

    setTipsDismissed(false);
    const timer = setTimeout(() => {
      setTipsDismissed(true);
    }, 4000);

    return () => clearTimeout(timer);
  }, [isFirstSession]);

  useEffect(() => {
    async function loadBrief() {
      if (!repId) return;
      setLoading(true);
      setError(null);
      try {
        const [assignments, scenarioResult] = await Promise.all([
          fetchRepAssignments(repId),
          fetchRepScenario(repId, scenarioId),
        ]);
        setAssignment(assignments.find((item) => item.id === assignmentId) ?? null);
        setScenario(scenarioResult);
        
        // Staggered status updates with haptics
        setTimeout(() => {
          setStatusStage(1);
          Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light);
        }, 800);
        
        setTimeout(() => {
          setStatusStage(2);
          Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
        }, 1800);
        
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load drill brief");
      } finally {
        setLoading(false);
      }
    }

    void loadBrief();
  }, [assignmentId, repId, scenarioId]);

  const persona = useMemo(() => personaSummary(scenario), [scenario]);

  const startDrill = useCallback(async () => {
    if (!repId || starting) return;

    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    setStarting(true);
    setError(null);
    
    try {
      const reachable = await checkApiReachable();
      if (!reachable) throw new Error("No internet connection.");

      const permission = await Audio.getPermissionsAsync();
      const granted = permission.granted ? permission : await Audio.requestPermissionsAsync();
      if (!granted.granted) throw new Error("Microphone access is required.");

      const session = await createRepSession(repId, assignmentId ?? null, scenarioId);
      
      bottomSheetRef.current?.close();
      
      // Delay slightly for bottom sheet close animation
        setTimeout(() => {
          navigation.replace("Session", {
            assignmentId: assignmentId ?? undefined,
            scenarioId: scenarioId,
            sessionId: session.id,
            isFirstSession,
          });
        }, 300);

    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start drill");
      setStarting(false);
    }
  }, [assignmentId, isFirstSession, scenarioId, navigation, repId, starting]);

  const renderBackdrop = useCallback(
    (props: any) => (
      <BottomSheetBackdrop {...props} disappearsOnIndex={-1} appearsOnIndex={0}>
        <View style={[StyleSheet.absoluteFill, { backgroundColor: 'rgba(0,0,0,0.7)' }]} />
      </BottomSheetBackdrop>
    ),
    []
  );

  const getStatusText = () => {
    if (error) return "Connection Failed";
    if (statusStage === 0) return "Establishing connection...";
    if (statusStage === 1) return "Loading persona...";
    return "Homeowner is ready";
  };

  return (
    <LinearGradient colors={["#FBF9F5", "#EFEEEA", "#E4E2DE"]} style={styles.container}>
      <BottomSheet
        ref={bottomSheetRef}
        index={0}
        snapPoints={["65%", "85%"]}
        enablePanDownToClose
        onClose={() => navigation.goBack()}
        backdropComponent={renderBackdrop}
        backgroundStyle={styles.sheetBackground}
        handleIndicatorStyle={styles.sheetIndicator}
      >
        <BottomSheetView style={styles.sheetContent}>
          <View style={styles.header}>
            <Pressable onPress={() => bottomSheetRef.current?.close()} style={styles.closeBtn}>
              <ChevronLeft color={colors.ink} size={24} />
            </Pressable>
            <Text style={styles.headerTitle}>Drill Brief</Text>
            <View style={{ width: 40 }} />
          </View>

          {isFirstSession && !tipsDismissed ? (
            <Animated.View entering={FadeIn} exiting={FadeOut} style={styles.tipsCard}>
              <Text style={styles.tipsTitle}>A few tips:</Text>
              <Text style={styles.tipItem}>• Speak naturally, just like a real door.</Text>
              <Text style={styles.tipItem}>• The AI responds like a real homeowner would.</Text>
              <Text style={styles.tipItem}>• You&apos;ll get a score and breakdown after.</Text>
            </Animated.View>
          ) : null}

          <PulsingOrb isReady={statusStage === 2} isStarting={starting} />

          <View style={styles.infoContainer}>
            <Text style={styles.scenarioName}>{scenario?.name ?? "Loading..."}</Text>
            <Text style={styles.personaInfo}>{persona.name} · {persona.attitude}</Text>
            
            <View style={styles.statusBox}>
              <Animated.Text key={statusStage} entering={FadeIn} exiting={FadeOut} style={styles.statusText}>
                {getStatusText()}
              </Animated.Text>
            </View>

            <Text style={styles.personaHint}>{persona.cue}</Text>
          </View>

          {error && (
            <View style={styles.errorBox}>
              <Text style={styles.errorText}>{error}</Text>
            </View>
          )}

          <View style={styles.footer}>
            <Pressable
              style={[styles.startBtn, (starting || loading || statusStage < 2 || (assignmentId && !assignment)) && styles.startBtnDisabled]}
              onPress={startDrill}
              disabled={starting || loading || statusStage < 2 || (!!assignmentId && !assignment)}
            >
              {starting ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.startBtnText}>
                  {statusStage < 2 ? "Please Wait" : "Swipe up to knock"}
                </Text>
              )}
            </Pressable>
          </View>

        </BottomSheetView>
      </BottomSheet>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  sheetBackground: {
    backgroundColor: "#FBF9F5",
    borderRadius: 32,
    borderWidth: 1,
    borderColor: colors.line,
  },
  sheetIndicator: {
    backgroundColor: "rgba(0, 0, 0, 0.15)",
    width: 40,
  },
  sheetContent: {
    flex: 1,
    paddingHorizontal: 24,
    paddingTop: 8,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 24,
  },
  closeBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: "rgba(0, 0, 0, 0.05)",
    alignItems: "center",
    justifyContent: "center",
  },
  headerTitle: {
    fontSize: 16,
    fontFamily: "Poppins_800ExtraBold",
    color: colors.ink,
    textTransform: "uppercase",
  },
  animationContainer: {
    height: 160,
    alignItems: "center",
    justifyContent: "center",
  },
  tipsCard: {
    marginBottom: 16,
    borderRadius: 20,
    paddingVertical: 14,
    paddingHorizontal: 16,
    backgroundColor: "rgba(22, 101, 52, 0.08)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: "rgba(22, 101, 52, 0.18)",
    gap: 6,
  },
  tipsTitle: {
    fontSize: 14,
    fontFamily: "Poppins_700Bold",
    color: colors.ink,
  },
  tipItem: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.muted,
    fontFamily: "Inter_400Regular",
  },
  orbWrapper: {
    width: 80,
    height: 80,
    alignItems: "center",
    justifyContent: "center",
  },
  orb: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: "rgba(74, 222, 128, 0.12)",
    borderWidth: 2,
    borderColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
  },
  orbReady: {
    backgroundColor: colors.accent,
    shadowColor: colors.accent,
    shadowOffset: { width: 0, height: 0 },
    shadowOpacity: 0.5,
    shadowRadius: 20,
  },
  orbStarting: {
    transform: [{ scale: 1.5 }],
    opacity: 0.8,
  },
  pulseRing: {
    position: "absolute",
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: "rgba(22, 101, 52, 0.2)",
  },
  statusBox: {
    alignItems: "center",
    marginVertical: 16,
    height: 24,
  },
  statusText: {
    fontSize: 14,
    fontWeight: "600",
    color: colors.accent,
    textTransform: "uppercase",
    letterSpacing: 1,
  },
  infoContainer: {
    alignItems: "center",
    paddingHorizontal: 20,
  },
  scenarioName: {
    fontSize: 24,
    fontFamily: "Poppins_800ExtraBold",
    color: colors.ink,
    textAlign: "center",
    marginBottom: 6,
  },
  personaInfo: {
    fontSize: 16,
    fontWeight: "700",
    color: colors.muted,
    textAlign: "center",
    marginBottom: 8,
  },
  personaHint: {
    fontSize: 15,
    lineHeight: 24,
    color: colors.muted,
    textAlign: "center",
    marginTop: 8,
  },
  errorBox: {
    marginTop: 16,
    padding: 12,
    backgroundColor: "#FEE2E2",
    borderRadius: 12,
    borderWidth: 1,
    borderColor: "#FECACA",
  },
  errorText: {
    color: "#991B1B",
    fontSize: 14,
    fontWeight: "600",
    textAlign: "center",
  },
  footer: {
    marginTop: "auto",
    paddingBottom: 32,
  },
  startBtn: {
    backgroundColor: colors.accent,
    borderRadius: 24,
    paddingVertical: 20,
    alignItems: "center",
    shadowColor: colors.accent,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.3,
    shadowRadius: 16,
  },
  startBtnDisabled: {
    opacity: 0.6,
  },
  startBtnText: {
    color: "#fff",
    fontSize: 18,
    fontFamily: "Poppins_800ExtraBold",
  },
});
