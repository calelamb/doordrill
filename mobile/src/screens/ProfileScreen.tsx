import { NativeStackScreenProps } from "@react-navigation/native-stack";
import { useCallback, useEffect, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Switch,
  Text,
  TextInput,
  View,
  Image,
  ScrollView,
} from "react-native";
import {
  Award,
  BellRing,
  Camera,
  Check,
  ChevronDown,
  ChevronUp,
  Edit2,
  Flame,
  LogOut,
  Star,
  Target,
  TrendingUp,
  X,
} from "lucide-react-native";
import { LinearGradient } from "expo-linear-gradient";
import { BlurView } from "expo-blur";
import * as ImagePicker from "expo-image-picker";

import { BottomTabParamList, RootStackParamList } from "../navigation/types";
import {
  fetchNotificationPreferences,
  fetchRepHierarchy,
  fetchRepProgress,
  revokeDeviceToken,
  updateNotificationPreferences,
  updateRepProfile,
  uploadRepAvatar,
} from "../services/api";
import { API_BASE_URL } from "../services/config";
import { clearStoredPushToken, getStoredPushToken } from "../services/notifications";
import { useSession } from "../store/session";
import { colors } from "../theme/tokens";
import { DEFAULT_NOTIFICATION_PREFERENCES, HierarchyNode, NotificationPreferences, RepProgress } from "../types";
import { BottomTabScreenProps } from "@react-navigation/bottom-tabs";
import { CompositeScreenProps } from "@react-navigation/native";

type Props = CompositeScreenProps<
  BottomTabScreenProps<BottomTabParamList, "ProfileTab">,
  NativeStackScreenProps<RootStackParamList>
>;

const CATEGORY_LABELS: Record<string, string> = {
  opening: "Opening",
  pitch_delivery: "Pitch",
  objection_handling: "Objection Handling",
  closing_technique: "Closing",
  professionalism: "Professionalism",
};

const NOTIFICATION_PREFERENCE_ITEMS: Array<{
  key: keyof NotificationPreferences;
  label: string;
  description: string;
}> = [
  { key: "score_ready", label: "Score Ready", description: "When your latest drill is graded." },
  { key: "assignment_created", label: "New Assignment", description: "When a manager assigns you a drill." },
  { key: "assignment_due_soon", label: "Due Reminders", description: "Twenty-four hours before a deadline." },
  { key: "coaching_note", label: "Coaching Notes", description: "When a manager posts visible feedback." },
  { key: "streak_nudge", label: "Practice Reminders", description: "When you have been inactive for multiple days." },
];

