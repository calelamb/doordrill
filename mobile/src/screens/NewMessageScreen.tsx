import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { SafeAreaView, StyleSheet, Text, View, Pressable, TextInput, KeyboardAvoidingView, Platform, ScrollView } from "react-native";
import { LinearGradient } from "expo-linear-gradient";
import { X } from "lucide-react-native";
import { BlurView } from "expo-blur";
import { useState } from "react";

import { colors } from "../theme/tokens";
import { RootStackParamList } from "../navigation/types";
import { useMessages } from "../store/messages";

type Props = NativeStackScreenProps<RootStackParamList, "NewMessage">;

export function NewMessageScreen({ navigation }: Props) {
  const { addThread } = useMessages();
  const [recipient, setRecipient] = useState("");
  const [subject, setSubject] = useState("");
  const [content, setContent] = useState("");

  const canSend = recipient.trim() && subject.trim() && content.trim();

  const handleSend = () => {
    if (!canSend) return;
    addThread({
      manager: recipient.trim(),
      role: "Team Member", // Just a dummy default
      subject: subject.trim(),
    }, content.trim());
    
    navigation.goBack();
  };

  return (
    <LinearGradient colors={["#FDFDFD", "#F7F4EE", "#EBE5D9"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <KeyboardAvoidingView 
          behavior={Platform.OS === "ios" ? "padding" : "height"} 
          style={styles.keyboardView}
        >
          <View style={styles.header}>
            <Pressable onPress={() => navigation.goBack()} style={styles.closeBtn}>
              <X color={colors.ink} size={28} />
            </Pressable>
            <Text style={styles.headerTitle}>New Message</Text>
            <Pressable 
              style={[styles.sendHeaderBtn, !canSend && styles.sendHeaderBtnDisabled]} 
              onPress={handleSend}
              disabled={!canSend}
            >
              <Text style={styles.sendHeaderText}>Send</Text>
            </Pressable>
          </View>

          <ScrollView style={styles.formContainer} keyboardShouldPersistTaps="handled">
            <BlurView intensity={40} tint="light" style={styles.inputGroup}>
              <Text style={styles.label}>To:</Text>
              <TextInput
                style={styles.input}
                placeholder="Manager or Team Member..."
                placeholderTextColor={colors.muted}
                value={recipient}
                onChangeText={setRecipient}
                autoFocus
              />
            </BlurView>
            <View style={styles.divider} />
            
            <BlurView intensity={40} tint="light" style={styles.inputGroup}>
              <Text style={styles.label}>Subject:</Text>
              <TextInput
                style={styles.input}
                placeholder="Brief summary..."
                placeholderTextColor={colors.muted}
                value={subject}
                onChangeText={setSubject}
              />
            </BlurView>
            <View style={styles.divider} />

            <BlurView intensity={40} tint="light" style={[styles.inputGroup, styles.messageGroup]}>
              <TextInput
                style={styles.messageInput}
                placeholder="Write your message here..."
                placeholderTextColor={colors.muted}
                value={content}
                onChangeText={setContent}
                multiline
                textAlignVertical="top"
              />
            </BlurView>
          </ScrollView>
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
    justifyContent: "space-between",
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.line,
    backgroundColor: "rgba(255,255,255,0.4)"
  },
  closeBtn: {
    width: 44,
    height: 44,
    alignItems: "center",
    justifyContent: "center",
  },
  headerTitle: {
    fontFamily: "Poppins_700Bold",
    fontSize: 18,
    color: colors.ink,
  },
  sendHeaderBtn: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    backgroundColor: colors.accent,
    borderRadius: 16,
  },
  sendHeaderBtnDisabled: {
    backgroundColor: "rgba(22, 101, 52, 0.4)",
  },
  sendHeaderText: {
    color: "#fff",
    fontWeight: "700",
    fontSize: 14,
  },
  formContainer: {
    flex: 1,
  },
  inputGroup: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 20,
    minHeight: 56,
  },
  label: {
    fontSize: 15,
    fontWeight: "600",
    color: colors.muted,
    width: 72,
  },
  input: {
    flex: 1,
    fontSize: 16,
    color: colors.ink,
    height: "100%",
  },
  divider: {
    height: 1,
    backgroundColor: colors.line,
  },
  messageGroup: {
    flex: 1,
    paddingVertical: 16,
    alignItems: "flex-start",
  },
  messageInput: {
    flex: 1,
    width: "100%",
    minHeight: 300,
    fontSize: 16,
    color: colors.ink,
    lineHeight: 24,
  }
});