import { useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  Clock,
  FileText,
  MessageSquare,
  Save,
  Send,
  Target,
  Volume2,
  Zap,
} from "lucide-react";

import { createCoachingNote, createFollowup, submitOverride } from "../lib/api";
import type { CategoryScoreValue, ReplayResponse, TranscriptTurn } from "../lib/types";
import { EmptyState } from "./shared/EmptyState";
import { ScoreChip } from "./shared/ScoreChip";

type Props = {
  managerId: string;
  replay: ReplayResponse | null;
  onActionDone: () => Promise<void>;
  focusTurnId?: string | null;
  focusCategory?: string | null;
};

const CATEGORY_META = [
  { key: "opening", label: "Opening", weight: "15%" },
  { key: "pitch_delivery", label: "Pitch", weight: "25%" },
  { key: "objection_handling", label: "Objection Handling", weight: "30%" },
  { key: "closing_technique", label: "Closing", weight: "20%" },
  { key: "professionalism", label: "Professionalism", weight: "10%" },
] as const;

const PLAYBACK_SPEEDS = [1, 1.25, 1.5, 2] as const;

type UiReasonCode = "grading_error" | "extenuating_circumstance" | "calibration_correction";

type TimelineTurn = TranscriptTurn & {
  startOffset: number;
  endOffset: number;
};

function normalizeCategory(value: CategoryScoreValue | undefined) {
  if (typeof value === "number") {
    return { score: value, rationale: "", evidenceTurnIds: [] as string[] };
  }
  return {
    score: value?.score ?? 0,
    rationale: value?.rationale ?? "",
    evidenceTurnIds: value?.evidence_turn_ids ?? []
  };
}

