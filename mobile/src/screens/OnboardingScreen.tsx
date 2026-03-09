import { useMemo, useState } from "react";
import {
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { BarChart2, Bell, Mic, TreePine, Users } from "lucide-react-native";
import Animated, {
  FadeIn,
  FadeInDown,
  FadeOut,
  LinearTransition,
  SlideInRight,
} from "react-native-reanimated";

import { requestPushPermission } from "../services/notifications";

type OnboardingScreenProps = {
  onComplete: () => Promise<void> | void;
};

type SlideDefinition = {
  icon: typeof Mic;
  title: string;
  body: string;
};

const SLIDES: SlideDefinition[] = [
  {
    icon: Mic,
    title: "Train Like It's Real",
    body: "Practice D2D conversations with a lifelike AI homeowner. Get scored, get better.",
  },
  {
    icon: BarChart2,
    title: "Know Exactly Where You Stand",
    body: "Detailed scorecards show your strengths and exactly what to work on after every drill.",
  },
  {
    icon: Users,
    title: "Your Manager Has Your Back",
    body: "Get coaching notes, new drills assigned, and reminders right to your phone.",
  },
];

function OnboardingDot({ active }: { active: boolean }) {
  return (
    <Animated.View
      layout={LinearTransition.springify().damping(18).stiffness(180)}
      style={[styles.dot, active ? styles.dotActive : styles.dotInactive]}
    />
  );
}

type OnboardingSlideProps = {
  slide: SlideDefinition;
  index: number;
  total: number;
  onNext: () => void;
  onSkip: () => void;
};

function OnboardingSlide({ slide, index, total, onNext, onSkip }: OnboardingSlideProps) {
  const Icon = slide.icon;
  const isLast = index === total - 1;

  return (
    <Animated.View
      key={slide.title}
      entering={SlideInRight.duration(300)}
      exiting={FadeOut.duration(180)}
      style={styles.slide}
    >
      <Pressable onPress={onSkip} style={styles.skipButton} accessibilityLabel="Skip onboarding">
        <Text style={styles.skipText}>Skip</Text>
      </Pressable>

      <Animated.View entering={FadeInDown.delay(40).duration(320)} style={styles.brandPill}>
        <TreePine color="#166534" size={16} strokeWidth={2.5} />
        <Text style={styles.brandPillText}>DoorDrill</Text>
      </Animated.View>

      <Animated.View entering={FadeIn.delay(80).duration(320)} style={styles.slideIconShell}>
        <Icon color="#166534" size={38} strokeWidth={2.4} />
      </Animated.View>

      <Animated.Text entering={FadeInDown.delay(120).duration(320)} style={styles.slideTitle}>
        {slide.title}
      </Animated.Text>
      <Animated.Text entering={FadeInDown.delay(160).duration(320)} style={styles.slideBody}>
        {slide.body}
      </Animated.Text>

      <View style={styles.slideFooter}>
        <View style={styles.dotsRow}>
          {SLIDES.map((item, dotIndex) => (
            <OnboardingDot key={item.title} active={dotIndex === index} />
          ))}
        </View>

        <Pressable
          onPress={onNext}
          style={({ pressed }) => [styles.primaryButton, pressed && styles.primaryButtonPressed]}
          accessibilityLabel={isLast ? "Open notification permission step" : "Go to next onboarding slide"}
        >
          <Text style={styles.primaryButtonLabel}>{isLast ? "Get Started" : "Next"}</Text>
        </Pressable>
      </View>
    </Animated.View>
  );
}

export function OnboardingScreen({ onComplete }: OnboardingScreenProps) {
  const [currentIndex, setCurrentIndex] = useState(0);
  const [showPermissionStep, setShowPermissionStep] = useState(false);
  const [finishing, setFinishing] = useState(false);

  const currentSlide = useMemo(() => SLIDES[currentIndex], [currentIndex]);

  const openPermissionStep = () => {
    setShowPermissionStep(true);
  };

  const finishOnboarding = async () => {
    if (finishing) {
      return;
    }
    setFinishing(true);
    try {
      await onComplete();
    } finally {
      setFinishing(false);
    }
  };

  const handleAllowNotifications = async () => {
    if (finishing) {
      return;
    }
    try {
      await requestPushPermission();
    } finally {
      await finishOnboarding();
    }
  };

  const handleNext = () => {
    if (currentIndex >= SLIDES.length - 1) {
      openPermissionStep();
      return;
    }
    setCurrentIndex((value) => value + 1);
  };

  return (
    <LinearGradient colors={["#FCFBF7", "#F3EEE4", "#E6DECF"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.textureOrbTop} pointerEvents="none" />
        <View style={styles.textureOrbBottom} pointerEvents="none" />
        <View style={styles.content}>
          <OnboardingSlide
            slide={currentSlide}
            index={currentIndex}
            total={SLIDES.length}
            onNext={handleNext}
            onSkip={openPermissionStep}
          />
        </View>

        {showPermissionStep ? (
          <View style={styles.permissionBackdrop}>
            <Animated.View
              entering={FadeInDown.duration(260)}
              style={styles.permissionCard}
            >
              <View style={styles.permissionIconShell}>
                <Bell color="#166534" size={40} strokeWidth={2.3} />
              </View>
              <Text style={styles.permissionTitle}>Stay in the loop</Text>
              <Text style={styles.permissionBody}>
                Get notified when your score is ready, a drill is assigned, or your manager leaves feedback.
              </Text>

              <Pressable
                onPress={handleAllowNotifications}
                style={({ pressed }) => [
                  styles.primaryButton,
                  finishing && styles.primaryButtonDisabled,
                  pressed && !finishing && styles.primaryButtonPressed,
                ]}
                disabled={finishing}
                accessibilityLabel="Allow push notifications"
              >
                <Text style={styles.primaryButtonLabel}>
                  {finishing ? "One moment..." : "Allow Notifications"}
                </Text>
              </Pressable>

              <Pressable
                onPress={() => {
                  void finishOnboarding();
                }}
                style={styles.secondaryButton}
                accessibilityLabel="Skip notification permission for now"
              >
                <Text style={styles.secondaryButtonLabel}>Not now</Text>
              </Pressable>
            </Animated.View>
          </View>
        ) : null}
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
    paddingHorizontal: 24,
    paddingVertical: 28,
    justifyContent: "center",
  },
  textureOrbTop: {
    position: "absolute",
    top: 28,
    right: -26,
    width: 170,
    height: 170,
    borderRadius: 85,
    backgroundColor: "rgba(22, 101, 52, 0.08)",
  },
  textureOrbBottom: {
    position: "absolute",
    bottom: 80,
    left: -46,
    width: 210,
    height: 210,
    borderRadius: 105,
    backgroundColor: "rgba(180, 83, 9, 0.08)",
  },
  slide: {
    flex: 1,
    alignItems: "center",
    justifyContent: "space-between",
  },
  skipButton: {
    alignSelf: "flex-end",
    paddingHorizontal: 6,
    paddingVertical: 10,
  },
  skipText: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 15,
    color: "#6C6255",
  },
  brandPill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 999,
    backgroundColor: "rgba(255, 255, 255, 0.58)",
    borderWidth: 1,
    borderColor: "rgba(22, 101, 52, 0.15)",
    marginTop: 8,
  },
  brandPillText: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 14,
    color: "#1F1A13",
  },
  slideIconShell: {
    width: 108,
    height: 108,
    borderRadius: 36,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(255, 255, 255, 0.62)",
    borderWidth: 1,
    borderColor: "rgba(22, 101, 52, 0.16)",
    shadowColor: "#1F1A13",
    shadowOffset: { width: 0, height: 14 },
    shadowOpacity: 0.08,
    shadowRadius: 24,
    elevation: 3,
  },
  slideTitle: {
    fontFamily: "Poppins_800ExtraBold",
    fontSize: 36,
    lineHeight: 42,
    color: "#1F1A13",
    textAlign: "center",
    marginTop: 12,
    maxWidth: 320,
  },
  slideBody: {
    fontFamily: "Inter_400Regular",
    fontSize: 18,
    lineHeight: 28,
    color: "#6C6255",
    textAlign: "center",
    maxWidth: 324,
    marginTop: 14,
  },
  slideFooter: {
    width: "100%",
    alignItems: "center",
    marginBottom: 8,
  },
  dotsRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    marginBottom: 28,
  },
  dot: {
    height: 10,
    borderRadius: 999,
  },
  dotActive: {
    width: 26,
    backgroundColor: "#166534",
  },
  dotInactive: {
    width: 10,
    backgroundColor: "rgba(22, 101, 52, 0.22)",
  },
  primaryButton: {
    width: "100%",
    height: 58,
    borderRadius: 18,
    backgroundColor: "#166534",
    alignItems: "center",
    justifyContent: "center",
    shadowColor: "#166534",
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.24,
    shadowRadius: 18,
    elevation: 4,
  },
  primaryButtonPressed: {
    opacity: 0.9,
    transform: [{ scale: 0.985 }],
  },
  primaryButtonDisabled: {
    opacity: 0.6,
    shadowOpacity: 0,
  },
  primaryButtonLabel: {
    fontFamily: "Inter_700Bold",
    fontSize: 17,
    color: "#FFFFFF",
    letterSpacing: 0.2,
  },
  permissionBackdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: "rgba(31, 26, 19, 0.26)",
    paddingHorizontal: 24,
    alignItems: "center",
    justifyContent: "center",
  },
  permissionCard: {
    width: "100%",
    borderRadius: 28,
    paddingHorizontal: 24,
    paddingTop: 28,
    paddingBottom: 22,
    backgroundColor: "rgba(255, 252, 244, 0.98)",
    borderWidth: 1,
    borderColor: "rgba(255, 255, 255, 0.75)",
    shadowColor: "#1F1A13",
    shadowOffset: { width: 0, height: 14 },
    shadowOpacity: 0.14,
    shadowRadius: 22,
    elevation: 6,
  },
  permissionIconShell: {
    width: 78,
    height: 78,
    borderRadius: 26,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(22, 101, 52, 0.12)",
    borderWidth: 1,
    borderColor: "rgba(22, 101, 52, 0.18)",
    alignSelf: "center",
    marginBottom: 20,
  },
  permissionTitle: {
    fontFamily: "Poppins_700Bold",
    fontSize: 29,
    lineHeight: 34,
    color: "#1F1A13",
    textAlign: "center",
    marginBottom: 12,
  },
  permissionBody: {
    fontFamily: "Inter_400Regular",
    fontSize: 16,
    lineHeight: 25,
    color: "#6C6255",
    textAlign: "center",
    marginBottom: 24,
  },
  secondaryButton: {
    alignItems: "center",
    justifyContent: "center",
    paddingTop: 16,
    paddingBottom: 4,
  },
  secondaryButtonLabel: {
    fontFamily: "Inter_600SemiBold",
    fontSize: 15,
    color: "#6C6255",
  },
});
