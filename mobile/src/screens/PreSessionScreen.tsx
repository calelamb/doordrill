import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { Audio } from "expo-av";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { ChevronLeft } from "lucide-react-native";
import BottomSheet, { BottomSheetBackdrop, BottomSheetView } from "@gorhom/bottom-sheet";
import * as Haptics from "expo-haptics";
import Animated, { FadeIn, FadeOut } from "react-native-reanimated";
import { BlurView } from "expo-blur";

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

export function PreSessionScreen({ route, navigation }: Props) {
  const { assignmentId, scenarioId } = route.params;
  const { repId } = useSession();
  
  const bottomSheetRef = useRef<BottomSheet>(null);
  
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [assignment, setAssignment] = useState<RepAssignment | null>(null);
  const [scenario, setScenario] = useState<ScenarioBrief | null>(null);
  
  // Fake status loading stages for AirPods effect
  const [statusStage, setStatusStage] = useState(0); 
  // 0 = Establishing connection...
  // 1 = Loading persona...
  // 2 = Homeowner is ready

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
    if (!repId || !assignment || starting) return;

    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Heavy);
    setStarting(true);
    setError(null);
    
    try {
      const reachable = await checkApiReachable();
      if (!reachable) throw new Error("No internet connection.");

      const permission = await Audio.getPermissionsAsync();
      const granted = permission.granted ? permission : await Audio.requestPermissionsAsync();
      if (!granted.granted) throw new Error("Microphone access is required.");

      const session = await createRepSession(repId, assignment.id, assignment.scenario_id);
      
      bottomSheetRef.current?.close();
      
      // Delay slightly for bottom sheet close animation
      setTimeout(() => {
        navigation.replace("Session", {
          assignmentId: assignment.id,
          scenarioId: assignment.scenario_id,
          sessionId: session.id,
        });
      }, 300);

    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start drill");
      setStarting(false);
    }
  }, [assignment, navigation, repId, starting]);

  const renderBackdrop = useCallback(
    (props: any) => (
      <BottomSheetBackdrop {...props} disappearsOnIndex={-1} appearsOnIndex={0}>
        <BlurView style={StyleSheet.absoluteFill} tint="dark" intensity={60} />
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
    <View style={styles.container}>
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

          <View style={styles.animationContainer}>
            {/* Simple orb placeholder for now, we'll upgrade with Reanimated/Lottie later if needed */}
            <Animated.View 
              style={[
                styles.orb, 
                statusStage === 2 ? styles.orbReady : undefined,
                starting && styles.orbStarting
              ]} 
            />
          </View>

          <View style={styles.statusBox}>
            <Animated.Text key={statusStage} entering={FadeIn} exiting={FadeOut} style={styles.statusText}>
              {getStatusText()}
            </Animated.Text>
          </View>

          <View style={styles.detailsCard}>
            <Text style={styles.scenarioName}>{scenario?.name ?? "Loading..."}</Text>
            <Text style={styles.personaInfo}>{persona.name} · {persona.attitude}</Text>
            <Text style={styles.personaHint}>{persona.cue}</Text>
          </View>

          {error && (
            <View style={styles.errorBox}>
              <Text style={styles.errorText}>{error}</Text>
            </View>
          )}

          <View style={styles.footer}>
            <Pressable
              style={[styles.startBtn, (starting || loading || !assignment || statusStage < 2) && styles.startBtnDisabled]}
              onPress={startDrill}
              disabled={starting || loading || !assignment || statusStage < 2}
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
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  sheetBackground: {
    backgroundColor: colors.panel,
    borderRadius: 32,
  },
  sheetIndicator: {
    backgroundColor: colors.line,
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
    backgroundColor: colors.bg,
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
  orb: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: colors.accentSoft,
    borderWidth: 2,
    borderColor: colors.accent,
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
  detailsCard: {
    backgroundColor: colors.bg,
    borderRadius: 24,
    padding: 20,
    gap: 8,
    borderWidth: 1,
    borderColor: colors.line,
  },
  scenarioName: {
    fontSize: 22,
    fontFamily: "Poppins_800ExtraBold",
    color: colors.ink,
  },
  personaInfo: {
    fontSize: 16,
    fontWeight: "700",
    color: colors.muted,
  },
  personaHint: {
    fontSize: 14,
    lineHeight: 22,
    color: colors.muted,
    marginTop: 4,
  },
  errorBox: {
    marginTop: 16,
    padding: 12,
    backgroundColor: "#FEE2E2",
    borderRadius: 12,
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
