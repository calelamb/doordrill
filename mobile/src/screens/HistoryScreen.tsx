import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { Pressable, SafeAreaView, StyleSheet, Text, View } from "react-native";

import { colors } from "../theme/tokens";
import { BottomTabParamList, RootStackParamList } from "../navigation/types";
import { BottomTabScreenProps } from "@react-navigation/bottom-tabs";
import { CompositeScreenProps } from "@react-navigation/native";

type Props = CompositeScreenProps<
  BottomTabScreenProps<BottomTabParamList, "HistoryTab">,
  NativeStackScreenProps<RootStackParamList>
>;

export function HistoryScreen({ navigation }: Props) {
  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>
        <Text style={styles.title}>History</Text>
        <Text style={styles.subtitle}>Rep session history view is staged for next iteration.</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: { flex: 1, backgroundColor: colors.bg },
  container: { flex: 1, padding: 20, gap: 8 },
  title: { fontSize: 32, fontFamily: "Poppins_800ExtraBold", color: colors.ink, marginBottom: 4 },
  subtitle: { color: colors.muted, fontSize: 15 },
});
