import { useMemo, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  Clock,
  FileText,
  Mic,
  MessageSquare,
  Save,
  Send,
  Target,
  TrendingUp,
  Zap,
} from "lucide-react";

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
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6"
      >
        <h2 className="text-lg font-semibold tracking-tight text-ink">Session Replay</h2>
        <p className="text-muted mt-2 text-sm">Select a session from the manager feed.</p>
      </motion.div>
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
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6 space-y-6"
    >
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-accent/10 flex items-center justify-center">
            <FileText className="w-4.5 h-4.5 text-accent" />
          </div>
          <h2 className="text-lg font-semibold tracking-tight text-ink">
            Session {replay.session_id.slice(0, 8)}
          </h2>
        </div>
        <span className="bg-accent/10 text-accent text-xs font-medium rounded-full px-3 py-1">
          {replay.status}
        </span>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: "Score", value: scorecard?.overall_score ?? "--", icon: TrendingUp },
          { label: "Audio ms", value: replay.transport_metrics.audio_duration_ms ?? 0, icon: Mic },
          { label: "Turns", value: replay.transport_metrics.turn_count ?? 0, icon: MessageSquare },
          { label: "Barge-ins", value: replay.transport_metrics.barge_in_count ?? 0, icon: Zap },
        ].map((metric) => (
          <motion.div
            key={metric.label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-white/50 backdrop-blur-xl border border-white/30 rounded-xl p-4 text-center"
          >
            <div className="flex items-center justify-center mb-2">
              <metric.icon className="w-4 h-4 text-muted" />
            </div>
            <span className="text-xs text-muted font-medium uppercase tracking-wide">{metric.label}</span>
            <strong className="block text-xl font-bold text-ink mt-0.5">{metric.value}</strong>
          </motion.div>
        ))}
      </div>

      {/* Two Column Layout */}
      <div className="grid grid-cols-2 gap-6">
        {/* Left Column */}
        <div className="space-y-6">
          {/* Weakness Tags */}
          <div>
            <div className="flex items-center gap-2 mb-3">
              <AlertTriangle className="w-4 h-4 text-muted" />
              <h3 className="text-sm font-semibold tracking-tight text-ink">Weakness Tags</h3>
            </div>
            <div className="flex flex-wrap gap-2">
              {(scorecard?.weakness_tags ?? []).map((tag) => (
                <span
                  key={tag}
                  className="bg-accent-soft text-accent rounded-full px-3 py-1 text-xs font-medium"
                >
                  {tag}
                </span>
              ))}
              {!scorecard?.weakness_tags?.length ? (
                <span className="text-muted text-sm">No weaknesses tagged</span>
              ) : null}
            </div>
          </div>

          {/* Stage Timeline */}
          <div className="border-t border-white/20 pt-6">
            <div className="flex items-center gap-2 mb-3">
              <Clock className="w-4 h-4 text-muted" />
              <h3 className="text-sm font-semibold tracking-tight text-ink">Stage Timeline</h3>
            </div>
            <div className="relative ml-3">
              {/* Vertical connecting line */}
              <div className="absolute left-[5px] top-2 bottom-2 w-px bg-accent/20" />
              <ul className="space-y-3">
                {replay.stage_timeline.map((stage) => (
                  <li key={`${stage.stage}-${stage.turn_index}`} className="flex items-start gap-3 relative">
                    <div className="w-[11px] h-[11px] rounded-full bg-accent border-2 border-white mt-1 z-10 shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs text-muted font-mono">#{stage.turn_index}</span>
                        <strong className="text-sm text-ink font-medium">{stage.stage}</strong>
                      </div>
                      <small className="text-xs text-muted">{new Date(stage.entered_at).toLocaleTimeString()}</small>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>

        {/* Right Column - Coach Actions */}
        <div className="bg-white/30 backdrop-blur-xl border border-white/20 rounded-xl p-5 space-y-4">
          <div className="flex items-center gap-2 mb-1">
            <Target className="w-4 h-4 text-accent" />
            <h3 className="text-sm font-semibold tracking-tight text-ink">Coach Actions</h3>
          </div>
          <div>
            <label className="block text-xs font-medium text-muted mb-1.5">Override score</label>
            <input
              value={overrideScore}
              onChange={(e) => setOverrideScore(e.target.value)}
              placeholder="8.5"
              className="w-full bg-white/50 backdrop-blur-xl border border-white/30 rounded-xl px-3 py-2.5 text-sm text-ink placeholder:text-muted/50 focus:ring-2 focus:ring-accent focus:border-accent outline-none transition-all"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-muted mb-1.5">Notes</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              placeholder="Coaching notes"
              className="w-full bg-white/50 backdrop-blur-xl border border-white/30 rounded-xl px-3 py-2.5 text-sm text-ink placeholder:text-muted/50 focus:ring-2 focus:ring-accent focus:border-accent outline-none transition-all resize-none"
            />
          </div>
          <div className="flex gap-3 pt-1">
            <button
              onClick={handleOverride}
              disabled={saving || !scorecard}
              className="flex items-center gap-2 bg-accent text-white rounded-xl px-4 py-2.5 text-sm font-medium hover:bg-accent-hover transition-colors disabled:opacity-50 cursor-pointer disabled:cursor-not-allowed"
            >
              <Save className="w-3.5 h-3.5" />
              Save Review
            </button>
            <button
              onClick={handleFollowup}
              disabled={saving || !scorecard}
              className="flex items-center gap-2 bg-white/50 backdrop-blur-xl border border-white/30 text-ink rounded-xl px-4 py-2.5 text-sm font-medium hover:bg-white/70 transition-colors disabled:opacity-50 cursor-pointer disabled:cursor-not-allowed"
            >
              <Send className="w-3.5 h-3.5" />
              Assign Follow-up ({topWeakness ?? "drill"})
            </button>
          </div>
        </div>
      </div>

      {/* Interruption Timeline */}
      <div className="border-t border-white/20 pt-6">
        <div className="flex items-center gap-2 mb-3">
          <Activity className="w-4 h-4 text-muted" />
          <h3 className="text-sm font-semibold tracking-tight text-ink">Interruption Timeline</h3>
        </div>
        {replay.interruption_timeline.length === 0 ? (
          <p className="text-muted text-sm">No interruptions detected.</p>
        ) : (
          <div className="relative ml-3">
            <div className="absolute left-[5px] top-2 bottom-2 w-px bg-amber-300/40" />
            <ul className="space-y-3">
              {replay.interruption_timeline.map((interrupt) => (
                <li key={interrupt.event_id} className="flex items-start gap-3 relative">
                  <div className="w-[11px] h-[11px] rounded-full bg-amber-400 border-2 border-white mt-1 z-10 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted font-mono">#{interrupt.sequence}</span>
                      <strong className="text-sm text-ink font-medium">{interrupt.reason}</strong>
                    </div>
                    <small className="text-xs text-muted">
                      {new Date(interrupt.at).toLocaleTimeString()} · {interrupt.latency_ms}ms
                    </small>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Transcript */}
      <div className="border-t border-white/20 pt-6">
        <div className="flex items-center gap-2 mb-3">
          <MessageSquare className="w-4 h-4 text-muted" />
          <h3 className="text-sm font-semibold tracking-tight text-ink">Transcript</h3>
        </div>
        <ul className="space-y-2">
          {replay.transcript_turns.map((turn, index) => (
            <li
              key={turn.turn_id}
              className={`flex gap-3 p-3 rounded-xl ${
                index % 2 === 0 ? "bg-white/20" : "bg-white/10"
              } ${
                turn.speaker === "rep"
                  ? "border-l-3 border-l-accent"
                  : "border-l-3 border-l-amber-400"
              }`}
            >
              <span
                className={`shrink-0 text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-md h-fit mt-0.5 ${
                  turn.speaker === "rep"
                    ? "bg-accent/10 text-accent"
                    : "bg-amber-400/15 text-amber-700"
                }`}
              >
                {turn.speaker}
              </span>
              <p className="text-sm text-ink leading-relaxed">{turn.text}</p>
            </li>
          ))}
        </ul>
      </div>
    </motion.div>
  );
}
