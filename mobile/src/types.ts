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

export type Scorecard = {
  id: string;
  overall_score: number;
  category_scores: Record<string, number>;
  highlights: Array<{ type: string; note: string; turn_id?: string | null }>;
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
};

export type WsInboundEvent = {
  type: string;
  sequence?: number;
  timestamp?: string;
  payload: Record<string, unknown>;
};
