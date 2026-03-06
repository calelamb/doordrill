import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { motion } from "framer-motion";
import { AlertCircle, ArrowLeft, Radio, RefreshCcw } from "lucide-react";

import { EmptyState } from "../components/shared/EmptyState";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { fetchLiveTranscript } from "../lib/api";
import type { LiveTranscriptResponse } from "../lib/types";

const STAGE_ORDER = [
  { key: "opening", label: "Open" },
  { key: "pitch", label: "Pitch" },
  { key: "objection_handling", label: "Obj" },
  { key: "closing", label: "Close" },
  { key: "done", label: "Done" },
] as const;

function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}:${String(remainingSeconds).padStart(2, "0")}`;
}

function formatStageLabel(stage: string | null | undefined): string {
  if (!stage) {
    return "Waiting for first turn";
  }
  return stage
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function LiveSessionPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";

  const [transcript, setTranscript] = useState<LiveTranscriptResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestIdRef = useRef(0);
  const transcriptEndRef = useRef<HTMLDivElement | null>(null);

  const loadTranscript = useCallback(async (silent = false) => {
    if (!managerId || !id) {
      return;
    }

    const requestId = ++requestIdRef.current;
    if (silent) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);

    try {
      const response = await fetchLiveTranscript(managerId, id);
      if (requestIdRef.current !== requestId) {
        return;
      }
      setTranscript(response);
    } catch (err) {
      if (isAuthError(err)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      if (requestIdRef.current !== requestId) {
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load live transcript");
    } finally {
      if (requestIdRef.current === requestId) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [id, managerId, navigate]);

  useEffect(() => {
    void loadTranscript();
  }, [loadTranscript]);

  useEffect(() => {
    if (!transcript || transcript.status !== "active") {
      return;
    }

    const intervalId = window.setInterval(() => {
      void loadTranscript(true);
    }, 3_000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [loadTranscript, transcript]);

  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [transcript?.turns.length]);

  const activeStageKey = useMemo(() => {
    if (!transcript) {
      return null;
    }
    if (transcript.status !== "active") {
      return "done";
    }
    return STAGE_ORDER.some((stage) => stage.key === transcript.stage) ? transcript.stage : null;
  }, [transcript]);

  const activeStageIndex = activeStageKey
    ? STAGE_ORDER.findIndex((stage) => stage.key === activeStageKey)
    : -1;
  const scenarioDifficulty = transcript?.scenario?.difficulty ?? 0;

  const lastTurn = transcript?.turns[transcript.turns.length - 1] ?? null;
  const aiResponding = transcript?.status === "active" && lastTurn?.speaker === "rep";

  if (loading && !transcript) {
    return (
      <main className="mx-auto max-w-7xl px-6 py-6">
        <div className="rounded-3xl border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <div className="h-4 w-28 animate-pulse rounded-full bg-white/45" />
          <div className="mt-4 h-10 w-2/3 animate-pulse rounded-full bg-white/35" />
          <div className="mt-6 h-72 animate-pulse rounded-3xl bg-white/30" />
        </div>
      </main>
    );
  }

  return (
    <motion.main
      className="mx-auto max-w-7xl px-6 py-6"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
    >
      <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Link to="/manager/feed" className="mb-2 inline-flex items-center gap-2 text-sm text-muted transition hover:text-ink">
            <ArrowLeft className="h-4 w-4" />
            Back to Feed
          </Link>
          <div className="flex flex-wrap items-center gap-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-red-200 bg-red-50/80 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-red-700">
              <Radio className="h-3.5 w-3.5 animate-pulse" />
              Live
            </div>
            <h1 className="text-3xl font-bold tracking-tight text-ink">
              {transcript?.rep.name ?? "Live Session"}
              {transcript?.scenario ? ` — ${transcript.scenario.name}` : ""}
            </h1>
          </div>
          <p className="mt-2 text-sm text-muted">
            Elapsed: <span className="font-semibold text-ink">{formatElapsed(transcript?.elapsed_seconds ?? 0)}</span>
            {"  "}Stage: <span className="font-semibold text-ink">{formatStageLabel(transcript?.stage)}</span>
            {transcript?.scenario ? (
              <>
                  {"  "}Diff:
                <span className="ml-2 inline-flex items-center gap-1" aria-label={`Difficulty ${scenarioDifficulty}`}>
                  {Array.from({ length: 5 }, (_, index) => (
                    <span
                      key={index}
                      className={`h-2.5 w-2.5 rounded-full ${index < scenarioDifficulty ? "bg-accent" : "bg-accent-soft/70"}`}
                    />
                  ))}
                </span>
              </>
            ) : null}
          </p>
        </div>
        <button
          onClick={() => void loadTranscript(true)}
          disabled={refreshing}
          aria-label="Refresh live transcript"
          className="inline-flex items-center gap-2 rounded-xl border border-white/35 bg-white/55 px-4 py-2.5 text-sm font-medium text-ink transition hover:bg-white/70 disabled:opacity-60"
        >
          <RefreshCcw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
          {refreshing ? "Refreshing..." : "Refresh"}
        </button>
      </header>

      {error ? (
        <div className="mb-6 rounded-3xl border border-error/15 bg-error/[0.06] px-6 py-10">
          <EmptyState variant="error" message={error} onRetry={() => void loadTranscript()} />
        </div>
      ) : null}

      {!error && !transcript ? (
        <div className="rounded-3xl border border-white/30 bg-white/40 px-6 py-10 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <EmptyState variant="empty" message="No live session data found for this session." />
        </div>
      ) : null}

      {transcript ? (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.6fr)_minmax(320px,0.9fr)]">
          <section className="rounded-3xl border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl">
            <div className="mb-4 flex items-center justify-between gap-3 border-b border-white/30 pb-4">
              <div>
                <h2 className="text-lg font-bold tracking-tight text-ink">Live Transcript</h2>
                <p className="mt-1 text-sm text-muted">Streaming partial transcript with automatic scroll.</p>
              </div>
              <span className="text-xs font-medium text-muted">auto-scroll</span>
            </div>

            <div className="thin-scrollbar max-h-[62vh] space-y-3 overflow-y-auto pr-2">
              {transcript.turns.map((turn) => {
                const isRep = turn.speaker === "rep";
                return (
                  <div key={turn.turn_id} className={`flex ${isRep ? "justify-end" : "justify-start"}`}>
                    <div
                      className={`max-w-[82%] rounded-3xl px-4 py-3 shadow-sm ${isRep
                        ? "bg-accent/12 text-ink"
                        : "border border-white/30 bg-white/40 backdrop-blur-2xl text-ink"
                        }`}
                    >
                      <div className="mb-1 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                        <span>{isRep ? "Rep" : "AI"}</span>
                        <span>Turn {turn.turn_index + 1}</span>
                        <span>{formatStageLabel(turn.stage)}</span>
                      </div>
                      <p className="m-0 whitespace-pre-wrap text-sm leading-6">{turn.text}</p>
                    </div>
                  </div>
                );
              })}

              {aiResponding ? (
                <div className="flex justify-start">
                  <div className="inline-flex items-center gap-2 rounded-3xl border border-white/30 bg-white/40 px-4 py-3 text-sm text-muted backdrop-blur-2xl">
                    <span>AI is responding...</span>
                    <span className="inline-block h-4 w-1.5 animate-pulse rounded-full bg-accent" aria-hidden="true" />
                  </div>
                </div>
              ) : null}

              {!transcript.turns.length ? (
                <div className="rounded-2xl border border-white/30 bg-white/30 px-4 py-6 text-sm text-muted">
                  Waiting for the first turn to arrive.
                </div>
              ) : null}
              <div ref={transcriptEndRef} />
            </div>
          </section>

          <section className="space-y-6">
            <div className="rounded-3xl border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl">
              <h2 className="text-lg font-bold tracking-tight text-ink">Stage Progress</h2>
              <div className="mt-5 flex items-center gap-2">
                {STAGE_ORDER.map((stage, index) => {
                  const state =
                    activeStageIndex > index ? "complete" : activeStageIndex === index ? "active" : "pending";
                  return (
                    <div key={stage.key} className="flex flex-1 items-center gap-2">
                      <div
                        className={`h-3 w-3 rounded-full ${state === "complete"
                          ? "bg-accent"
                          : state === "active"
                            ? "bg-accent ring-4 ring-accent/15"
                            : "bg-white/70 border border-white/40"
                          }`}
                      />
                      {index < STAGE_ORDER.length - 1 ? (
                        <div className={`h-1 flex-1 rounded-full ${activeStageIndex > index ? "bg-accent" : "bg-white/60"}`} />
                      ) : null}
                    </div>
                  );
                })}
              </div>
              <div className="mt-3 grid grid-cols-5 gap-2 text-center text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                {STAGE_ORDER.map((stage) => (
                  <span key={stage.key}>{stage.label}</span>
                ))}
              </div>
            </div>

            <div className="rounded-3xl border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl">
              <h2 className="text-lg font-bold tracking-tight text-ink">Live Metrics</h2>
              <div className="mt-4 grid gap-3 sm:grid-cols-2">
                <div className="rounded-2xl border border-white/30 bg-white/35 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted">Turns</div>
                  <div className="mt-2 text-2xl font-black tracking-tight text-ink">{transcript.turn_count}</div>
                </div>
                <div className="rounded-2xl border border-white/30 bg-white/35 p-4">
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted">Status</div>
                  <div className="mt-2 text-2xl font-black tracking-tight text-ink">{transcript.status}</div>
                </div>
              </div>
            </div>

            {transcript.status !== "active" ? (
              <div className="rounded-3xl border border-accent/15 bg-accent-soft/35 p-5 shadow-xl shadow-black/5">
                <div className="flex items-start gap-3">
                  <AlertCircle className="mt-0.5 h-5 w-5 text-accent" />
                  <div>
                    <h2 className="text-lg font-bold tracking-tight text-ink">Session Ended</h2>
                    <p className="mt-1 text-sm text-muted">
                      The live drill is no longer active. Open the full replay for scorecard details and manager review actions.
                    </p>
                    <button
                      onClick={() => navigate(`/manager/sessions/${transcript.session_id}/replay`)}
                      aria-label="View full scorecard"
                      className="mt-4 inline-flex items-center rounded-full bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-hover"
                    >
                      View Full Scorecard →
                    </button>
                  </div>
                </div>
              </div>
            ) : null}
          </section>
        </div>
      ) : null}
    </motion.main>
  );
}