function formatClock(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = Math.floor(totalSeconds % 60);
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function mapReasonCode(reason: UiReasonCode, currentScore: number | null, overrideScore: string): string {
  if (reason === "extenuating_circumstance") {
    return "policy_override";
  }
  if (reason === "calibration_correction") {
    return "manager_coaching";
  }
  const overrideValue = Number(overrideScore);
  if (Number.isFinite(overrideValue) && currentScore !== null && overrideValue < currentScore) {
    return "lenient_ai";
  }
  return "harsh_ai";
}

function buildTurnTimeline(turns: TranscriptTurn[]): TimelineTurn[] {
  const origin = turns.length ? new Date(turns[0].started_at).getTime() : 0;
  return turns.map((turn) => {
    const start = new Date(turn.started_at).getTime();
    const end = new Date(turn.ended_at).getTime();
    const startOffset = Math.max(0, (start - origin) / 1000);
    const endOffset = Math.max(startOffset + 0.25, (end - origin) / 1000);
    return {
      ...turn,
      startOffset,
      endOffset,
    };
  });
}

export function ReplayPanel({ managerId, replay, onActionDone, focusTurnId, focusCategory }: Props) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const turnRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [overrideScore, setOverrideScore] = useState("");
  const [overrideReason, setOverrideReason] = useState<UiReasonCode>("grading_error");
  const [reviewNotes, setReviewNotes] = useState("");
  const [coachingNote, setCoachingNote] = useState("");
  const [followupScenarioId, setFollowupScenarioId] = useState("");
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [playbackRate, setPlaybackRate] = useState<(typeof PLAYBACK_SPEEDS)[number]>(1);
  const [currentTime, setCurrentTime] = useState(0);
  const [activeTurnId, setActiveTurnId] = useState<string | null>(null);

  const timelineTurns = useMemo(() => buildTurnTimeline(replay?.transcript_turns ?? []), [replay?.transcript_turns]);
  const totalDuration = useMemo(() => {
    const audioDuration = replay?.transport_metrics?.audio_duration_ms;
    if (typeof audioDuration === "number" && audioDuration > 0) {
      return audioDuration / 1000;
    }
    return timelineTurns[timelineTurns.length - 1]?.endOffset ?? 0;
  }, [replay?.transport_metrics, timelineTurns]);

  const audioUrl = replay?.audio_artifacts?.[0]?.url ?? "";
  const topWeakness = useMemo(() => replay?.scorecard?.weakness_tags?.[0] ?? null, [replay]);
  const highlightMap = useMemo(() => {
    const strong = new Set<string>();
    const improve = new Set<string>();
    for (const item of replay?.scorecard?.highlights ?? []) {
      if (!item.turn_id) {
        continue;
      }
      if (item.type === "strong") {
        strong.add(item.turn_id);
      }
      if (item.type === "improve") {
        improve.add(item.turn_id);
      }
    }
    return { strong, improve };
  }, [replay?.scorecard?.highlights]);
  const evidenceTurnIds = useMemo(() => new Set(replay?.scorecard?.evidence_turn_ids ?? []), [replay?.scorecard?.evidence_turn_ids]);

  const interruptedTurnIds = useMemo(() => {
    const flagged = new Set<string>();
    for (const interruption of replay?.interruption_timeline ?? []) {
      const at = new Date(interruption.at).getTime();
      const nearest = timelineTurns.find((turn) => {
        const started = new Date(turn.started_at).getTime();
        const ended = new Date(turn.ended_at).getTime();
        return at >= started && at <= ended;
      }) || timelineTurns.find((turn) => new Date(turn.started_at).getTime() >= at);
      if (nearest) {
        flagged.add(nearest.turn_id);
      }
    }
    return flagged;
  }, [replay?.interruption_timeline, timelineTurns]);

  const categories = useMemo(() => {
    const turnsById = new Map(timelineTurns.map((turn) => [turn.turn_id, turn]));
    return CATEGORY_META.map((category) => {
      const normalized = normalizeCategory(replay?.scorecard?.category_scores?.[category.key]);
      const evidenceTurn = normalized.evidenceTurnIds
        .map((id) => turnsById.get(id)?.text)
        .find(Boolean) ?? "";
      return {
        ...category,
        ...normalized,
        evidenceQuote: evidenceTurn,
      };
    });
  }, [replay?.scorecard?.category_scores, timelineTurns]);
  const criticalMoments = useMemo(() => {
    const moments: Array<{
      id: string;
      label: string;
      note: string;
      turnId: string | null;
      tone: "strong" | "improve" | "evidence";
      categoryKey?: string;
    }> = [];

    for (const item of replay?.scorecard?.highlights ?? []) {
      moments.push({
        id: `highlight-${item.turn_id ?? item.note}`,
        label: item.type === "strong" ? "Strong moment" : "Coach this",
        note: item.note,
        turnId: item.turn_id ?? null,
        tone: item.type === "strong" ? "strong" : "improve",
      });
    }

    for (const category of categories) {
      if (!category.evidenceTurnIds.length) {
        continue;
      }
      moments.push({
        id: `evidence-${category.key}`,
        label: `${category.label} evidence`,
        note: category.evidenceQuote || category.rationale || "Evidence linked from grading rationale.",
        turnId: category.evidenceTurnIds[0] ?? null,
        tone: "evidence",
        categoryKey: category.key,
      });
    }

    return moments.slice(0, 10);
  }, [categories, replay?.scorecard?.highlights]);

  useEffect(() => {
    setFollowupScenarioId(replay?.session?.scenario_id ?? "");
    setOverrideScore("");
    setReviewNotes("");
    setCoachingNote("");
    setActionError(null);
    setExpandedCategory(focusCategory ?? null);
    setCurrentTime(0);
    setActiveTurnId(focusTurnId ?? timelineTurns[0]?.turn_id ?? null);
  }, [focusCategory, focusTurnId, replay?.session?.scenario_id, replay?.session_id, timelineTurns]);

  useEffect(() => {
    if (!focusTurnId) {
      return;
    }
    const turn = timelineTurns.find((item) => item.turn_id === focusTurnId);
    if (!turn) {
      return;
    }
    setActiveTurnId(turn.turn_id);
    turnRefs.current[turn.turn_id]?.scrollIntoView({ behavior: "smooth", block: "center" });
    const audio = audioRef.current;
    if (audio) {
      audio.currentTime = turn.startOffset;
      setCurrentTime(turn.startOffset);
    }
  }, [focusTurnId, timelineTurns]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }
    audio.playbackRate = playbackRate;
  }, [playbackRate, audioUrl]);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !timelineTurns.length) {
      return;
    }
    const handleTimeUpdate = () => {
      const time = audio.currentTime;
      setCurrentTime(time);
      const turn = timelineTurns.find((candidate) => time >= candidate.startOffset && time <= candidate.endOffset)
        ?? timelineTurns.find((candidate) => candidate.startOffset >= time)
        ?? timelineTurns[timelineTurns.length - 1];
      setActiveTurnId(turn?.turn_id ?? null);
    };
    audio.addEventListener("timeupdate", handleTimeUpdate);
    audio.addEventListener("loadedmetadata", handleTimeUpdate);
    return () => {
      audio.removeEventListener("timeupdate", handleTimeUpdate);
      audio.removeEventListener("loadedmetadata", handleTimeUpdate);
    };
  }, [timelineTurns, audioUrl]);

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

  function seekToTurn(turnId: string) {
    const audio = audioRef.current;
    const turn = timelineTurns.find((item) => item.turn_id === turnId);
    if (!audio || !turn) {
      return;
    }
    audio.currentTime = turn.startOffset;
    setCurrentTime(turn.startOffset);
    setActiveTurnId(turn.turn_id);
  }

  function seekFromWaveform(seconds: number) {
    const audio = audioRef.current;
    if (!audio) {
      return;
    }
    audio.currentTime = seconds;
    setCurrentTime(seconds);
  }

  async function handleOverride() {
    if (!scorecard) {
      return;
    }
    setSaving(true);
    setActionError(null);
    try {
      await submitOverride(managerId, scorecard.id, {
        reason_code: mapReasonCode(overrideReason, scorecard.overall_score, overrideScore),
        override_score: overrideScore ? Number(overrideScore) : undefined,
        notes: reviewNotes || undefined
      });
      setOverrideScore("");
      setReviewNotes("");
      await onActionDone();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Unable to save score override");
    } finally {
      setSaving(false);
    }
  }

  async function handleSaveCoachingNote() {
    if (!scorecard || !coachingNote.trim()) {
      return;
    }
    setSaving(true);
    setActionError(null);
    try {
      await createCoachingNote(managerId, scorecard.id, {
        note: coachingNote.trim(),
        visible_to_rep: true,
        weakness_tags: replay?.scorecard?.weakness_tags ?? []
      });
      setCoachingNote("");
      await onActionDone();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Unable to save coaching note");
    } finally {
      setSaving(false);
    }
  }

  async function handleFollowup() {
    if (!scorecard) {
      return;
    }
    if (!followupScenarioId.trim()) {
      setActionError("Scenario ID is required for follow-up assignment.");
      return;
    }
    setSaving(true);
    setActionError(null);
    try {
      await createFollowup(managerId, scorecard.id, followupScenarioId.trim());
      await onActionDone();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "Unable to create follow-up assignment");
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
      <div className="flex flex-col gap-4 border-b border-white/20 pb-6 lg:flex-row lg:items-start lg:justify-between">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-accent/10 flex items-center justify-center">
            <FileText className="w-4.5 h-4.5 text-accent" />
          </div>
          <div>
            <h2 className="text-lg font-semibold tracking-tight text-ink">
              Session {replay.session_id.slice(0, 8)}
            </h2>
            <p className="mt-1 text-sm text-muted">
              {replay.scenario?.name ?? replay.session?.scenario_id ?? "Scenario unavailable"} · {replay.status}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <ScoreChip score={scorecard?.overall_score ?? null} size="lg" />
          <span className="bg-accent/10 text-accent text-xs font-medium rounded-full px-3 py-1">
            {replay.session?.duration_seconds ? formatClock(replay.session.duration_seconds) : "Duration pending"}
          </span>
          {focusTurnId || focusCategory ? (
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-900">
              Focused evidence
            </span>
          ) : null}
        </div>
      </div>

      {focusTurnId || focusCategory ? (
        <div className="rounded-2xl border border-amber-300/35 bg-amber-50/70 px-4 py-3 text-sm text-amber-950">
          {focusCategory ? `Opened from ${focusCategory.replace(/_/g, " ")} evidence.` : "Opened on a linked transcript moment from management analytics."}
        </div>
      ) : null}

      <div className="grid gap-4 md:grid-cols-4">
        {[
          { label: "Audio", value: replay.transport_metrics.audio_duration_ms ? `${Math.round(replay.transport_metrics.audio_duration_ms / 1000)}s` : "--", icon: Volume2 },
          { label: "Turns", value: replay.transport_metrics.turn_count ?? 0, icon: MessageSquare },
          { label: "Barge-ins", value: replay.transport_metrics.barge_in_count ?? 0, icon: Zap },
          { label: "Latency", value: replay.transport_metrics.first_audio_latency_ms ? `${replay.transport_metrics.first_audio_latency_ms}ms` : "--", icon: Clock },
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

      <div className="grid gap-6 xl:grid-cols-[1.3fr_0.9fr]">
        <div className="space-y-6">
          <section className="rounded-2xl border border-white/25 bg-white/35 p-5">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold tracking-tight text-ink">Audio Replay</h3>
                <p className="mt-1 text-sm text-muted">Waveform scrubber stays aligned to the transcript. Click any turn or segment to seek.</p>
              </div>
              <div className="flex flex-wrap gap-2">
                {PLAYBACK_SPEEDS.map((speed) => (
                  <button
                    key={speed}
                    onClick={() => setPlaybackRate(speed)}
                    className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${playbackRate === speed
                      ? "bg-accent text-white"
                      : "border border-white/35 bg-white/55 text-ink hover:bg-white/70"
                      }`}
                  >
                    {speed}x
                  </button>
                ))}
              </div>
            </div>

            {audioUrl ? (
              <>
                <audio ref={audioRef} controls className="mt-4 w-full rounded-2xl" src={audioUrl} preload="metadata" />
                <div className="mt-4 rounded-2xl border border-white/25 bg-white/45 p-4">
                  <div className="mb-3 flex items-center justify-between text-xs font-medium text-muted">
                    <span>{formatClock(currentTime)}</span>
                    <span>{formatClock(totalDuration)}</span>
                  </div>
                  <div className="flex h-20 items-end gap-1 rounded-xl bg-[linear-gradient(180deg,rgba(45,90,61,0.05),rgba(45,90,61,0.12))] p-3">
                    {timelineTurns.map((turn, index) => {
                      const span = Math.max(1.5, ((turn.endOffset - turn.startOffset) / Math.max(totalDuration, 1)) * 100);
                      const active = activeTurnId === turn.turn_id;
                      const baseHeight = 28 + ((turn.text.length + index * 11) % 38);
                      return (
                        <button
                          key={turn.turn_id}
                          onClick={() => seekFromWaveform(turn.startOffset)}
                          className={`rounded-full transition ${active ? "bg-accent" : turn.speaker === "rep" ? "bg-[rgba(45,90,61,0.55)]" : "bg-[rgba(139,105,20,0.55)] hover:bg-[rgba(139,105,20,0.75)]"
                            }`}
                          style={{ width: `${span}%`, height: `${baseHeight}px` }}
                          aria-label={`Seek to turn ${turn.turn_index}`}
                        />
                      );
                    })}
                  </div>
                </div>
              </>
            ) : (
              <div className="mt-4 rounded-2xl border border-dashed border-white/30 bg-white/30 p-6">
                <EmptyState variant="empty" message="No audio artifact is available for this replay yet." />
              </div>
            )}
          </section>

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

          <div className="rounded-2xl border border-white/25 bg-white/35 p-5">
            <div className="flex items-center gap-2 mb-3">
              <Activity className="w-4 h-4 text-muted" />
              <h3 className="text-sm font-semibold tracking-tight text-ink">Critical Moments</h3>
            </div>
            {criticalMoments.length ? (
              <div className="space-y-3">
                {criticalMoments.map((moment) => (
                  <button
                    key={moment.id}
                    onClick={() => {
                      if (moment.categoryKey) {
                        setExpandedCategory(moment.categoryKey);
                      }
                      if (moment.turnId) {
                        seekToTurn(moment.turnId);
                      }
                    }}
                    className={`w-full rounded-2xl border px-4 py-3 text-left transition ${
                      moment.tone === "strong"
                        ? "border-emerald-200 bg-emerald-50/70"
                        : moment.tone === "improve"
                          ? "border-amber-200 bg-amber-50/70"
                          : "border-accent/15 bg-accent-soft/25"
                    }`}
                  >
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">{moment.label}</div>
                    <div className="mt-1 text-sm text-ink">{moment.note}</div>
                  </button>
                ))}
              </div>
            ) : (
              <EmptyState variant="empty" message="No critical moments were extracted for this replay." />
            )}
          </div>

          <div className="rounded-2xl border border-white/25 bg-white/35 p-5">
            <div className="flex items-center gap-2 mb-3">
              <Clock className="w-4 h-4 text-muted" />
              <h3 className="text-sm font-semibold tracking-tight text-ink">Stage Timeline</h3>
            </div>
            <div className="relative ml-3">
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

        <div className="space-y-6">
          <section className="rounded-2xl border border-white/25 bg-white/35 p-5">
            <div className="flex items-center gap-2 mb-4">
              <Target className="w-4 h-4 text-accent" />
              <h3 className="text-sm font-semibold tracking-tight text-ink">Score Panel</h3>
            </div>

            {scorecard ? (
              <div className="space-y-4">
                {categories.map((category) => (
                  <div key={category.key} className="rounded-2xl border border-white/25 bg-white/50 p-4">
                    <button
                      onClick={() => setExpandedCategory(expandedCategory === category.key ? null : category.key)}
                      className="flex w-full items-center justify-between gap-3 text-left"
                    >
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-semibold text-ink">{category.label}</span>
                          <span className="rounded-full bg-white/55 px-2 py-0.5 text-[11px] font-medium text-muted">
                            {category.weight}
                          </span>
                        </div>
                        <div className="mt-3 h-2 w-full rounded-full bg-accent-soft">
                          <div
                            className="h-full rounded-full bg-accent transition-all"
                            style={{ width: `${Math.max(0, Math.min(100, category.score * 10))}%` }}
                          />
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="text-base font-bold text-ink">{category.score.toFixed(1)}</div>
                        <div className="text-xs text-muted">
                          {expandedCategory === category.key ? "Hide details" : "Show details"}
                        </div>
                      </div>
                    </button>
                    {expandedCategory === category.key ? (
                      <div className="mt-4 space-y-3 border-t border-white/25 pt-4">
                        <p className="text-sm leading-6 text-muted">
                          {category.rationale || scorecard.ai_summary}
                        </p>
                        <div className="rounded-2xl border border-white/25 bg-white/60 px-4 py-3">
                          <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">Evidence quote</div>
                          <p className="mt-1 text-sm text-ink">{category.evidenceQuote || "No evidence quote attached to this category."}</p>
                        </div>
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState variant="empty" message="This session has not been graded yet." />
            )}
          </section>

          <section className="rounded-2xl border border-white/25 bg-white/35 p-5 space-y-4">
            <div className="flex items-center gap-2">
              <Save className="w-4 h-4 text-accent" />
              <h3 className="text-sm font-semibold tracking-tight text-ink">Manager Actions</h3>
            </div>

            <div className="space-y-3">
              <label className="block">
                <span className="mb-1.5 block text-xs font-medium text-muted">Override reason</span>
                <select
                  value={overrideReason}
                  onChange={(event) => setOverrideReason(event.target.value as UiReasonCode)}
                  className="w-full rounded-xl border border-white/30 bg-white/50 px-3 py-2.5 text-sm text-ink outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
                >
                  <option value="grading_error">Grading Error</option>
                  <option value="extenuating_circumstance">Extenuating Circumstance</option>
                  <option value="calibration_correction">Calibration Correction</option>
                </select>
              </label>

              <label className="block">
                <span className="mb-1.5 block text-xs font-medium text-muted">Override score</span>
                <input
                  value={overrideScore}
                  onChange={(event) => setOverrideScore(event.target.value)}
                  placeholder={scorecard ? scorecard.overall_score.toFixed(1) : "8.5"}
                  className="w-full rounded-xl border border-white/30 bg-white/50 px-3 py-2.5 text-sm text-ink placeholder:text-muted/50 outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
                />
              </label>

              <label className="block">
                <span className="mb-1.5 block text-xs font-medium text-muted">Review notes</span>
                <textarea
                  value={reviewNotes}
                  onChange={(event) => setReviewNotes(event.target.value)}
                  rows={3}
                  placeholder="Document why you changed the score."
                  className="w-full rounded-xl border border-white/30 bg-white/50 px-3 py-2.5 text-sm text-ink placeholder:text-muted/50 outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20 resize-none"
                />
              </label>

              <button
                onClick={handleOverride}
                disabled={saving || !scorecard}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-accent px-4 py-3 text-sm font-semibold text-white transition hover:bg-accent-hover disabled:opacity-50"
              >
                <Save className="w-3.5 h-3.5" />
                Save Override
              </button>
            </div>

            <div className="border-t border-white/25 pt-4">
              <label className="block">
                <span className="mb-1.5 block text-xs font-medium text-muted">Coaching note</span>
                <textarea
                  value={coachingNote}
                  onChange={(event) => setCoachingNote(event.target.value)}
                  rows={3}
                  placeholder="This note is attached to the rep-facing scorecard."
                  className="w-full rounded-xl border border-white/30 bg-white/50 px-3 py-2.5 text-sm text-ink placeholder:text-muted/50 outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20 resize-none"
                />
              </label>
              <button
                onClick={handleSaveCoachingNote}
                disabled={saving || !scorecard || !coachingNote.trim()}
                className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-xl border border-white/35 bg-white/65 px-4 py-3 text-sm font-semibold text-ink transition hover:bg-white/80 disabled:opacity-50"
              >
                <MessageSquare className="w-3.5 h-3.5" />
                Add Coaching Note
              </button>
            </div>

            <div className="border-t border-white/25 pt-4 space-y-3">
              <div className="flex flex-wrap gap-2">
                {(scorecard?.weakness_tags ?? []).map((tag) => (
                  <span key={tag} className="rounded-full bg-accent-soft px-3 py-1 text-xs font-semibold text-accent">
                    {tag}
                  </span>
                ))}
                {!scorecard?.weakness_tags?.length ? (
                  <span className="text-sm text-muted">No weakness tags are attached to this session.</span>
                ) : null}
              </div>
              <label className="block">
                <span className="mb-1.5 block text-xs font-medium text-muted">Follow-up scenario ID</span>
                <input
                  value={followupScenarioId}
                  onChange={(event) => setFollowupScenarioId(event.target.value)}
                  placeholder="scenario_..."
                  className="w-full rounded-xl border border-white/30 bg-white/50 px-3 py-2.5 text-sm text-ink placeholder:text-muted/50 outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20"
                />
              </label>
              <button
                onClick={handleFollowup}
                disabled={saving || !scorecard}
                className="inline-flex w-full items-center justify-center gap-2 rounded-xl border border-white/35 bg-white/65 px-4 py-3 text-sm font-semibold text-ink transition hover:bg-white/80 disabled:opacity-50"
              >
                <Send className="w-3.5 h-3.5" />
                Assign Follow-Up ({topWeakness ?? "next drill"})
              </button>
            </div>

            {actionError ? (
              <div className="flex items-start gap-2 rounded-2xl border border-error/15 bg-error/[0.06] px-4 py-3 text-sm text-error">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{actionError}</span>
              </div>
            ) : null}
          </section>

          <section className="rounded-2xl border border-white/25 bg-white/35 p-5 space-y-4">
            <div className="flex items-center gap-2">
              <MessageSquare className="w-4 h-4 text-accent" />
              <h3 className="text-sm font-semibold tracking-tight text-ink">Review History</h3>
            </div>
            {replay.manager_reviews?.length ? (
              replay.manager_reviews.map((review) => (
                <div key={review.id} className="rounded-2xl border border-white/25 bg-white/50 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <span className="rounded-full bg-white/60 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                      {review.reason_code.replace(/_/g, " ")}
                    </span>
                    <span className="text-xs text-muted">{new Date(review.reviewed_at).toLocaleString()}</span>
                  </div>
                  {typeof review.override_score === "number" ? (
                    <div className="mt-3 text-sm font-semibold text-ink">Override score: {review.override_score.toFixed(1)}</div>
                  ) : null}
                  <p className="mt-2 text-sm leading-6 text-ink">{review.notes ?? "No review note recorded."}</p>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted">No manager reviews have been recorded yet.</p>
            )}
          </section>

          <section className="rounded-2xl border border-white/25 bg-white/35 p-5 space-y-4">
            <div className="flex items-center gap-2">
              <Save className="w-4 h-4 text-accent" />
              <h3 className="text-sm font-semibold tracking-tight text-ink">Coaching Notes</h3>
            </div>
            {replay.coaching_notes?.length ? (
              replay.coaching_notes.map((note) => (
                <div key={note.id} className="rounded-2xl border border-white/25 bg-white/50 p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div className="flex flex-wrap gap-2">
                      {note.weakness_tags.map((tag) => (
                        <span key={tag} className="rounded-full bg-accent-soft px-2.5 py-1 text-[11px] font-semibold text-accent">
                          {tag}
                        </span>
                      ))}
                    </div>
                    <span className="text-xs text-muted">{new Date(note.created_at).toLocaleString()}</span>
                  </div>
                  <p className="mt-3 text-sm leading-6 text-ink">{note.note}</p>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted">No coaching notes have been attached yet.</p>
            )}
          </section>
        </div>
      </div>

      <div className="rounded-2xl border border-white/25 bg-white/35 p-5">
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

      <div className="rounded-2xl border border-white/25 bg-white/35 p-5">
        <div className="flex items-center gap-2 mb-4">
          <MessageSquare className="w-4 h-4 text-muted" />
          <h3 className="text-sm font-semibold tracking-tight text-ink">Transcript</h3>
        </div>
        <ul className="space-y-3">
          {timelineTurns.map((turn) => {
            const isRep = turn.speaker === "rep";
            const active = activeTurnId === turn.turn_id;
            const strong = highlightMap.strong.has(turn.turn_id);
            const improve = highlightMap.improve.has(turn.turn_id);
            return (
              <li key={turn.turn_id}>
                <button
                  ref={(node) => {
                    turnRefs.current[turn.turn_id] = node;
                  }}
                  onClick={() => seekToTurn(turn.turn_id)}
                  className={`w-full rounded-2xl border px-4 py-4 text-left transition ${active
                    ? "border-accent/40 bg-accent-soft/35 shadow-md shadow-accent/10"
                    : isRep
                      ? "border-accent/12 bg-white/55 hover:bg-white/70"
                      : "border-amber-300/20 bg-amber-50/60 hover:bg-amber-50/75"
                    }`}
                >
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`text-xs font-semibold uppercase tracking-wide ${isRep ? "text-accent" : "text-amber-700"}`}
                      >
                        {turn.speaker}
                      </span>
                      <span className="rounded-full bg-white/60 px-2 py-0.5 text-[11px] font-medium text-muted">
                        {turn.stage}
                      </span>
                      {strong ? (
                        <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[11px] font-semibold text-emerald-800">
                          Strong
                        </span>
                      ) : null}
                      {improve ? (
                        <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                          Improve
                        </span>
                      ) : null}
                      {interruptedTurnIds.has(turn.turn_id) ? (
                        <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-700">
                          <Zap className="h-3 w-3" />
                          Barge-in
                        </span>
                      ) : null}
                      {evidenceTurnIds.has(turn.turn_id) ? (
                        <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-semibold text-accent">
                          Evidence
                        </span>
                      ) : null}
                    </div>
                    <span className="text-[11px] text-muted">{formatClock(turn.startOffset)}</span>
                  </div>
                  <p className="text-sm leading-6 text-ink">{turn.text}</p>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </motion.div>
  );
}
