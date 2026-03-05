import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { SafeAreaView, ScrollView, StyleSheet, Text, View, Pressable } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { MessageSquare, UserCircle, Plus } from "lucide-react-native";
import { BlurView } from "expo-blur";

import { colors } from "../theme/tokens";
import { BottomTabParamList, RootStackParamList } from "../navigation/types";
import { BottomTabScreenProps } from "@react-navigation/bottom-tabs";
import { CompositeScreenProps } from "@react-navigation/native";
import { useMessages } from "../store/messages";

type Props = CompositeScreenProps<
  BottomTabScreenProps<BottomTabParamList, "CommunicationsTab">,
  NativeStackScreenProps<RootStackParamList>
>;

export function CommunicationsScreen({ navigation }: Props) {
  const { threads, markRead } = useMessages();

  const handlePressThread = (threadId: string) => {
    markRead(threadId);
    navigation.navigate("MessageThread", { threadId });
  };

  return (
    <LinearGradient colors={["#FDFDFD", "#F7F4EE", "#EBE5D9"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.content}>
          <View style={styles.headerRow}>
            <View>
              <Text style={styles.title}>Inbox</Text>
              <Text style={styles.subtitle}>Feedback and updates from your team.</Text>
            </View>
            <Pressable 
              style={({ pressed }) => [styles.newBtn, pressed && styles.newBtnPressed]} 
              onPress={() => navigation.navigate("NewMessage")}
            >
              <Plus color="#ffffff" size={24} />
            </Pressable>
          </View>
          
          <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={styles.list}>
            {threads.length === 0 ? (
              <View style={styles.emptyState}>
                <View style={styles.emptyIconContainer}>
                  <MessageSquare size={32} color={colors.accent} />
                </View>
                <Text style={styles.emptyText}>No messages yet.</Text>
                <Text style={styles.emptySubtext}>Your inbox is clear. Tap the plus button to start a conversation.</Text>
              </View>
            ) : (
              threads.map((thread) => {
                const lastMessage = thread.messages[thread.messages.length - 1];
                
                return (
                  <Pressable 
                    key={thread.id} 
                    style={({ pressed }) => [styles.cardWrapper, pressed && styles.cardPressed]}
                    onPress={() => handlePressThread(thread.id)}
                  >
                    <BlurView intensity={40} tint="light" style={styles.card}>
                      <View style={styles.cardHeader}>
                        <View style={styles.authorInfo}>
                          <UserCircle size={36} color={colors.accent} strokeWidth={1.5} />
                          <View>
                            <Text style={styles.authorName}>{thread.manager}</Text>
                            <Text style={styles.authorRole}>{thread.role}</Text>
                          </View>
                        </View>
                        <View style={styles.metaInfo}>
                          {thread.isNew && (
                            <View style={styles.newBadge}>
                              <Text style={styles.newBadgeText}>NEW</Text>
                            </View>
                          )}
                          <Text style={styles.dateText}>{lastMessage?.date}</Text>
                        </View>
                      </View>
                      
                      <View style={styles.divider} />
                      <Text style={styles.subjectText}>{thread.subject}</Text>
                      <Text style={styles.messageContent} numberOfLines={2}>{lastMessage?.content}</Text>
                    </BlurView>
                  </Pressable>
                );
              })
            )}
          </ScrollView>
        </View>
      </SafeAreaView>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  safeArea: { flex: 1 },
  content: { flex: 1, padding: 20, paddingBottom: 0, gap: 16 },
  headerRow: { 
    marginBottom: 8, 
    marginTop: 10,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center"
  },
  title: { fontSize: 32, fontFamily: "Poppins_800ExtraBold", color: colors.ink, marginBottom: 4 },
  subtitle: { color: colors.muted, fontSize: 16 },
  newBtn: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
    shadowColor: colors.accent,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.3,
    shadowRadius: 8,
    elevation: 4,
  },
  newBtnPressed: {
    opacity: 0.8,
    transform: [{ scale: 0.96 }]
  },
  list: { gap: 16, paddingBottom: 40 },
  emptyState: { flex: 1, alignItems: "center", justifyContent: "center", marginTop: 80, gap: 12 },
  emptyIconContainer: {
    width: 64,
    height: 64,
    borderRadius: 32,
    backgroundColor: colors.accentSoft,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 8,
    borderWidth: 1,
    borderColor: "rgba(22, 101, 52, 0.2)"
  },
  emptyText: { fontSize: 20, fontFamily: "Poppins_700Bold", color: colors.ink },
  emptySubtext: { fontSize: 15, color: colors.muted, textAlign: "center", paddingHorizontal: 20 },
  cardWrapper: {
    borderRadius: 24,
    overflow: "hidden",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    backgroundColor: "rgba(255, 255, 255, 0.6)",
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.04,
    shadowRadius: 16,
    elevation: 3,
  },
  cardPressed: {
    opacity: 0.85,
    transform: [{ scale: 0.98 }]
  },
  card: {
    padding: 18,
  },
  cardHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
  },
  authorInfo: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
  },
  authorName: {
    color: colors.ink,
    fontSize: 16,
    fontFamily: "Poppins_700Bold",
  },
  authorRole: {
    color: colors.muted,
    fontSize: 13,
  },
  metaInfo: {
    alignItems: "flex-end",
    gap: 6,
  },
  newBadge: {
    backgroundColor: "rgba(22, 101, 52, 0.12)",
    borderWidth: 1,
    borderColor: "rgba(22, 101, 52, 0.3)",
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 999,
  },
  newBadgeText: {
    color: "#15803d",
    fontSize: 10,
    fontWeight: "800",
    letterSpacing: 0.5,
  },
  dateText: {
    color: colors.muted,
    fontSize: 12,
  },
  divider: {
    height: 1,
    backgroundColor: colors.line,
    marginVertical: 14,
  },
  subjectText: {
    color: colors.ink,
    fontSize: 15,
    fontFamily: "Poppins_700Bold",
    marginBottom: 4,
  },
  messageContent: {
    color: colors.muted,
    fontSize: 14,
    lineHeight: 22,
  }
});