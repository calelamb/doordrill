export type RepAssignment = {
  id: string;
  scenario_id: string;
  rep_id: string;
  assigned_by: string;
  due_at: string | null;
  status: string;
  min_score_target: number | null;
  retry_policy: Record<string, unknown>;
};

export type ScenarioBrief = {
  id: string;
  org_id: string | null;
  name: string;
  industry: string;
  difficulty: number;
  description: string;
  persona: Record<string, unknown>;
  rubric: Record<string, unknown>;
  stages: string[];
  created_by_id: string | null;
};

export type CategoryScoreDetail = {
  score: number | null;
  rationale_summary?: string;
  rationale_detail?: string;
  improvement_target?: string | null;
  behavioral_signals?: string[];
  evidence_turn_ids?: string[];
  confidence?: number;
};

export type TechniqueCheck = {
  id: string;
  label: string;
  category: string;
  status: string;
  kind: string;
  evidence_turn_ids: string[];
};

export type GradingMeta = {
  status: string;
  source?: string | null;
  provisional: boolean;
  confidence?: number | null;
  evidence_quality?: string | null;
  session_complexity?: number | null;
  call_quality?: string | null;
  message?: string | null;
};

export type ImprovementTarget = {
  category: string;
  label: string;
  target: string;
  score: number;
};

export type TranscriptTurn = {
  turn_index: number;
  rep_text: string;
  ai_text: string;
  turn_id: string;
  objection_tags: string[];
  emotion?: string | null;
  stage?: string | null;
};

export type Scorecard = {
  id: string;
  overall_score: number | null;
  scorecard_schema_version: string;
  category_scores: Record<string, CategoryScoreDetail>;
  improvement_targets: ImprovementTarget[];
  highlights: Array<{
    type: string;
    note: string;
    turn_id?: string | null;
    quote?: string | null;
    transcript_quote?: string | null;
  }>;
  ai_summary: string;
  evidence_turn_ids: string[];
  weakness_tags: string[];
  technique_checks: TechniqueCheck[];
};

export type RepSessionDetail = {
  session: {
    id: string;
    assignment_id: string;
    rep_id: string;
    scenario_id: string;
    started_at: string;
    ended_at: string | null;
    status: string;
  };
  scorecard: Scorecard | null;
  grading_meta?: GradingMeta | null;
  manager_review?: {
    notes?: string | null;
    override_score?: number | null;
    reason_code?: string | null;
  } | null;
  manager_coaching_note?: {
    id: string;
    scorecard_id: string;
    reviewer_id: string;
    note: string;
    visible_to_rep: boolean;
    weakness_tags: string[];
    created_at: string;
  } | null;
  manager_note?: string | null;
  transcript: TranscriptTurn[];
};

export type RepTrend = {
  sessions: Array<{
    session_id: string;
    started_at: string;
    overall_score: number;
    category_scores: Record<string, number>;
  }>;
  category_averages: Record<string, number>;
  overall_trend: "improving" | "declining" | "stable";
};

export type RepPlan = {
  focus_skills: string[];
  recommended_difficulty: number;
  readiness_trajectory: Record<string, { sessions_to_readiness: number; slope: number }>;
  next_scenario_suggestion: {
    name: string;
    scenario_id: string | null;
    difficulty: number;
    reason: string;
  } | null;
};

export type RepProgress = {
  rep_id: string;
  rep_name?: string | null;
  rep_email?: string | null;
  rep_avatar_url?: string | null;
  session_count: number;
  scored_session_count: number;
  average_score: number | null;
  completed_drills?: number | null;
  streak_days?: number | null;
  personal_best?: number | null;
  personal_best_session_id?: string | null;
  most_improved_category?: string | null;
  most_improved_delta?: number | null;
  last_scored_session_at?: string | null;
};

export type HierarchyNode = {
  id: string;
  name: string;
  role: string;
  avatar_url: string | null;
};

export type RepSessionHistoryItem = {
  session_id: string;
  assignment_id: string | null;
  scenario_id: string;
  status: string;
  started_at: string;
  ended_at: string | null;
  overall_score: number | null;
};

export type WsInboundEvent = {
  type: string;
  sequence?: number;
  timestamp?: string;
  payload: Record<string, unknown>;
};

export type NotificationPreferences = {
  score_ready: boolean;
  assignment_created: boolean;
  assignment_due_soon: boolean;
  coaching_note: boolean;
  streak_nudge: boolean;
};

export const DEFAULT_NOTIFICATION_PREFERENCES: NotificationPreferences = {
  score_ready: true,
  assignment_created: true,
  assignment_due_soon: true,
  coaching_note: true,
  streak_nudge: true,
};

export type RegisteredDeviceToken = {
  id: string;
  user_id: string;
  platform: "ios" | "android";
  provider: "expo" | "fcm";
  token: string;
  status: string;
  last_seen_at: string;
};

export type AuthRole = "rep" | "manager" | "admin";

export type AuthUser = {
  id: string;
  org_id: string;
  team_id: string | null;
  role: AuthRole;
  name: string;
  email: string;
};

export type AuthTokenResponse = {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
};

export type InviteValidationResponse = {
  email: string;
  org_id: string;
  valid: boolean;
};
