import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { SafeAreaView, ScrollView, StyleSheet, Text, View, Pressable, TextInput, KeyboardAvoidingView, Platform } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { ChevronLeft, Send } from "lucide-react-native";
import { BlurView } from "expo-blur";
import { useState } from "react";

import { colors } from "../theme/tokens";
import { RootStackParamList } from "../navigation/types";
import { useMessages } from "../store/messages";

type Props = NativeStackScreenProps<RootStackParamList, "MessageThread">;

export function MessageThreadScreen({ route, navigation }: Props) {
  const { threadId } = route.params;
  const { threads, addMessage } = useMessages();
  const [replyText, setReplyText] = useState("");

  const thread = threads.find((t) => t.id === threadId);

  if (!thread) {
    return (
      <View style={styles.container}>
        <Text>Thread not found</Text>
      </View>
    );
  }

  const handleSend = () => {
    if (!replyText.trim()) return;
    addMessage(threadId, replyText.trim());
    setReplyText("");
  };

  return (
    <LinearGradient colors={["#FDFDFD", "#F7F4EE", "#EBE5D9"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <KeyboardAvoidingView 
          behavior={Platform.OS === "ios" ? "padding" : "height"} 
          style={styles.keyboardView}
        >
          <View style={styles.header}>
            <Pressable onPress={() => navigation.goBack()} style={styles.backBtn}>
              <ChevronLeft color={colors.ink} size={28} />
            </Pressable>
            <View style={styles.headerInfo}>
              <Text style={styles.headerName}>{thread.manager}</Text>
              <Text style={styles.headerSubject}>{thread.subject}</Text>
            </View>
            <View style={styles.placeholder} />
          </View>

          <ScrollView showsVerticalScrollIndicator={false} contentContainerStyle={styles.list}>
            {thread.messages.map((msg) => (
              <View 
                key={msg.id} 
                style={[
                  styles.messageBubbleWrapper, 
                  msg.isMe ? styles.messageBubbleMe : styles.messageBubbleThem
                ]}
              >
                {!msg.isMe && <Text style={styles.senderLabel}>{msg.sender}</Text>}
                <BlurView 
                  intensity={40} 
                  tint="light" 
                  style={[
                    styles.messageBubble,
                    msg.isMe ? styles.bubbleMe : styles.bubbleThem
                  ]}
                >
                  <Text style={[styles.messageText, msg.isMe && styles.messageTextMe]}>{msg.content}</Text>
                  <Text style={[styles.messageDate, msg.isMe && styles.messageDateMe]}>{msg.date}</Text>
                </BlurView>
              </View>
            ))}
          </ScrollView>

          <View style={styles.inputContainer}>
            <BlurView intensity={60} tint="light" style={styles.inputBlur}>
              <TextInput
                style={styles.input}
                placeholder="Type your reply..."
                placeholderTextColor={colors.muted}
                value={replyText}
                onChangeText={setReplyText}
                multiline
                maxLength={500}
              />
              <Pressable 
                style={({ pressed }) => [
                  styles.sendBtn, 
                  !replyText.trim() && styles.sendBtnDisabled,
                  pressed && !!replyText.trim() && styles.sendBtnPressed
                ]}
                disabled={!replyText.trim()}
                onPress={handleSend}
              >
                <Send size={18} color="#fff" style={{ marginLeft: 2 }} />
              </Pressable>
            </BlurView>
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  safeArea: { flex: 1 },
  keyboardView: { flex: 1 },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.line,
  },
  backBtn: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
    borderRadius: 22,
    backgroundColor: "rgba(0,0,0,0.04)"
  },
  headerInfo: {
    flex: 1,
    alignItems: "center",
  },
  headerName: {
    fontFamily: "Poppins_700Bold",
    fontSize: 16,
    color: colors.ink,
  },
  headerSubject: {
    fontSize: 13,
    color: colors.muted,
  },
  placeholder: { width: 44 },
  list: {
    padding: 20,
    gap: 16,
  },
  messageBubbleWrapper: {
    maxWidth: "85%",
  },
  messageBubbleMe: {
    alignSelf: "flex-end",
  },
  messageBubbleThem: {
    alignSelf: "flex-start",
  },
  senderLabel: {
    fontSize: 12,
    color: colors.muted,
    marginBottom: 4,
    marginLeft: 4,
    fontWeight: "600",
  },
  messageBubble: {
    padding: 16,
    borderRadius: 20,
    overflow: "hidden",
    borderWidth: 1,
  },
  bubbleMe: {
    backgroundColor: colors.accent,
    borderColor: "rgba(0,0,0,0.1)",
    borderBottomRightRadius: 4,
  },
  bubbleThem: {
    backgroundColor: "rgba(255,255,255,0.7)",
    borderColor: colors.line,
    borderBottomLeftRadius: 4,
  },
  messageText: {
    fontSize: 15,
    lineHeight: 22,
    color: colors.ink,
  },
  messageTextMe: {
    color: "#ffffff",
  },
  messageDate: {
    fontSize: 11,
    color: colors.muted,
    alignSelf: "flex-end",
    marginTop: 8,
  },
  messageDateMe: {
    color: "rgba(255,255,255,0.7)",
  },
  inputContainer: {
    paddingHorizontal: 20,
    paddingVertical: 12,
    paddingBottom: 24,
  },
  inputBlur: {
    flexDirection: "row",
    alignItems: "flex-end",
    borderRadius: 24,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: "rgba(255, 255, 255, 0.6)",
    paddingHorizontal: 16,
    paddingVertical: 12,
    overflow: "hidden",
  },
  input: {
    flex: 1,
    minHeight: 40,
    maxHeight: 120,
    color: colors.ink,
    fontSize: 15,
    paddingTop: 8,
    paddingBottom: 8,
  },
  sendBtn: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.accent,
    alignItems: "center",
    justifyContent: "center",
    marginLeft: 12,
  },
  sendBtnDisabled: {
    backgroundColor: "rgba(22, 163, 74, 0.4)",
  },
  sendBtnPressed: {
    opacity: 0.8,
    transform: [{ scale: 0.95 }]
  }
});