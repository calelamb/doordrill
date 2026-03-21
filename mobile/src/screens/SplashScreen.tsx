import { SafeAreaView, StyleSheet, Text, View } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { TreePine } from "lucide-react-native";

export function SplashScreen() {
  return (
    <LinearGradient colors={["#FCFBF7", "#F3EEE4", "#E6DECF"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.content}>
          <View style={styles.iconShell}>
            <TreePine color="#144227" size={38} strokeWidth={2.5} />
          </View>
          <Text style={styles.title}>DoorDrill</Text>
          <Text style={styles.subtitle}>Sharper reps. Better conversations.</Text>
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
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: 24,
  },
  iconShell: {
    width: 82,
    height: 82,
    borderRadius: 28,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(22, 101, 52, 0.12)",
    borderWidth: 1,
    borderColor: "rgba(22, 101, 52, 0.22)",
    marginBottom: 20,
  },
  title: {
    fontFamily: "Poppins_800ExtraBold",
    fontSize: 34,
    lineHeight: 40,
    color: "#1F1A13",
    marginBottom: 8,
    letterSpacing: 0.4,
  },
  subtitle: {
    fontFamily: "Inter_400Regular",
    fontSize: 15,
    lineHeight: 22,
    color: "#6C6255",
    textAlign: "center",
  },
});
