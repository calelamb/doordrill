import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Check, ClipboardList, Copy, RefreshCcw, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { ChartSkeleton } from "./shared/ChartSkeleton";
import { EmptyState } from "./shared/EmptyState";
import { clearStoredAuth, isAuthError } from "../lib/auth";
import { fetchOneOnOnePrep } from "../lib/api";
import type { OneOnOnePrepResponse } from "../lib/types";

type OneOnOnePrepCardProps = {
  open: boolean;
  onClose: () => void;
  managerId: string;
  repId: string;
  repName: string;
  periodDays?: number;
};

function OneOnOnePrepSkeleton() {
  return (
    <div className="space-y-4">
      <ChartSkeleton heightClass="h-6" className="max-w-[200px]" />
      <ChartSkeleton heightClass="h-24" className="rounded-[28px]" />
      <ChartSkeleton heightClass="h-32" className="rounded-[28px]" />
      <ChartSkeleton heightClass="h-32" className="rounded-[28px]" />
      <ChartSkeleton heightClass="h-24" className="rounded-[28px]" />
    </div>
  );
}

function isEmptyDataError(error: string | null) {
  if (!error) {
    return false;
  }
  return error.toLowerCase().includes("no scored sessions") || error.toLowerCase().includes("no data");
}

export function OneOnOnePrepCard({
  open,
  onClose,
  managerId,
  repId,
  repName,
  periodDays = 14,
}: OneOnOnePrepCardProps) {
  const navigate = useNavigate();
  const [data, setData] = useState<OneOnOnePrepResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const requestRef = useRef(0);

  const loadData = useCallback(async () => {
    if (!open || !managerId || !repId) {
      return;
    }
    const requestId = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const response = await fetchOneOnOnePrep(managerId, repId, periodDays);
      if (requestRef.current !== requestId) {
        return;
      }
      setData(response);
    } catch (loadError) {
      if (isAuthError(loadError)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      if (requestRef.current !== requestId) {
        return;
      }
      setData(null);
      setError(loadError instanceof Error ? loadError.message : "Failed to load 1:1 prep.");
    } finally {
      if (requestRef.current === requestId) {
        setLoading(false);
      }
    }
  }, [managerId, navigate, open, periodDays, repId]);

  useEffect(() => {
    if (!open) {
      return;
    }
    void loadData();
  }, [loadData, open]);

  useEffect(() => {
    if (!copied) {
      return;
    }
    const timer = window.setTimeout(() => setCopied(false), 1400);
    return () => window.clearTimeout(timer);
  }, [copied]);

  const copyText = useMemo(() => {
    if (!data) {
      return "";
    }
    const topics = data.discussion_topics
      .map(
        (topic, index) =>
          `${index + 1}. ${topic.topic}\nEvidence: ${topic.evidence}\nOpener: ${topic.suggested_opener}`
      )
      .join("\n\n");
    return [
      `${data.rep_name} 1:1 Prep`,
      `Window: last ${data.period_days} days`,
      "",
      `Readiness summary: ${data.readiness_summary}`,
      "",
      "Discussion topics:",
      topics,
      "",
      `Strength to acknowledge: ${data.strength_to_acknowledge.skill}`,
      data.strength_to_acknowledge.what_to_say,
      "",
      `Pattern to challenge: ${data.pattern_to_challenge.skill}`,
      data.pattern_to_challenge.pattern,
      data.pattern_to_challenge.what_to_say,
      "",
      `Suggested next scenario: ${data.suggested_next_scenario.scenario_type} (difficulty ${data.suggested_next_scenario.difficulty})`,
      data.suggested_next_scenario.rationale,
    ].join("\n");
  }, [data]);

  const handleCopy = useCallback(async () => {
    if (!copyText || !navigator.clipboard?.writeText) {
      return;
    }
    try {
      await navigator.clipboard.writeText(copyText);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }, [copyText]);

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-50"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.button
            type="button"
            aria-label="Close one on one prep panel"
            className="absolute inset-0 bg-ink/20 backdrop-blur-sm"
            onClick={onClose}
          />

          <motion.aside
            className="absolute right-0 top-0 flex h-full w-full max-w-2xl flex-col border-l border-white/30 bg-background/95 p-6 shadow-2xl"
            initial={{ x: 48, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: 48, opacity: 0 }}
            transition={{ type: "spring", stiffness: 220, damping: 26 }}
          >
            <div className="flex items-start justify-between gap-4 border-b border-white/30 pb-5">
              <div>
                <div className="flex items-center gap-2 text-sm font-semibold text-accent">
                  <ClipboardList className="h-4 w-4" />
                  Prep for 1:1
                </div>
                <h2 className="mt-2 text-2xl font-black tracking-tight text-ink">{repName}</h2>
                <p className="mt-2 text-sm text-muted">Structured talking points for the last {periodDays} days.</p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  aria-label="Refresh one on one prep"
                  onClick={() => void loadData()}
                  disabled={loading}
                  className="rounded-full border border-white/35 bg-white/60 p-2 text-muted transition hover:bg-white hover:text-ink"
                >
                  <RefreshCcw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
                </button>
                <button
                  type="button"
                  aria-label="Close one on one prep panel"
                  onClick={onClose}
                  className="rounded-full border border-white/35 bg-white/60 p-2 text-muted transition hover:bg-white hover:text-ink"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div className="thin-scrollbar mt-6 flex-1 overflow-y-auto pr-1">
              {loading ? <OneOnOnePrepSkeleton /> : null}

              {!loading && error && isEmptyDataError(error) ? (
                <EmptyState variant="empty" message="No 1:1 prep is available yet for this rep." />
              ) : null}

              {!loading && error && !isEmptyDataError(error) ? (
                <div className="rounded-[28px] border border-red-200 bg-red-50/80 p-5 text-sm text-red-700">{error}</div>
              ) : null}

              {!loading && !error && data ? (
                <div className="space-y-5">
                  <div className="rounded-[30px] border border-white/35 bg-white/60 p-5 backdrop-blur-2xl">
                    <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
                      <div>
                        <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Readiness Summary</div>
                        <p className="mt-3 text-lg font-semibold leading-7 text-ink">{data.readiness_summary}</p>
                      </div>
                      <button
                        type="button"
                        aria-label="Copy one on one prep to clipboard"
                        onClick={() => void handleCopy()}
                        className="inline-flex shrink-0 items-center gap-2 rounded-xl border border-white/35 bg-white/80 px-4 py-2 text-sm font-semibold text-ink transition hover:bg-white"
                      >
                        {copied ? <Check className="h-4 w-4 text-accent" /> : <Copy className="h-4 w-4" />}
                        {copied ? "Copied" : "Copy notes"}
                      </button>
                    </div>
                  </div>

                  <section className="space-y-3">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Discussion Topics</div>
                    {data.discussion_topics.length ? (
                      data.discussion_topics.map((topic, index) => (
                        <div key={`${topic.topic}-${index}`} className="rounded-[28px] border border-white/35 bg-white/55 p-5 backdrop-blur-2xl">
                          <div className="flex items-start gap-4">
                            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl bg-accent/10 text-sm font-black text-accent">
                              {index + 1}
                            </div>
                            <div className="space-y-3">
                              <h3 className="text-lg font-bold tracking-tight text-ink">{topic.topic}</h3>
                              <p className="text-sm leading-6 text-ink">{topic.evidence}</p>
                              <div className="rounded-2xl border border-accent/15 bg-accent-soft/55 px-4 py-3">
                                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-accent">Suggested Opener</div>
                                <p className="mt-2 text-sm leading-6 text-ink">{topic.suggested_opener}</p>
                              </div>
                            </div>
                          </div>
                        </div>
                      ))
                    ) : (
                      <EmptyState variant="empty" message="No discussion topics were generated for this prep yet." />
                    )}
                  </section>

                  <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
                    <div className="rounded-[28px] border border-white/35 bg-white/55 p-5 backdrop-blur-2xl">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Strength to Acknowledge</div>
                      <h3 className="mt-3 text-lg font-bold tracking-tight text-ink">{data.strength_to_acknowledge.skill}</h3>
                      <p className="mt-3 text-sm leading-6 text-ink">{data.strength_to_acknowledge.what_to_say}</p>
                    </div>

                    <div className="rounded-[28px] border border-white/35 bg-white/55 p-5 backdrop-blur-2xl">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Pattern to Challenge</div>
                      <h3 className="mt-3 text-lg font-bold tracking-tight text-ink">{data.pattern_to_challenge.skill}</h3>
                      <p className="mt-3 text-sm leading-6 text-ink">{data.pattern_to_challenge.pattern}</p>
                      <p className="mt-3 rounded-2xl border border-white/35 bg-white/60 px-4 py-3 text-sm leading-6 text-ink">
                        {data.pattern_to_challenge.what_to_say}
                      </p>
                    </div>
                  </div>

                  <div className="rounded-[28px] border border-white/35 bg-white/55 p-5 backdrop-blur-2xl">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Suggested Next Scenario</div>
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                      <h3 className="text-lg font-bold tracking-tight text-ink">{data.suggested_next_scenario.scenario_type}</h3>
                      <span className="rounded-full border border-accent/20 bg-accent-soft/60 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-accent">
                        Difficulty {data.suggested_next_scenario.difficulty}
                      </span>
                    </div>
                    <p className="mt-3 text-sm leading-6 text-ink">{data.suggested_next_scenario.rationale}</p>
                  </div>
                </div>
              ) : null}

              {!loading && !error && !data ? (
                <EmptyState variant="empty" message="No 1:1 prep is available yet for this rep." />
              ) : null}
            </div>
          </motion.aside>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
