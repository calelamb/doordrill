import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, CalendarDays, CheckCircle2, CheckSquare, Clock3, Flag, Users } from "lucide-react";

import { getValidStoredAuth } from "../lib/auth";
import { fetchManagerSessionDetail, submitOverride } from "../lib/api";
import type { FeedItem } from "../lib/types";
import { EmptyState } from "./shared/EmptyState";
import { ScoreChip } from "./shared/ScoreChip";

type Props = {
  items: FeedItem[];
  activeSessionId: string | null;
  onSelect: (sessionId: string) => void;
};

export function FeedList({ items, activeSessionId, onSelect }: Props) {
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [marking, setMarking] = useState(false);
  const [batchError, setBatchError] = useState<string | null>(null);

  useEffect(() => {
    setSelectedIds((current) => current.filter((id) => items.some((item) => item.session_id === id)));
  }, [items]);

  const selectableItems = useMemo(
    () => items.filter((item) => !item.manager_reviewed && item.overall_score !== null),
    [items]
  );

  const allSelectableSelected = selectableItems.length > 0 && selectableItems.every((item) => selectedIds.includes(item.session_id));

  async function handleBatchReview() {
    if (!managerId) {
      return;
    }
    const targets = items.filter((item) => selectedIds.includes(item.session_id) && !item.manager_reviewed && item.overall_score !== null);
    if (!targets.length) {
      return;
    }

    setMarking(true);
    setBatchError(null);
    try {
      await Promise.all(
        targets.map(async (item) => {
          const detail = await fetchManagerSessionDetail(managerId, item.session_id);
          if (!detail.scorecard?.id) {
            return;
          }
          await submitOverride(managerId, detail.scorecard.id, {
            reason_code: "manager_coaching",
            notes: "Marked reviewed from manager feed."
          });
        })
      );
      setSelectedIds([]);
      window.dispatchEvent(new Event("manager-feed:refresh"));
    } catch (error) {
      setBatchError(error instanceof Error ? error.message : "Failed to mark selected sessions reviewed");
    } finally {
      setMarking(false);
    }
  }

  function formatDuration(durationSeconds?: number | null): string {
    if (!durationSeconds || durationSeconds < 1) {
      return "--";
    }
    const minutes = Math.floor(durationSeconds / 60);
    const seconds = durationSeconds % 60;
    return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }

  function formatDate(dateString?: string | null): string {
    if (!dateString) {
      return "No date";
    }
    return new Date(dateString).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit"
    });
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-[28px] p-6"
    >
      <div className="mb-5 flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-lg font-bold tracking-tight text-ink flex items-center gap-2">
            <Users className="w-5 h-5 text-accent" />
            Session Feed
          </h2>
          <p className="mt-1 text-sm text-muted">{items.length} session{items.length === 1 ? "" : "s"} in the current view.</p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() =>
              setSelectedIds(allSelectableSelected ? [] : selectableItems.map((item) => item.session_id))
            }
            disabled={!selectableItems.length}
            className="inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/55 px-4 py-2 text-sm font-medium text-ink transition hover:bg-white/70 disabled:opacity-50"
          >
            <CheckSquare className="h-4 w-4" />
            {allSelectableSelected ? "Clear" : "Select"} reviewables
          </button>
          <button
            onClick={() => void handleBatchReview()}
            disabled={!selectedIds.length || marking}
            className="inline-flex items-center gap-2 rounded-full bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-hover disabled:opacity-50"
          >
            <CheckCircle2 className="h-4 w-4" />
            {marking ? "Marking..." : `Mark Reviewed (${selectedIds.length})`}
          </button>
        </div>
      </div>

      {batchError ? (
        <div className="mb-4 rounded-2xl border border-error/15 bg-error/[0.06] px-4 py-3 text-sm text-error">
          {batchError}
        </div>
      ) : null}

      {!items.length ? (
        <EmptyState variant="empty" message="No sessions available in the feed." />
      ) : null}

      <ul className="flex flex-col gap-3">
        {items.map((item, index) => {
          const isActive = activeSessionId === item.session_id;
          const isReviewed = item.manager_reviewed;
          const isSelected = selectedIds.includes(item.session_id);
          const isRedFlag = typeof item.overall_score === "number" && item.overall_score < 6.0;

          return (
            <motion.li
              key={item.session_id}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3, delay: index * 0.04 }}
              className="list-none"
            >
              <div
                role="button"
                tabIndex={0}
                className={`w-full text-left rounded-[24px] p-5 transition-all duration-200 hover:scale-[1.01] border cursor-pointer ${
                  isActive
                    ? "ring-2 ring-accent bg-accent-soft/40 border-accent/30 shadow-md shadow-accent/10"
                    : "bg-white/30 backdrop-blur-xl border-white/20 hover:bg-white/55 hover:shadow-md hover:shadow-black/5"
                }`}
                onClick={() => onSelect(item.session_id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    onSelect(item.session_id);
                  }
                }}
              >
                <div className="mb-3 flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={(event) => {
                        event.stopPropagation();
                        setSelectedIds((current) =>
                          current.includes(item.session_id)
                            ? current.filter((id) => id !== item.session_id)
                            : [...current, item.session_id]
                        );
                      }}
                      onClick={(event) => event.stopPropagation()}
                      className="mt-1 h-4 w-4 rounded border-white/40 bg-white/70 text-accent focus:ring-accent"
                    />
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-semibold text-ink">{item.rep_name ?? item.rep_id}</span>
                        <span className="rounded-full border border-white/40 bg-white/50 px-2.5 py-1 text-[11px] font-medium uppercase tracking-wide text-muted">
                          {item.scenario_name ?? item.scenario_id ?? "Unknown scenario"}
                        </span>
                        {isRedFlag ? (
                          <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2.5 py-1 text-[11px] font-semibold text-red-800">
                            <Flag className="h-3 w-3" />
                            Red flag
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-2 line-clamp-2 text-sm text-muted">
                        {item.scenario_description ?? "Open the replay to review transcript evidence and manager coaching options."}
                      </p>
                    </div>
                  </div>
                  <ScoreChip score={item.overall_score} size="md" />
                </div>

                <div className="grid gap-2 text-xs text-muted md:grid-cols-4">
                  <span className="inline-flex items-center gap-2">
                    <CalendarDays className="h-3.5 w-3.5" />
                    {formatDate(item.started_at)}
                  </span>
                  <span className="inline-flex items-center gap-2">
                    <Clock3 className="h-3.5 w-3.5" />
                    {formatDuration(item.duration_seconds)}
                  </span>
                  <span className="font-medium capitalize">{item.session_status.replace(/_/g, " ")}</span>
                  <span className="flex items-center gap-1.5 justify-self-start md:justify-self-end">
                    {isReviewed ? (
                      <>
                        <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-500" />
                        <span className="font-medium text-green-700">Reviewed</span>
                        <CheckCircle2 className="w-3.5 h-3.5 text-green-500" />
                      </>
                    ) : (
                      <>
                        <AlertTriangle className="h-3.5 w-3.5 text-amber-600" />
                        <span className="font-medium text-amber-700">Unreviewed</span>
                      </>
                    )}
                  </span>
                </div>
              </div>
            </motion.li>
          );
        })}
      </ul>
    </motion.div>
  );
}
