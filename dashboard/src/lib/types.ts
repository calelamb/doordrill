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
  latest_reviewed_at?: string | null;
  latest_coaching_note_preview?: string | null;
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
  rep?: {
    id: string;
    name: string;
    email: string;
    team_id?: string | null;
  } | null;
  scenario?: {
    id: string;
    name: string;
    industry: string;
    difficulty: number;
  } | null;
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
  manager_reviews?: ManagerReview[];
  coaching_notes?: ManagerCoachingNote[];
  latest_coaching_note?: ManagerCoachingNote | null;
};

export type ManagerAnalytics = {
  manager_id: string;
  assignment_count: number;
  completed_assignment_count: number;
  sessions_count: number;
  active_rep_count: number;
  average_score: number | null;
  completion_rate: number;
  summary?: CommandCenterResponse["summary"];
  score_trend?: CommandCenterResponse["score_trend"];
  scenario_pass_matrix?: CommandCenterResponse["scenario_pass_matrix"];
  rep_risk_matrix?: CommandCenterResponse["rep_risk_matrix"];
  weakest_categories?: CommandCenterResponse["weakest_categories"];
  alerts_preview?: CommandCenterResponse["alerts_preview"];
};

export type RepProgress = {
  rep_id: string;
  rep_name?: string;
  rep_email?: string;
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

export type ManagerReview = {
  id: string;
  scorecard_id: string;
  reviewer_id: string;
  reviewed_at: string;
  reason_code: string;
  override_score: number | null;
  notes: string | null;
  idempotency_key?: string | null;
};

export type ManagerCoachingNote = {
  id: string;
  scorecard_id: string;
  reviewer_id: string;
  note: string;
  visible_to_rep: boolean;
  weakness_tags: string[];
  created_at: string;
};

export type AlertItem = {
  id: string;
  severity: "high" | "medium" | "low";
  kind: string;
  title: string;
  description: string;
  occurred_at: string;
  rep_id?: string | null;
  rep_name?: string | null;
  session_id?: string | null;
  scenario_id?: string | null;
};

export type CommandCenterResponse = {
  manager_id: string;
  period: string;
  date_from: string;
  date_to: string;
  summary: {
    team_average_score: number | null;
    team_average_delta_vs_previous_period: number | null;
    completion_rate: number;
    review_coverage_rate: number;
    active_rep_count: number;
    reps_at_risk: number;
    overdue_assignments: number;
    sessions_count: number;
    scored_session_count: number;
  };
  score_trend: Array<{
    date: string;
    session_count: number;
    average_score: number | null;
  }>;
  score_distribution_histogram: Array<{
    label: string;
    min: number;
    max: number;
    count: number;
  }>;
  scenario_pass_matrix: Array<{
    scenario_id: string;
    scenario_name: string;
    difficulty: number;
    session_count: number;
    scored_count: number;
    pass_count: number;
    average_score: number | null;
    pass_rate: number;
  }>;
  rep_risk_matrix: Array<{
    rep_id: string;
    rep_name: string;
    average_score: number;
    score_delta: number;
    volatility: number;
    completion_rate: number;
    red_flag_count: number;
    unreviewed_scored_sessions: number;
    risk_level: "high" | "medium" | "low";
    risk_score: number;
  }>;
  weakest_categories: Array<{
    category: string;
    average_score: number;
  }>;
  alerts_preview: AlertItem[];
};

export type ScenarioIntelligenceResponse = {
  manager_id: string;
  period: string;
  date_from: string;
  date_to: string;
  items: Array<{
    scenario_id: string;
    scenario_name: string;
    difficulty: number;
    session_count: number;
    scored_session_count: number;
    pass_rate: number;
    average_score: number | null;
    rep_count: number;
    average_duration_seconds: number | null;
    improvement_delta: number | null;
    top_weakness_tags: string[];
    top_objection_tags: string[];
  }>;
  difficulty_bands: Array<{
    difficulty: number;
    session_count: number;
    average_score: number | null;
    pass_rate: number;
  }>;
  objection_failure_map: Array<{
    scenario_id: string;
    scenario_name: string;
    objection_tag: string;
    count: number;
  }>;
};

export type CoachingAnalyticsResponse = {
  manager_id: string;
  period: string;
  date_from: string;
  date_to: string;
  summary: {
    coaching_note_count: number;
    review_count: number;
    override_rate: number;
    average_override_delta: number | null;
  };
  coaching_uplift: Array<{
    rep_id: string;
    rep_name: string;
    session_id: string;
    scenario_name: string;
    before_score: number;
    after_score: number | null;
    delta: number | null;
    note: string;
    weakness_tags: string[];
    created_at: string;
  }>;
  weakness_tag_uplift: Array<{
    tag: string;
    delta: number;
    sample_size: number;
  }>;
  manager_calibration: Array<{
    reviewer_id: string;
    reviewer_name: string;
    review_count: number;
    override_count: number;
    average_override_delta: number | null;
    harsh_adjustments: number;
    lenient_adjustments: number;
  }>;
  intervention_timeline: Array<{
    date: string;
    review_count: number;
    coaching_note_count: number;
  }>;
  recent_notes: Array<{
    id: string;
    rep_id: string;
    rep_name: string;
    scenario_name: string;
    note: string;
    visible_to_rep: boolean;
    weakness_tags: string[];
    created_at: string;
  }>;
};

export type ExplorerResponse = {
  manager_id: string;
  total_count: number;
  filters: Record<string, unknown>;
  items: Array<{
    session_id: string;
    rep_id: string;
    rep_name: string;
    scenario_id: string;
    scenario_name: string;
    started_at: string | null;
    ended_at: string | null;
    duration_seconds: number | null;
    overall_score: number | null;
    manager_reviewed: boolean;
    latest_reviewed_at: string | null;
    latest_coaching_note_preview: string | null;
    weakness_tags: string[];
    objection_tags: string[];
    barge_in_count: number;
    highlight_count: number;
    transcript_preview: string;
    assignment_status: string;
    session_status: string;
  }>;
};

export type BenchmarksResponse = {
  manager_id: string;
  period: string;
  date_from: string;
  date_to: string;
  score_benchmarks: {
    median: number | null;
    upper_quartile: number | null;
    lower_quartile: number | null;
    session_count: number;
  };
};
