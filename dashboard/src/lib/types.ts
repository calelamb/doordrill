export type CategoryScoreValue =
  | number
  | {
    score: number;
    rationale?: string;
    evidence_turn_ids?: string[];
  };

export type HighlightMoment = {
  type: string;
  note: string;
  turn_id?: string;
};

export type FeedItem = {
  session_id: string;
  rep_id: string;
  assignment_id: string;
  overall_score: number | null;
  category_scores: Record<string, CategoryScoreValue>;
  highlights: HighlightMoment[];
  manager_reviewed: boolean;
  assignment_status: string;
  session_status: string;
  rep_name?: string | null;
  scenario_id?: string | null;
  scenario_name?: string | null;
  scenario_difficulty?: number | null;
  scenario_description?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  duration_seconds?: number | null;
};

export type SessionDetail = {
  id: string;
  assignment_id: string;
  rep_id: string;
  scenario_id: string;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  duration_seconds?: number | null;
};

export type AssignmentDetail = {
  id: string;
  status: string;
  due_at: string | null;
  min_score_target?: number | null;
  retry_policy?: Record<string, unknown>;
};

export type TranscriptTurn = {
  turn_id: string;
  turn_index: number;
  speaker: string;
  stage: string;
  text: string;
  started_at: string;
  ended_at: string;
};

export type ReplayResponse = {
  session_id: string;
  status: string;
  audio_artifacts: Array<{
    artifact_id: string;
    storage_key: string;
    url: string;
    metadata: Record<string, unknown>;
  }>;
  transcript_turns: TranscriptTurn[];
  objection_timeline: Array<{
    turn_id: string;
    turn_index: number;
    objection_tags: string[];
  }>;
  interruption_timeline: Array<{
    event_id: string;
    at: string;
    reason: string;
    latency_ms: number;
    sequence: number;
  }>;
  stage_timeline: Array<{
    stage: string;
    entered_at: string;
    turn_index: number;
    speaker: string;
  }>;
  transport_metrics: Record<string, number>;
  scorecard: null | {
    id: string;
    overall_score: number;
    category_scores: Record<string, CategoryScoreValue>;
    highlights: HighlightMoment[];
    ai_summary: string;
    evidence_turn_ids: string[];
    weakness_tags: string[];
  };
  session?: SessionDetail;
  assignment?: AssignmentDetail | null;
};

export type ManagerAnalytics = {
  manager_id: string;
  assignment_count: number;
  completed_assignment_count: number;
  sessions_count: number;
  active_rep_count: number;
  average_score: number | null;
  completion_rate: number;
};

export type RepProgress = {
  rep_id: string;
  session_count: number;
  scored_session_count: number;
  average_score: number | null;
  latest_sessions: Array<{
    session_id: string;
    started_at: string | null;
    status: string | null;
    overall_score: number | null;
  }>;
};

export type ManagerActionLog = {
  id: string;
  manager_id: string;
  action_type: string;
  target_type: string;
  target_id: string;
  summary: string | null;
  payload: Record<string, unknown>;
  occurred_at: string;
};

export type ManagerAssignment = {
  id: string;
  scenario_id: string;
  rep_id: string;
  assigned_by: string;
  due_at: string | null;
  status: string;
  min_score_target: number | null;
  retry_policy: Record<string, unknown>;
  created_at?: string | null;
};

export type ManagerTeamMember = {
  id: string;
  name: string;
  email: string;
  team_id?: string | null;
  org_id?: string | null;
  created_at?: string | null;
};

export type ScenarioSummary = {
  id: string;
  org_id?: string | null;
  name: string;
  industry: string;
  difficulty: number;
  description: string;
  persona: Record<string, unknown>;
  rubric: Record<string, unknown>;
  stages: string[];
  created_by_id?: string | null;
};

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
  scorecard: null | {
    id: string;
    overall_score: number;
    category_scores: Record<string, CategoryScoreValue>;
    highlights: HighlightMoment[];
    ai_summary: string;
    evidence_turn_ids: string[];
    weakness_tags: string[];
  };
};