export function ProfileScreen({ navigation }: Props) {
  const { repId, clearSession } = useSession();
  const [progress, setProgress] = useState<RepProgress | null>(null);
  const [hierarchy, setHierarchy] = useState<HierarchyNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [isEditing, setIsEditing] = useState(false);
  const [editName, setEditName] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const [prefs, setPrefs] = useState<NotificationPreferences>({ ...DEFAULT_NOTIFICATION_PREFERENCES });
  const [prefsLoading, setPrefsLoading] = useState(false);
  const [prefsSaving, setPrefsSaving] = useState(false);
  const [prefsError, setPrefsError] = useState<string | null>(null);
  const [notificationsExpanded, setNotificationsExpanded] = useState(true);
  const [loggingOut, setLoggingOut] = useState(false);

  const loadProgress = useCallback(async () => {
    if (!repId) return;
    setLoading(true);
    setError(null);
    try {
      const [progressData, hierarchyData] = await Promise.all([
        fetchRepProgress(repId),
        fetchRepHierarchy()
      ]);
      setProgress(progressData);
      setHierarchy(hierarchyData);
      setEditName(progressData.rep_name || "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load profile");
    } finally {
      setLoading(false);
    }
  }, [repId]);

  useEffect(() => {
    void loadProgress();
  }, [loadProgress]);

  const loadPreferences = useCallback(async () => {
    if (!repId) {
      return;
    }
    setPrefsLoading(true);
    setPrefsError(null);
    try {
      const savedPrefs = await fetchNotificationPreferences();
      setPrefs(savedPrefs);
    } catch (err) {
      setPrefsError(err instanceof Error ? err.message : "Failed to load notification preferences");
      setPrefs({ ...DEFAULT_NOTIFICATION_PREFERENCES });
    } finally {
      setPrefsLoading(false);
    }
  }, [repId]);

  useEffect(() => {
    void loadPreferences();
  }, [loadPreferences]);

  const handleSaveProfile = async () => {
    if (!repId) return;
    setSavingProfile(true);
    try {
      await updateRepProfile(editName);
      await loadProgress(); // reload data
      setIsEditing(false);
    } catch (err) {
      alert("Failed to save profile");
    } finally {
      setSavingProfile(false);
    }
  };

  const pickImage = async () => {
    if (!repId || !isEditing) return;
    try {
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images, // Corrected from ['images']
        allowsEditing: true,
        aspect: [1, 1],
        quality: 0.5,
      });

      if (!result.canceled && result.assets && result.assets.length > 0) {
        setUploadingAvatar(true);
        await uploadRepAvatar(result.assets[0].uri);
        await loadProgress(); // reload data to get new avatar URL
      }
    } catch (err) {
      alert("Failed to upload image");
    } finally {
      setUploadingAvatar(false);
    }
  };

  const togglePref = async (key: keyof NotificationPreferences) => {
    if (!repId || prefsSaving) {
      return;
    }

    const previousPrefs = prefs;
    const updatedPrefs = { ...previousPrefs, [key]: !previousPrefs[key] };
    setPrefs(updatedPrefs);
    setPrefsSaving(true);
    setPrefsError(null);
    try {
      const savedPrefs = await updateNotificationPreferences(updatedPrefs);
      setPrefs(savedPrefs);
    } catch (err) {
      setPrefs(previousPrefs);
      setPrefsError(err instanceof Error ? err.message : "Failed to update notification preferences");
    } finally {
      setPrefsSaving(false);
    }
  };

  const handleLogout = async () => {
    if (!repId || loggingOut) {
      await clearSession();
      return;
    }

    setLoggingOut(true);
    try {
      const tokenId = await getStoredPushToken();
      if (tokenId) {
        await revokeDeviceToken(tokenId);
      }
    } catch {
      // Best-effort cleanup; logout should not be blocked on network state.
    } finally {
      await clearStoredPushToken().catch(() => undefined);
      await clearSession();
    }
  };

  const displayName = progress?.rep_name || "Sales Representative";
  const initials = progress?.rep_name 
    ? progress.rep_name.split(" ").map(n => n[0]).join("").substring(0, 2).toUpperCase()
    : "SR";
  const displayRole = progress?.rep_email || "rep@doordrill.com";
  const avatarUrl = progress?.rep_avatar_url ? `${API_BASE_URL}${progress.rep_avatar_url}` : null;
  const mostImprovedLabel = progress?.most_improved_category
    ? CATEGORY_LABELS[progress.most_improved_category] ?? progress.most_improved_category.replace(/_/g, " ")
    : "—";

  return (
    <LinearGradient colors={["#FBF9F5", "#EFEEEA", "#E4E2DE"]} style={styles.container}>
      <SafeAreaView style={styles.safeArea}>
        <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
          <BlurView intensity={40} tint="light" style={styles.profileCard}>
            {!isEditing && (
              <Pressable
                style={styles.editButton}
                onPress={() => setIsEditing(true)}
                accessibilityLabel="Edit profile"
              >
                <Edit2 size={18} color={colors.muted} />
              </Pressable>
            )}
            
            <Pressable
              onPress={pickImage}
              disabled={!isEditing}
              style={[styles.avatar, isEditing && styles.avatarEditing]}
              accessibilityLabel="Update profile picture"
            >
              {uploadingAvatar ? (
                <ActivityIndicator color={colors.accent} />
              ) : avatarUrl ? (
                <Image source={{ uri: avatarUrl }} style={styles.avatarImage} />
              ) : (
                <Text style={styles.avatarText}>{initials}</Text>
              )}
              {isEditing && !uploadingAvatar && (
                <View style={styles.avatarEditOverlay}>
                  <Camera size={20} color="#fff" />
                </View>
              )}
            </Pressable>
            
            {isEditing ? (
              <View style={styles.editForm}>
                <TextInput
                  style={styles.nameInput}
                  value={editName}
                  onChangeText={setEditName}
                  placeholder="Your Name"
                  placeholderTextColor={colors.muted}
                />
                <View style={styles.editActions}>
                  <Pressable 
                    style={[styles.actionBtn, styles.cancelBtn]} 
                    onPress={() => { setIsEditing(false); setEditName(progress?.rep_name || ""); }}
                    accessibilityLabel="Cancel profile editing"
                  >
                    <X size={16} color="#6b7280" />
                  </Pressable>
                  <Pressable
                    style={[styles.actionBtn, styles.saveBtn]}
                    onPress={handleSaveProfile}
                    disabled={savingProfile}
                    accessibilityLabel="Save profile"
                  >
                    {savingProfile ? <ActivityIndicator size="small" color="#fff" /> : <Check size={16} color="#fff" />}
                  </Pressable>
                </View>
              </View>
            ) : (
              <>
                <Text style={styles.name}>{displayName}</Text>
                <Text style={styles.role}>{displayRole}</Text>
              </>
            )}
          </BlurView>

          {progress ? (
            <ScrollView
              horizontal
              showsHorizontalScrollIndicator={false}
              contentContainerStyle={styles.profileStatsRow}
            >
              <BlurView intensity={40} tint="light" style={styles.profileStatChip}>
                <Star size={16} color={colors.warning} />
                <Text style={styles.profileStatText}>
                  {`Best Score: ${progress.personal_best !== null && progress.personal_best !== undefined ? progress.personal_best.toFixed(1) : "—"}`}
                </Text>
              </BlurView>

              <BlurView intensity={40} tint="light" style={styles.profileStatChip}>
                <Flame size={16} color={colors.warning} />
                <Text style={styles.profileStatText}>{`${progress.streak_days ?? 0}-day streak`}</Text>
              </BlurView>

              <BlurView intensity={40} tint="light" style={styles.profileStatChip}>
                <TrendingUp size={16} color={colors.accent} />
                <Text style={styles.profileStatText}>{`Most Improved: ${mostImprovedLabel}`}</Text>
              </BlurView>
            </ScrollView>
          ) : null}

          {loading && !progress ? (
            <ActivityIndicator size="large" color={colors.accent} style={{ marginTop: 40 }} />
          ) : error ? (
            <View style={styles.errorContainer}>
              <Text style={styles.error}>{error}</Text>
              <Pressable onPress={loadProgress}>
                <Text style={styles.retryText}>Retry</Text>
              </Pressable>
            </View>
          ) : progress ? (
            <>
              <View style={styles.statsContainer}>
                <Text style={styles.sectionTitle}>Your Progress</Text>
                
                <View style={styles.statGrid}>
                  <View style={styles.statCardWrapper}>
                    <BlurView intensity={40} tint="light" style={styles.statCard}>
                      <View style={styles.statHeader}>
                        <Target size={18} color={colors.muted} />
                        <Text style={styles.statLabel}>Total Drills</Text>
                      </View>
                      <Text style={styles.statValue}>{progress.session_count}</Text>
                    </BlurView>
                  </View>

                  <View style={styles.statCardWrapper}>
                    <BlurView intensity={40} tint="light" style={styles.statCard}>
                      <View style={styles.statHeader}>
                        <Award size={18} color={colors.accent} />
                        <Text style={styles.statLabel}>Avg Score</Text>
                      </View>
                      <Text style={[styles.statValue, { color: colors.accent }]}>
                        {progress.average_score !== null ? progress.average_score.toFixed(1) : "--"}
                      </Text>
                    </BlurView>
                  </View>
                </View>
              </View>

              {hierarchy && hierarchy.length > 0 && (
                <View style={styles.hierarchyContainer}>
                  <Text style={styles.sectionTitle}>Reporting Structure</Text>
                  <View style={styles.hierarchyWrapper}>
                    {hierarchy.map((node, index) => {
                      const isLast = index === hierarchy.length - 1;
                      const isMe = node.id === repId;
                      const nodeInitials = node.name.split(" ").map(n => n[0]).join("").substring(0, 2).toUpperCase();
                      const nodeAvatar = node.avatar_url ? `${API_BASE_URL}${node.avatar_url}` : null;
                      
                      return (
                        <View key={node.id} style={styles.hierarchyRow}>
                          <View style={styles.hierarchyLineContainer}>
                            <View style={[styles.hierarchyAvatar, isMe && styles.hierarchyAvatarMe]}>
                              {nodeAvatar ? (
                                <Image source={{ uri: nodeAvatar }} style={styles.hierarchyAvatarImage} />
                              ) : (
                                <Text style={[styles.hierarchyAvatarText, isMe && styles.hierarchyAvatarTextMe]}>{nodeInitials}</Text>
                              )}
                            </View>
                            {!isLast && <View style={styles.hierarchyLine} />}
                          </View>
                          <View style={[styles.hierarchyDetails, isMe && styles.hierarchyDetailsMe]}>
                            <Text style={[styles.hierarchyName, isMe && styles.hierarchyNameMe]}>
                              {node.name} {isMe ? "(You)" : ""}
                            </Text>
                            <Text style={styles.hierarchyRole}>
                              {node.role.charAt(0).toUpperCase() + node.role.slice(1)}
                            </Text>
                          </View>
                        </View>
                      );
                    })}
                  </View>
                </View>
              )}

              <BlurView intensity={40} tint="light" style={styles.preferencesCard}>
                <Pressable
                  style={styles.preferencesHeader}
                  onPress={() => setNotificationsExpanded((current) => !current)}
                  accessibilityLabel="Toggle notification preferences"
                >
                  <View style={styles.preferencesHeaderCopy}>
                    <View style={styles.preferencesIconWrap}>
                      <BellRing size={18} color={colors.accent} />
                    </View>
                    <View style={styles.preferencesHeaderText}>
                      <Text style={styles.sectionTitle}>Notifications</Text>
                      <Text style={styles.preferencesSubtitle}>Choose which reminders and coaching alerts you receive.</Text>
                    </View>
                  </View>
                  {notificationsExpanded ? (
                    <ChevronUp size={18} color={colors.muted} />
                  ) : (
                    <ChevronDown size={18} color={colors.muted} />
                  )}
                </Pressable>

                {notificationsExpanded ? (
                  <View style={styles.preferencesBody}>
                    {prefsLoading ? (
                      <ActivityIndicator color={colors.accent} style={styles.preferencesLoading} />
                    ) : (
                      <>
                        {prefsError ? (
                          <View style={styles.preferenceErrorRow}>
                            <Text style={styles.preferenceErrorText}>{prefsError}</Text>
                            <Pressable onPress={loadPreferences} accessibilityLabel="Retry loading notification preferences">
                              <Text style={styles.preferenceRetryText}>Retry</Text>
                            </Pressable>
                          </View>
                        ) : null}

                        {NOTIFICATION_PREFERENCE_ITEMS.map(({ key, label, description }, index) => (
                          <View
                            key={key}
                            style={[
                              styles.preferenceRow,
                              index < NOTIFICATION_PREFERENCE_ITEMS.length - 1 && styles.preferenceRowBorder,
                            ]}
                          >
                            <View style={styles.preferenceTextGroup}>
                              <Text style={styles.preferenceLabel}>{label}</Text>
                              <Text style={styles.preferenceDescription}>{description}</Text>
                            </View>
                            <Switch
                              value={prefs[key]}
                              onValueChange={() => {
                                void togglePref(key);
                              }}
                              disabled={prefsLoading || prefsSaving || loggingOut}
                              trackColor={{ false: colors.line, true: colors.accent }}
                              thumbColor="#FFFFFF"
                              ios_backgroundColor={colors.line}
                              accessibilityLabel={`Toggle ${label} notifications`}
                            />
                          </View>
                        ))}

                        {prefsSaving ? <Text style={styles.preferenceSavingText}>Saving changes…</Text> : null}
                      </>
                    )}
                  </View>
                ) : null}
              </BlurView>
            </>
          ) : null}

          <View style={styles.actionsContainer}>
            <Pressable
              style={({pressed}) => [styles.logoutButton, pressed && styles.logoutButtonPressed, loggingOut && styles.logoutButtonDisabled]}
              onPress={() => {
                void handleLogout();
              }}
              disabled={loggingOut}
              accessibilityLabel="Sign out"
            >
              {loggingOut ? <ActivityIndicator color="#991B1B" /> : <LogOut size={18} color="#991B1B" />}
              <Text style={styles.logoutText}>{loggingOut ? "Signing Out…" : "Sign Out"}</Text>
            </Pressable>
          </View>
        </ScrollView>
      </SafeAreaView>
    </LinearGradient>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  safeArea: { flex: 1 },
  content: { flexGrow: 1, padding: 20, paddingBottom: 32 },
  profileCard: { 
    alignItems: "center", 
    marginTop: 12, 
    marginBottom: 32,
    padding: 32,
    borderRadius: 32,
    backgroundColor: "rgba(255, 255, 255, 0.6)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    shadowColor: "#000",
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.04,
    shadowRadius: 24,
    elevation: 4,
    overflow: "hidden"
  },
  avatar: {
    width: 100,
    height: 100,
    borderRadius: 50,
    backgroundColor: "rgba(22, 101, 52, 0.1)",
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 16,
    borderWidth: 2,
    borderColor: "rgba(22, 101, 52, 0.3)",
    shadowColor: colors.accent,
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.15,
    shadowRadius: 16,
    elevation: 8,
  },
  avatarText: { fontSize: 36, fontWeight: "800", color: colors.accent },
  name: { fontSize: 26, fontFamily: "Poppins_800ExtraBold", color: colors.ink, marginBottom: 6 },
  role: { fontSize: 15, color: colors.muted },
  profileStatsRow: {
    gap: 10,
    paddingRight: 20,
    marginBottom: 24,
  },
  profileStatChip: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    paddingHorizontal: 14,
    paddingVertical: 12,
    borderRadius: 18,
    backgroundColor: "rgba(255, 255, 255, 0.6)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    overflow: "hidden",
  },
  profileStatText: {
    fontSize: 13,
    color: colors.ink,
    fontFamily: "Poppins_600SemiBold",
  },
  preferencesCard: {
    marginTop: 32,
    width: "100%",
    borderRadius: 28,
    backgroundColor: "rgba(255, 255, 255, 0.6)",
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.line,
    overflow: "hidden",
  },
  preferencesHeader: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
    paddingHorizontal: 20,
    paddingVertical: 18,
  },
  preferencesHeaderCopy: {
    flex: 1,
    flexDirection: "row",
    alignItems: "center",
    gap: 14,
  },
  preferencesIconWrap: {
    width: 38,
    height: 38,
    borderRadius: 19,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "rgba(22, 101, 52, 0.1)",
  },
  preferencesHeaderText: { flex: 1 },
  preferencesSubtitle: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.muted,
    marginTop: -6,
  },
  preferencesBody: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.line,
    paddingHorizontal: 20,
    paddingVertical: 8,
  },
  preferencesLoading: {
    paddingVertical: 18,
  },
  preferenceRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 16,
    paddingVertical: 14,
  },
  preferenceRowBorder: {
    borderBottomWidth: StyleSheet.hairlineWidth,
    borderBottomColor: colors.line,
  },
  preferenceTextGroup: {
    flex: 1,
    paddingRight: 8,
  },
  preferenceLabel: {
    fontSize: 15,
    fontFamily: "Poppins_600SemiBold",
    color: colors.ink,
    marginBottom: 4,
  },
  preferenceDescription: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.muted,
  },
  preferenceErrorRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
    paddingVertical: 12,
  },
  preferenceErrorText: {
    flex: 1,
    color: "#991B1B",
    fontWeight: "600",
  },
  preferenceRetryText: {
    color: "#991B1B",
    fontWeight: "800",
  },
  preferenceSavingText: {
    paddingTop: 12,
    fontSize: 12,
    color: colors.muted,
    textAlign: "right",
  },
  errorContainer: {
    backgroundColor: "#FEE2E2",
    borderWidth: 1,
    borderColor: "#FECACA",
    padding: 16,
    borderRadius: 14,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    marginTop: 20,
  },
  error: { color: "#991B1B", fontWeight: "600", flex: 1 },
  retryText: { color: "#991B1B", fontWeight: "800", textDecorationLine: "underline" },
  statsContainer: { width: "100%" },
  sectionTitle: { fontSize: 18, fontFamily: "Poppins_700Bold", color: colors.ink, marginBottom: 16 },
  statGrid: { flexDirection: "row", flexWrap: "wrap", gap: 12 },
  statCardWrapper: {
    flex: 1,
    minWidth: "45%",
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
  statCard: {
    padding: 18,
  },
  statHeader: { flexDirection: "row", alignItems: "center", gap: 8, marginBottom: 12 },
  statLabel: { fontSize: 12, fontWeight: "700", color: colors.muted, textTransform: "uppercase", letterSpacing: 0.5 },
  statValue: { fontSize: 36, fontWeight: "800", color: colors.ink },
  actionsContainer: { marginTop: "auto", gap: 12, paddingTop: 24, paddingBottom: 20 },
  logoutButton: {
    flexDirection: "row",
    gap: 8,
    paddingVertical: 16,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#FEE2E2",
    borderWidth: 1,
    borderColor: "#FECACA",
    borderRadius: 16,
  },
  logoutButtonPressed: {
    opacity: 0.7,
  },
  logoutButtonDisabled: {
    opacity: 0.8,
  },
  logoutText: { fontSize: 16, fontWeight: "700", color: "#991B1B" },
  editButton: { position: "absolute", top: 20, right: 20, padding: 8 },
  avatarEditing: { borderWidth: 2, borderColor: colors.accent, borderStyle: "dashed" },
  avatarImage: { width: "100%", height: "100%", borderRadius: 50 },
  avatarEditOverlay: {
    position: "absolute",
    bottom: 0,
    right: 0,
    backgroundColor: colors.accent,
    width: 32,
    height: 32,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 3,
    borderColor: "#fff"
  },
  editForm: { width: "100%", alignItems: "center", marginTop: 8 },
  nameInput: {
    width: "80%",
    fontSize: 22,
    fontFamily: "Poppins_800ExtraBold",
    color: colors.ink,
    textAlign: "center",
    borderBottomWidth: 2,
    borderBottomColor: colors.accent,
    paddingVertical: 4,
    marginBottom: 16
  },
  editActions: { flexDirection: "row", gap: 12 },
  actionBtn: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  saveBtn: { backgroundColor: colors.accent },
  cancelBtn: { backgroundColor: "rgba(0,0,0,0.05)", borderWidth: 1, borderColor: "rgba(0,0,0,0.1)" },
  hierarchyContainer: { marginTop: 32, width: "100%" },
  hierarchyWrapper: {
    paddingLeft: 16,
    paddingTop: 8,
  },
  hierarchyRow: {
    flexDirection: "row",
    minHeight: 70,
  },
  hierarchyLineContainer: {
    width: 40,
    alignItems: "center",
  },
  hierarchyAvatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: "rgba(22, 101, 52, 0.1)",
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 1,
    borderColor: "rgba(22, 101, 52, 0.3)",
    zIndex: 2,
  },
  hierarchyAvatarMe: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
    width: 48,
    height: 48,
    borderRadius: 24,
    marginLeft: -4,
  },
  hierarchyAvatarImage: { width: "100%", height: "100%", borderRadius: 24 },
  hierarchyAvatarText: { fontSize: 14, fontWeight: "800", color: colors.accent },
  hierarchyAvatarTextMe: { color: "#fff", fontSize: 16 },
  hierarchyLine: {
    width: 2,
    flex: 1,
    backgroundColor: "rgba(22, 101, 52, 0.2)",
    marginTop: -4,
    marginBottom: -4,
    zIndex: 1,
  },
  hierarchyDetails: {
    flex: 1,
    paddingLeft: 16,
    paddingTop: 4,
    paddingBottom: 24,
  },
  hierarchyDetailsMe: {
    paddingTop: 8,
  },
  hierarchyName: {
    fontSize: 16,
    fontWeight: "600",
    color: colors.ink,
    marginBottom: 2,
  },
  hierarchyNameMe: {
    fontFamily: "Poppins_700Bold",
    fontSize: 18,
    color: colors.accent,
  },
  hierarchyRole: {
    fontSize: 13,
    color: colors.muted,
  }
});
