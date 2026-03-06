import { StyleSheet, View } from "react-native";
import { colors } from "../theme/tokens";

export function BackgroundBlobs() {
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="none">
      <View style={[styles.blob, styles.blob1]} />
      <View style={[styles.blob, styles.blob2]} />
      <View style={[styles.blob, styles.blob3]} />
    </View>
  );
}

const styles = StyleSheet.create({
  blob: {
    position: "absolute",
    borderRadius: 999,
    opacity: 0.4,
  },
  blob1: {
    width: 300,
    height: 300,
    backgroundColor: "rgba(22, 163, 74, 0.15)", // soft green
    top: -100,
    right: -100,
  },
  blob2: {
    width: 400,
    height: 400,
    backgroundColor: "rgba(217, 119, 6, 0.08)", // soft warm orange/amber
    bottom: 100,
    left: -150,
  },
  blob3: {
    width: 250,
    height: 250,
    backgroundColor: "rgba(22, 163, 74, 0.1)", // softer green
    bottom: -50,
    right: 50,
  },
});
