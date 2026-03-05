import { useMemo, useState } from "react";

import { createFollowup, submitOverride } from "../lib/api";
import type { ReplayResponse } from "../lib/types";

type Props = {
  managerId: string;
  replay: ReplayResponse | null;
  onActionDone: () => Promise<void>;
};

export function ReplayPanel({ managerId, replay, onActionDone }: Props) {
  const [overrideScore, setOverrideScore] = useState("");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);

  const topWeakness = useMemo(() => replay?.scorecard?.weakness_tags?.[0] ?? null, [replay]);

  if (!replay) {
    return (
      <div className="panel replay-panel">
        <h2>Session Replay</h2>
        <p className="muted">Select a session from the manager feed.</p>
      </div>
    );
  }

  const scorecard = replay.scorecard;

  async function handleOverride() {
    if (!scorecard) {
      return;
    }
    setSaving(true);
    try {
      await submitOverride(managerId, scorecard.id, {
        reason_code: "manager_coaching",
        override_score: overrideScore ? Number(overrideScore) : undefined,
        notes
      });
      setOverrideScore("");
      setNotes("");
      await onActionDone();
    } finally {
      setSaving(false);
    }
  }

  async function handleFollowup() {
    if (!scorecard) {
      return;
    }
    const scenarioId = prompt("Scenario ID for follow-up assignment:");
    if (!scenarioId) {
      return;
    }
    setSaving(true);
    try {
      await createFollowup(managerId, scorecard.id, scenarioId);
      await onActionDone();
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="panel replay-panel">
      <div className="replay-header">
        <h2>Session {replay.session_id.slice(0, 8)}</h2>
        <span className="pill">{replay.status}</span>
      </div>

      <div className="metrics-row">
        <div className="metric">
          <span>Score</span>
          <strong>{scorecard?.overall_score ?? "--"}</strong>
        </div>
        <div className="metric">
          <span>Audio ms</span>
          <strong>{replay.transport_metrics.audio_duration_ms ?? 0}</strong>
        </div>
        <div className="metric">
          <span>Turns</span>
          <strong>{replay.transport_metrics.turn_count ?? 0}</strong>
        </div>
        <div className="metric">
          <span>Barge-ins</span>
          <strong>{replay.transport_metrics.barge_in_count ?? 0}</strong>
        </div>
      </div>

      <div className="two-col">
        <section>
          <h3>Weakness Tags</h3>
          <div className="tag-row">
            {(scorecard?.weakness_tags ?? []).map((tag) => (
              <span key={tag} className="tag">
                {tag}
              </span>
            ))}
            {!scorecard?.weakness_tags?.length ? <span className="muted">No weaknesses tagged</span> : null}
          </div>

          <h3>Stage Timeline</h3>
          <ul className="timeline">
            {replay.stage_timeline.map((stage) => (
              <li key={`${stage.stage}-${stage.turn_index}`}>
                <span>{stage.turn_index}</span>
                <strong>{stage.stage}</strong>
                <small>{new Date(stage.entered_at).toLocaleTimeString()}</small>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h3>Coach Actions</h3>
          <label>
            Override score
            <input value={overrideScore} onChange={(e) => setOverrideScore(e.target.value)} placeholder="8.5" />
          </label>
          <label>
            Notes
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} placeholder="Coaching notes" />
          </label>
          <div className="action-row">
            <button onClick={handleOverride} disabled={saving || !scorecard}>
              Save Review
            </button>
            <button onClick={handleFollowup} disabled={saving || !scorecard}>
              Assign Follow-up ({topWeakness ?? "drill"})
            </button>
          </div>
        </section>
      </div>

      <section>
        <h3>Interruption Timeline</h3>
        <ul className="timeline">
          {replay.interruption_timeline.length === 0 ? <li className="muted">No interruptions detected.</li> : null}
          {replay.interruption_timeline.map((interrupt) => (
            <li key={interrupt.event_id}>
              <span>{interrupt.sequence}</span>
              <strong>{interrupt.reason}</strong>
              <small>
                {new Date(interrupt.at).toLocaleTimeString()} · {interrupt.latency_ms}ms
              </small>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h3>Transcript</h3>
        <ul className="transcript">
          {replay.transcript_turns.map((turn) => (
            <li key={turn.turn_id} className={turn.speaker === "rep" ? "rep" : "ai"}>
              <span>{turn.speaker}</span>
              <p>{turn.text}</p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
