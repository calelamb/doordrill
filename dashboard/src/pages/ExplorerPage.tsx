import { useCallback, useDeferredValue, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { AlertTriangle, Bookmark, BookmarkPlus, Download, Search, Trash2, Zap } from "lucide-react";
import { Virtuoso } from "react-virtuoso";

import { EmptyState } from "../components/shared/EmptyState";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { fetchManagerExplorer } from "../lib/api";
import type { ExplorerResponse } from "../lib/types";

type ReviewedFilter = "all" | "true" | "false";

type SavedView = {
  id: string;
  name: string;
  search: string;
  reviewed: ReviewedFilter;
  bargeInOnly: boolean;
  weaknessFilter: string;
  repFilter: string;
  scenarioFilter: string;
  scoreMin: string;
  scoreMax: string;
};

const SAVED_VIEWS_KEY = "doordrill.management.explorer.saved-views.v1";

function readSavedViews(): SavedView[] {
  if (typeof window === "undefined") {
    return [];
  }
  try {
    const raw = window.localStorage.getItem(SAVED_VIEWS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function persistSavedViews(views: SavedView[]) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(SAVED_VIEWS_KEY, JSON.stringify(views));
}

export function ExplorerPage() {
  const navigate = useNavigate();
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";

  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [reviewed, setReviewed] = useState<ReviewedFilter>("all");
  const [bargeInOnly, setBargeInOnly] = useState(false);
  const [repFilter, setRepFilter] = useState("all");
  const [scenarioFilter, setScenarioFilter] = useState("all");
  const [scoreMin, setScoreMin] = useState("");
  const [scoreMax, setScoreMax] = useState("");
  const [data, setData] = useState<ExplorerResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [weaknessFilter, setWeaknessFilter] = useState("all");
  const [savedViews, setSavedViews] = useState<SavedView[]>(() => readSavedViews());
  const [viewName, setViewName] = useState("");
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

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
        repId: repFilter !== "all" ? repFilter : undefined,
        scenarioId: scenarioFilter !== "all" ? scenarioFilter : undefined,
        reviewed,
        bargeInOnly,
        scoreMin: scoreMin ? Number(scoreMin) : undefined,
        scoreMax: scoreMax ? Number(scoreMax) : undefined,
        search: deferredSearch.trim() || undefined,
        limit: 400,
      });
      setData(response);
      setSelectedSessionId((current) => current ?? response.items[0]?.session_id ?? null);
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
  }, [bargeInOnly, deferredSearch, managerId, navigate, repFilter, reviewed, scenarioFilter, scoreMax, scoreMin]);

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

  const repOptions = useMemo(() => {
    const reps = new Map<string, string>();
    for (const item of data?.items ?? []) {
      reps.set(item.rep_id, item.rep_name);
    }
    return Array.from(reps.entries()).sort((a, b) => a[1].localeCompare(b[1]));
  }, [data?.items]);

  const scenarioOptions = useMemo(() => {
    const scenarios = new Map<string, string>();
    for (const item of data?.items ?? []) {
      scenarios.set(item.scenario_id, item.scenario_name);
    }
    return Array.from(scenarios.entries()).sort((a, b) => a[1].localeCompare(b[1]));
  }, [data?.items]);

  const filteredItems = useMemo(() => {
    const source = data?.items ?? [];
    return source.filter((item) => weaknessFilter === "all" || item.weakness_tags.includes(weaknessFilter));
  }, [data?.items, weaknessFilter]);

  const selectedItem = useMemo(
    () => filteredItems.find((item) => item.session_id === selectedSessionId) ?? filteredItems[0] ?? null,
    [filteredItems, selectedSessionId]
  );

  function saveCurrentView() {
    const name = viewName.trim();
    if (!name) {
      return;
    }
    const next = [
      {
        id: `${Date.now()}`,
        name,
        search,
        reviewed,
        bargeInOnly,
        weaknessFilter,
        repFilter,
        scenarioFilter,
        scoreMin,
        scoreMax,
      },
      ...savedViews,
    ].slice(0, 8);
    setSavedViews(next);
    persistSavedViews(next);
    setViewName("");
  }

  function applySavedView(view: SavedView) {
    setSearch(view.search);
    setReviewed(view.reviewed);
    setBargeInOnly(view.bargeInOnly);
    setWeaknessFilter(view.weaknessFilter);
    setRepFilter(view.repFilter ?? "all");
    setScenarioFilter(view.scenarioFilter ?? "all");
    setScoreMin(view.scoreMin ?? "");
    setScoreMax(view.scoreMax ?? "");
  }

  function deleteSavedView(viewId: string) {
    const next = savedViews.filter((view) => view.id !== viewId);
    setSavedViews(next);
    persistSavedViews(next);
  }

  function exportCsv() {
    if (!filteredItems.length || typeof window === "undefined") {
      return;
    }
    const rows = [
      ["session_id", "rep_name", "scenario_name", "started_at", "overall_score", "reviewed", "barge_in_count", "weakness_tags", "objection_tags"],
      ...filteredItems.map((item) => [
        item.session_id,
        item.rep_name,
        item.scenario_name,
        item.started_at ?? "",
        typeof item.overall_score === "number" ? String(item.overall_score) : "",
        String(item.manager_reviewed),
        String(item.barge_in_count),
        item.weakness_tags.join("|"),
        item.objection_tags.join("|"),
      ]),
    ];
    const csv = rows
      .map((row) => row.map((value) => `"${String(value).replace(/"/g, '""')}"`).join(","))
      .join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = window.URL.createObjectURL(blob);
    const anchor = window.document.createElement("a");
    anchor.href = url;
    anchor.download = "doordrill-session-explorer.csv";
    anchor.click();
    window.URL.revokeObjectURL(url);
  }

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
      <header className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/55 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-muted">
            <Bookmark className="h-3.5 w-3.5 text-accent" />
            High-Density Explorer
          </div>
          <h1 className="mt-4 text-3xl font-black tracking-tight text-ink">Session Explorer</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted">
            Virtualized archive search with persistent saved views, transcript previews, weakness clustering, and replay evidence jumps.
          </p>
        </div>
        <div className="rounded-[24px] border border-white/30 bg-white/45 px-4 py-3 text-right shadow-xl shadow-black/5 backdrop-blur-2xl">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Visible Sessions</div>
          <div className="mt-1 text-2xl font-black tracking-tight text-ink">{filteredItems.length}</div>
        </div>
      </header>

      <section className="rounded-[32px] border border-white/30 bg-[radial-gradient(circle_at_top_left,rgba(45,90,61,0.16),transparent_38%),linear-gradient(180deg,rgba(255,255,255,0.62),rgba(250,246,241,0.52))] p-5 shadow-xl shadow-black/5 backdrop-blur-2xl">
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
            value={repFilter}
            onChange={(event) => setRepFilter(event.target.value)}
            className="rounded-2xl border border-white/35 bg-white/60 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent/50 focus:ring-2 focus:ring-accent/20"
          >
            <option value="all">All reps</option>
            {repOptions.map(([repId, repName]) => (
              <option key={repId} value={repId}>
                {repName}
              </option>
            ))}
          </select>
          <select
            value={scenarioFilter}
            onChange={(event) => setScenarioFilter(event.target.value)}
            className="rounded-2xl border border-white/35 bg-white/60 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent/50 focus:ring-2 focus:ring-accent/20"
          >
            <option value="all">All scenarios</option>
            {scenarioOptions.map(([scenarioId, scenarioName]) => (
              <option key={scenarioId} value={scenarioId}>
                {scenarioName}
              </option>
            ))}
          </select>
          <select
            value={reviewed}
            onChange={(event) => setReviewed(event.target.value as ReviewedFilter)}
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

        <div className="mt-3 grid gap-3 xl:grid-cols-[0.7fr_0.7fr_auto]">
          <input
            type="number"
            inputMode="decimal"
            min="0"
            max="10"
            step="0.1"
            value={scoreMin}
            onChange={(event) => setScoreMin(event.target.value)}
            placeholder="Min score"
            className="rounded-2xl border border-white/35 bg-white/60 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent/50 focus:ring-2 focus:ring-accent/20"
          />
          <input
            type="number"
            inputMode="decimal"
            min="0"
            max="10"
            step="0.1"
            value={scoreMax}
            onChange={(event) => setScoreMax(event.target.value)}
            placeholder="Max score"
            className="rounded-2xl border border-white/35 bg-white/60 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent/50 focus:ring-2 focus:ring-accent/20"
          />
          <button
            onClick={exportCsv}
            className="inline-flex items-center justify-center gap-2 rounded-2xl border border-white/35 bg-white/65 px-4 py-3 text-sm font-semibold text-ink transition hover:bg-white/80"
          >
            <Download className="h-4 w-4" />
            Export CSV
          </button>
        </div>

        <div className="mt-4 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex flex-1 gap-2">
            <input
              value={viewName}
              onChange={(event) => setViewName(event.target.value)}
              placeholder="Save current filter set"
              className="w-full rounded-2xl border border-white/35 bg-white/60 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent/50 focus:ring-2 focus:ring-accent/20"
            />
            <button
              onClick={saveCurrentView}
              className="inline-flex items-center gap-2 rounded-2xl bg-ink px-4 py-3 text-sm font-semibold text-white transition hover:bg-ink/90"
            >
              <BookmarkPlus className="h-4 w-4" />
              Save View
            </button>
          </div>
          <div className="flex flex-wrap gap-2">
            {savedViews.map((view) => (
              <div key={view.id} className="inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/60 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[0.16em] text-ink">
                <button onClick={() => applySavedView(view)} className="transition hover:text-accent">
                  {view.name}
                </button>
                <button onClick={() => deleteSavedView(view.id)} className="text-muted transition hover:text-error" aria-label={`Delete ${view.name}`}>
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </section>

      {!filteredItems.length ? (
        <EmptyState variant="empty" message="No sessions match the current explorer filters." />
      ) : (
        <section className="grid gap-6 xl:grid-cols-[1.2fr_0.8fr]">
          <div className="rounded-[32px] border border-white/30 bg-white/40 p-3 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <div className="mb-3 flex items-center justify-between px-3 pt-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
            <span>Virtualized Replay Archive</span>
            <span>{filteredItems.length} rows</span>
          </div>
          <Virtuoso
            style={{ height: 620 }}
            totalCount={filteredItems.length}
            itemContent={(index) => {
              const item = filteredItems[index];
              return (
                <div className="pb-3">
                  <button
                    key={item.session_id}
                    onClick={() => setSelectedSessionId(item.session_id)}
                    className={`w-full rounded-[26px] border p-5 text-left shadow-lg shadow-black/5 transition hover:bg-white/80 ${
                      selectedItem?.session_id === item.session_id
                        ? "border-accent/40 bg-[linear-gradient(135deg,rgba(239,245,240,0.9),rgba(244,239,231,0.6))]"
                        : "border-white/30 bg-[linear-gradient(135deg,rgba(255,255,255,0.72),rgba(244,239,231,0.5))]"
                    }`}
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

                      <div className="grid gap-3 text-sm sm:grid-cols-5 xl:min-w-[500px]">
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
                    <div className="mt-4 flex items-center justify-end">
                      <span className="rounded-full border border-white/35 bg-white/70 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink">
                        Preview
                      </span>
                    </div>
                  </button>
                </div>
              );
            }}
          />
          </div>

          <div className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Quick Preview</div>
                <h2 className="mt-2 text-lg font-bold tracking-tight text-ink">
                  {selectedItem?.rep_name ?? "Select a session"}
                </h2>
                <p className="mt-1 text-sm text-muted">{selectedItem?.scenario_name ?? "Replay-linked transcript preview"}</p>
              </div>
              {selectedItem ? (
                <button
                  onClick={() => openReplay(selectedItem.session_id, selectedItem.focus_turn_id)}
                  className="rounded-full border border-white/35 bg-white/70 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-ink transition hover:bg-white/85"
                >
                  Open Replay
                </button>
              ) : null}
            </div>

            {selectedItem ? (
              <div className="mt-5 space-y-4">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="rounded-2xl border border-white/25 bg-white/45 p-4">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Score</div>
                    <div className="mt-2 text-2xl font-black tracking-tight text-ink">
                      {typeof selectedItem.overall_score === "number" ? selectedItem.overall_score.toFixed(1) : "--"}
                    </div>
                  </div>
                  <div className="rounded-2xl border border-white/25 bg-white/45 p-4">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Status</div>
                    <div className="mt-2 text-sm font-semibold text-ink">
                      {selectedItem.manager_reviewed ? "Reviewed" : "Needs review"} · {selectedItem.assignment_status}
                    </div>
                  </div>
                </div>

                <div className="rounded-2xl border border-white/25 bg-white/45 p-4">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Transcript Preview</div>
                  <p className="mt-3 text-sm leading-7 text-ink">
                    {selectedItem.transcript_preview || "No transcript preview available."}
                  </p>
                </div>

                <div className="rounded-2xl border border-white/25 bg-white/45 p-4">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Evidence Tags</div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    {selectedItem.weakness_tags.map((tag) => (
                      <span key={tag} className="rounded-full bg-accent-soft px-2.5 py-1 text-[11px] font-medium text-accent">
                        {tag}
                      </span>
                    ))}
                    {selectedItem.objection_tags.map((tag) => (
                      <span key={tag} className="rounded-full bg-amber-100 px-2.5 py-1 text-[11px] font-medium text-amber-900">
                        {tag}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="rounded-2xl border border-white/25 bg-white/45 p-4">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Manager Note</div>
                  <div className="mt-3 text-sm leading-7 text-ink">
                    {selectedItem.latest_coaching_note_preview ?? "No coaching note attached yet."}
                  </div>
                </div>
              </div>
            ) : (
              <EmptyState variant="empty" message="Choose a session to inspect the transcript and evidence preview." />
            )}
          </div>
        </section>
      )}
    </motion.main>
  );
}
