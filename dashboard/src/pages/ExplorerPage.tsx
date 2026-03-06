import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Search, Zap } from "lucide-react";

import { EmptyState } from "../components/shared/EmptyState";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { fetchManagerExplorer } from "../lib/api";
import type { ExplorerResponse } from "../lib/types";

export function ExplorerPage() {
  const navigate = useNavigate();
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";

  const [search, setSearch] = useState("");
  const [reviewed, setReviewed] = useState<"all" | "true" | "false">("all");
  const [bargeInOnly, setBargeInOnly] = useState(false);
  const [data, setData] = useState<ExplorerResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function openReplay(sessionId: string, focusTurnId?: string | null) {
    const params = new URLSearchParams();
    if (focusTurnId) params.set("turnId", focusTurnId);
    navigate(`/manager/sessions/${sessionId}/replay${params.toString() ? `?${params.toString()}` : ""}`);
  }

  const loadData = useCallback(async () => {
    if (!managerId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetchManagerExplorer(managerId, {
        period: "90",
        reviewed,
        bargeInOnly,
        search: search.trim() || undefined,
        limit: 200,
      });
      setData(response);
    } catch (err) {
      if (isAuthError(err)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load explorer");
    } finally {
      setLoading(false);
    }
  }, [bargeInOnly, managerId, navigate, reviewed, search]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const weaknessOptions = useMemo(() => {
    const tags = new Set<string>();
    for (const item of data?.items ?? []) {
      for (const tag of item.weakness_tags) tags.add(tag);
    }
    return Array.from(tags).sort();
  }, [data?.items]);

  const [weaknessFilter, setWeaknessFilter] = useState("all");

  const filteredItems = useMemo(() => {
    const source = data?.items ?? [];
    return source.filter((item) => weaknessFilter === "all" || item.weakness_tags.includes(weaknessFilter));
  }, [data?.items, weaknessFilter]);

  if (loading) return <EmptyState variant="loading" message="Loading session explorer..." />;
  if (error) return <EmptyState variant="error" message={error} onRetry={() => void loadData()} />;
  if (!data) return <EmptyState variant="empty" message="No explorer data available." />;

  return (
    <motion.main
      className="mx-auto max-w-7xl px-6 py-6 space-y-6"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
    >
      <header>
        <h1 className="text-3xl font-black tracking-tight text-ink">Session Explorer</h1>
        <p className="mt-1 text-sm text-muted">Search the full session archive by score, review state, weakness tags, objections, and barge-ins.</p>
      </header>

      <section className="rounded-[32px] border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl">
        <div className="grid gap-3 xl:grid-cols-[1.6fr_0.7fr_0.7fr_0.7fr]">
          <label className="relative">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted/60" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search rep, scenario, transcript preview, or weakness tag"
              className="w-full rounded-2xl border border-white/35 bg-white/60 py-3 pl-11 pr-4 text-sm text-ink outline-none transition focus:border-accent/50 focus:ring-2 focus:ring-accent/20"
            />
          </label>
          <select
            value={reviewed}
            onChange={(event) => setReviewed(event.target.value as "all" | "true" | "false")}
            className="rounded-2xl border border-white/35 bg-white/60 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent/50 focus:ring-2 focus:ring-accent/20"
          >
            <option value="all">All review states</option>
            <option value="false">Unreviewed</option>
            <option value="true">Reviewed</option>
          </select>
          <select
            value={weaknessFilter}
            onChange={(event) => setWeaknessFilter(event.target.value)}
            className="rounded-2xl border border-white/35 bg-white/60 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent/50 focus:ring-2 focus:ring-accent/20"
          >
            <option value="all">All weakness tags</option>
            {weaknessOptions.map((tag) => (
              <option key={tag} value={tag}>
                {tag}
              </option>
            ))}
          </select>
          <button
            onClick={() => setBargeInOnly((value) => !value)}
            className={`rounded-2xl border px-4 py-3 text-sm font-semibold transition ${bargeInOnly ? "border-accent bg-accent text-white" : "border-white/35 bg-white/60 text-ink hover:bg-white/75"}`}
          >
            {bargeInOnly ? "Barge-ins only" : "Include all sessions"}
          </button>
        </div>
      </section>

      {!filteredItems.length ? (
        <EmptyState variant="empty" message="No sessions match the current explorer filters." />
      ) : (
        <section className="space-y-3">
          {filteredItems.map((item) => (
            <button
              key={item.session_id}
              onClick={() => openReplay(item.session_id, item.focus_turn_id)}
              className="w-full rounded-[28px] border border-white/30 bg-white/40 p-5 text-left shadow-xl shadow-black/5 backdrop-blur-2xl transition hover:bg-white/55"
            >
              <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-ink">{item.rep_name}</span>
                    <span className="rounded-full border border-white/35 bg-white/65 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
                      {item.scenario_name}
                    </span>
                    {item.barge_in_count > 0 ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-semibold text-amber-900">
                        <Zap className="h-3 w-3" />
                        {item.barge_in_count} barge-in
                      </span>
                    ) : null}
                    {!item.manager_reviewed ? (
                      <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2.5 py-1 text-[11px] font-semibold text-red-800">
                        <AlertTriangle className="h-3 w-3" />
                        Unreviewed
                      </span>
                    ) : null}
                  </div>

                  <p className="mt-3 line-clamp-2 text-sm leading-6 text-ink">{item.transcript_preview || "No transcript preview available."}</p>

                  <div className="mt-3 flex flex-wrap gap-2">
                    {item.weakness_tags.map((tag) => (
                      <span key={tag} className="rounded-full bg-accent-soft px-2.5 py-1 text-[11px] font-medium text-accent">
                        {tag}
                      </span>
                    ))}
                    {item.objection_tags.map((tag) => (
                      <span key={tag} className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-medium text-amber-900">
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="grid gap-3 text-sm sm:grid-cols-5 xl:min-w-[460px]">
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Score</div>
                    <div className="mt-1 text-lg font-black tracking-tight text-ink">{item.overall_score?.toFixed(1) ?? "--"}</div>
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Date</div>
                    <div className="mt-1 text-ink">{item.started_at ? new Date(item.started_at).toLocaleDateString() : "--"}</div>
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Duration</div>
                    <div className="mt-1 text-ink">{item.duration_seconds ? `${Math.round(item.duration_seconds / 60)}m` : "--"}</div>
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Highlights</div>
                    <div className="mt-1 text-ink">{item.highlight_count}</div>
                  </div>
                  <div>
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Coaching</div>
                    <div className="mt-1 line-clamp-2 text-ink">{item.latest_coaching_note_preview ?? "--"}</div>
                  </div>
                </div>
              </div>
            </button>
          ))}
        </section>
      )}
    </motion.main>
  );
}
