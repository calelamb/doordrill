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

export type RepInsightResponse = {
  rep_id: string;
  rep_name: string;
  generated_at: string;
  headline: string;
  primary_weakness: string;
  root_cause: string;
  drill_recommendation: string;
  coaching_script: string;
  expected_improvement: string;
  data_summary: Record<string, unknown>;
};

export type SessionAnnotation = {
  turn_id: string;
  type: "strength" | "weakness";
  label: string;
  explanation: string;
  coaching_tip?: string | null;
};

export type SessionAnnotationsResponse = {
  session_id: string;
  generated_at: string;
  annotations: SessionAnnotation[];
};

export type TeamCoachingSummaryResponse = {
  manager_id: string;
  period_days: number;
  generated_at: string;
  summary: string;
  data_summary: Record<string, unknown>;
};

export type ManagerAnalytics = {
  manager_id: string;
  period?: string;
  date_from?: string;
  date_to?: string;
  assignment_count: number;
  completed_assignment_count: number;
  sessions_count: number;
  active_rep_count: number;
  average_score: number | null;
  completion_rate: number;
  team_average_score?: number | null;
  team_average_delta_vs_previous_period?: number | null;
  completion_rate_by_rep?: Array<{
    rep_id: string;
    rep_name: string;
    assignment_count: number;
    completed_assignment_count: number;
    completion_rate: number;
  }>;
  scenario_pass_rates?: Array<{
    scenario_id: string;
    scenario_name: string;
    scored_session_count: number;
    pass_count: number;
    pass_rate: number;
  }>;
  score_distribution_histogram?: CommandCenterResponse["score_distribution_histogram"];
  summary?: CommandCenterResponse["summary"];
  score_trend?: CommandCenterResponse["score_trend"];
  scenario_pass_matrix?: CommandCenterResponse["scenario_pass_matrix"];
  rep_risk_matrix?: CommandCenterResponse["rep_risk_matrix"];
  weakest_categories?: CommandCenterResponse["weakest_categories"];
  alerts_preview?: CommandCenterResponse["alerts_preview"];
  _meta?: CommandCenterResponse["_meta"];
};

export type RepProgress = {
  rep_id: string;
  rep_name?: string;
  days?: number;
  date_from?: string;
  date_to?: string;
  session_count: number;
  scored_session_count: number;
  average_score: number | null;
  current_period_category_averages?: Record<string, number>;
  weak_area_tags?: string[];
  latest_sessions: Array<{
    session_id: string;
    scenario_id?: string | null;
    scenario_name?: string | null;
    started_at: string | null;
    status: string | null;
    overall_score: number | null;
  }>;
  trend?: Array<{
    session_id: string;
    started_at: string | null;
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
  focus_turn_id?: string | null;
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
    sample_session_id?: string | null;
    focus_turn_id?: string | null;
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
    session_id?: string | null;
    focus_turn_id?: string | null;
  }>;
  weakest_categories: Array<{
    category: string;
    average_score: number;
    session_id?: string | null;
    focus_turn_id?: string | null;
  }>;
  alerts?: AlertItem[];
  alerts_preview: AlertItem[];
  _meta?: {
    query_name: string;
    cache_status: string;
    generated_at: string;
    cached_at: string | null;
    analytics_last_refresh_at: string | null;
    freshness_seconds: number | null;
    query_duration_ms: number;
    cache?: {
      backend: string;
      entries?: number;
      hits?: number;
      misses?: number;
      writes?: number;
      max_entries?: number;
      ttl_seconds?: number;
    };
  };
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
    sample_session_id?: string | null;
    focus_turn_id?: string | null;
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
    calibration_drift_score?: number | null;
    intervention_improved_rate?: number | null;
    retry_uplift_avg?: number | null;
    coached_retry_uplift_avg?: number | null;
  };
  coaching_uplift: Array<{
    rep_id: string;
    rep_name: string;
    session_id: string;
    focus_turn_id?: string | null;
    next_session_id?: string | null;
    scenario_name: string;
    before_score: number;
    after_score: number | null;
    delta: number | null;
    outcome?: string;
    visible_to_rep?: boolean;
    note: string;
    weakness_tags: string[];
    created_at: string;
  }>;
  weakness_tag_uplift: Array<{
    tag: string;
    delta: number;
    sample_size: number;
    improved_count?: number;
    flat_count?: number;
    regressed_count?: number;
  }>;
  manager_calibration: Array<{
    reviewer_id: string;
    reviewer_name: string;
    review_count: number;
    override_count: number;
    average_override_delta: number | null;
    absolute_average_delta?: number | null;
    bias_direction?: string;
    harsh_adjustments: number;
    lenient_adjustments: number;
  }>;
  intervention_timeline: Array<{
    date: string;
    review_count: number;
    coaching_note_count: number;
  }>;
  calibration_drift_timeline?: Array<{
    date: string;
    review_count: number;
    average_delta: number | null;
    average_absolute_delta: number | null;
  }>;
  retry_impact?: Array<{
    rep_id: string;
    rep_name: string;
    scenario_id: string;
    scenario_name: string;
    from_session_id: string;
    to_session_id: string;
    before_score: number;
    after_score: number;
    delta: number;
    coached_between_attempts: boolean;
    days_between: number | null;
  }>;
  intervention_segments?: Array<{
    visibility: string;
    outcome: string;
    count: number;
  }>;
  score_drift_by_scenario?: Array<{
    scenario_id: string;
    scenario_name: string;
    review_count: number;
    average_delta: number | null;
    average_absolute_delta: number | null;
  }>;
  recent_notes: Array<{
    id: string;
    rep_id: string;
    rep_name: string;
    session_id?: string;
    focus_turn_id?: string | null;
    scenario_name: string;
    note: string;
    visible_to_rep: boolean;
    weakness_tags: string[];
    delta?: number | null;
    outcome?: string;
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
    focus_turn_id?: string | null;
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

export type ManagerAnalyticsOperations = {
  manager_id: string;
  analytics_last_refresh_at: string | null;
  cache: {
    backend: string;
    entries?: number;
    hits?: number;
    misses?: number;
    writes?: number;
    max_entries?: number;
    ttl_seconds?: number;
  };
  refresh_runs: {
    failed_count: number;
    running_count: number;
    recent: Array<{
      id: string;
      scope_type: string;
      scope_id: string | null;
      status: string;
      started_at: string | null;
      completed_at: string | null;
      error: string | null;
      row_counts_json: Record<string, unknown>;
    }>;
  };
  warehouse: {
    fact_session_count: number;
    manager_dim_last_refreshed_at: string | null;
    manager_rep_count: number;
  };
  materialized_views: {
    count: number;
    recent: Array<{
      id: string;
      view_name: string;
      period_key: string;
      row_count: number;
      window_start: string | null;
      window_end: string | null;
      refreshed_at: string | null;
    }>;
  };
  partitions: {
    count: number;
    active: Array<{
      table_name: string;
      partition_key: string;
      backend: string;
      status: string;
      range_start: string | null;
      range_end: string | null;
    }>;
  };
  runtime: {
    redis_configured: boolean;
    cache_ttl_seconds: number;
    warn_ms: number;
    critical_ms: number;
  };
  _meta?: CommandCenterResponse["_meta"];
};

export type AnalyticsMetricDefinition = {
  metric_key: string;
  display_name: string;
  description: string;
  entity_type: string;
  aggregation_method: string;
  owner: string;
  metadata_json: Record<string, unknown>;
};
