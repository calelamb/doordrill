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

export type Scorecard = {
  id: string;
  overall_score: number;
  category_scores: Record<string, number | { score?: number; rationale?: string; evidence_turn_ids?: string[] }>;
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
  manager_note?: string | null;
};

export type RepProgress = {
  rep_id: string;
  session_count: number;
  scored_session_count: number;
  average_score: number | null;
};

export type WsInboundEvent = {
  type: string;
  sequence?: number;
  timestamp?: string;
  payload: Record<string, unknown>;
};
