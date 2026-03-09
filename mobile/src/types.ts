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
  score: number;
  rationale_summary?: string;
  rationale_detail?: string;
  improvement_target?: string | null;
  behavioral_signals?: string[];
  evidence_turn_ids?: string[];
  confidence?: number;
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
  overall_score: number;
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

export type RepProgress = {
  rep_id: string;
  rep_name?: string | null;
  rep_email?: string | null;
  rep_avatar_url?: string | null;
  session_count: number;
  scored_session_count: number;
  average_score: number | null;
  completed_drills?: number | null;
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
