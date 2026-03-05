export type FeedItem = {
  session_id: string;
  rep_id: string;
  assignment_id: string;
  overall_score: number | null;
  category_scores: Record<string, number>;
  highlights: Array<{ type: string; note: string }>;
  manager_reviewed: boolean;
  assignment_status: string;
  session_status: string;
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
  transcript_turns: Array<{
    turn_id: string;
    turn_index: number;
    speaker: string;
    stage: string;
    text: string;
    started_at: string;
    ended_at: string;
  }>;
  objection_timeline: Array<{
    turn_id: string;
    turn_index: number;
    objection_tags: string[];
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
    category_scores: Record<string, number>;
    highlights: Array<{ type: string; note: string; turn_id?: string }>;
    ai_summary: string;
    evidence_turn_ids: string[];
    weakness_tags: string[];
  };
};
