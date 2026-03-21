import { useCallback, useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { AlertCircle, CalendarRange, Filter, RefreshCcw, Search, ShieldAlert } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { FeedList } from "../components/FeedList";
import { EmptyState } from "../components/shared/EmptyState";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { dispatchFeedRefresh, FEED_REFRESH_EVENT, LEGACY_FEED_REFRESH_EVENT } from "../lib/feedEvents";
import { fetchLiveSessions, fetchManagerAnalytics, fetchManagerFeed, fetchRepRiskDetail, getManagerLiveSessionsStreamUrl } from "../lib/api";
import type { FeedItem, LiveSessionCard, LiveSessionsResponse, ManagerAnalytics, RepRiskDetail } from "../lib/types";

type ReviewFilter = "all" | "reviewed" | "unreviewed";

function formatElapsed(seconds: number): string {
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}:${String(remainingSeconds).padStart(2, "0")} elapsed`;
}

function formatStageLabel(stage: string | null | undefined): string {
    if (!stage) {
        return "Waiting for first turn";
    }
    return stage
        .split("_")
        .map((chunk) => chunk.charAt(0).toUpperCase() + chunk.slice(1))
        .join(" ");
}

function averageScore(items: FeedItem[]): number | null {
    const scores = items.map((item) => item.overall_score).filter((score): score is number => typeof score === "number");
    if (!scores.length) {
        return null;
    }
    return scores.reduce((sum, score) => sum + score, 0) / scores.length;
}

export function ManagerFeedPage() {
    const navigate = useNavigate();
    const auth = getValidStoredAuth();
    const managerId = auth?.user.id ?? "";

    const [feed, setFeed] = useState<FeedItem[]>([]);
    const [analytics, setAnalytics] = useState<ManagerAnalytics | null>(null);
    const [riskByRepId, setRiskByRepId] = useState<Map<string, RepRiskDetail["risk_level"]>>(new Map());
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [liveSnapshot, setLiveSnapshot] = useState<LiveSessionsResponse | null>(null);
    const [liveLoading, setLiveLoading] = useState(true);
    const [liveError, setLiveError] = useState<string | null>(null);
    const [elapsedNow, setElapsedNow] = useState(() => Date.now());
    const [query, setQuery] = useState("");
    const [repFilter, setRepFilter] = useState("all");
    const [scenarioFilter, setScenarioFilter] = useState("all");
    const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("all");
    const [startDate, setStartDate] = useState("");
    const [endDate, setEndDate] = useState("");

    const updateLiveSnapshot = useCallback((next: LiveSessionsResponse) => {
        setLiveSnapshot((current) => {
            const currentIds = new Set(current?.live_sessions.map((session) => session.session_id) ?? []);
            const nextIds = new Set(next.live_sessions.map((session) => session.session_id));
            const sawEndedSession = currentIds.size > 0 && Array.from(currentIds).some((sessionId) => !nextIds.has(sessionId));
            if (sawEndedSession) {
                dispatchFeedRefresh();
            }
            return next;
        });
        setLiveLoading(false);
        setLiveError(null);
    }, []);

    const loadLiveSessions = useCallback(async () => {
        if (!managerId) {
            setLiveSnapshot(null);
            setLiveLoading(false);
            return;
        }
        try {
            const response = await fetchLiveSessions(managerId);
            updateLiveSnapshot(response);
        } catch (err) {
            if (isAuthError(err)) {
                clearStoredAuth();
                navigate("/login", { replace: true });
                return;
            }
            setLiveError(err instanceof Error ? err.message : "Failed to load live sessions");
            setLiveLoading(false);
        }
    }, [managerId, navigate, updateLiveSnapshot]);

    const loadFeed = useCallback(async (silent = false) => {
        if (!managerId) {
            return;
        }
        if (silent) {
            setRefreshing(true);
        } else {
            setLoading(true);
        }
        setError(null);
        try {
            const [itemsResult, analyticsResult, riskResult] = await Promise.allSettled([
                fetchManagerFeed(managerId),
                fetchManagerAnalytics(managerId),
                fetchRepRiskDetail(managerId),
            ]);

            const authFailure = [itemsResult, analyticsResult, riskResult].find(
                (result) => result.status === "rejected" && isAuthError(result.reason)
            );
            if (authFailure) {
                clearStoredAuth();
                navigate("/login", { replace: true });
                return;
            }

            if (itemsResult.status === "rejected") {
                throw itemsResult.reason;
            }

            if (analyticsResult.status === "rejected") {
                throw analyticsResult.reason;
            }

            setFeed(itemsResult.value);
            setAnalytics(analyticsResult.value);
            setRiskByRepId(
                riskResult.status === "fulfilled"
                    ? new Map(riskResult.value.reps.map((rep) => [rep.rep_id, rep.risk_level]))
                    : new Map()
            );
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load manager feed");
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }, [managerId, navigate]);

    useEffect(() => {
        void loadFeed();
    }, [loadFeed]);

    useEffect(() => {
        void loadLiveSessions();
    }, [loadLiveSessions]);

    useEffect(() => {
        const intervalId = window.setInterval(() => {
            void loadFeed(true);
        }, 60_000);

        const refreshListener = () => {
            void loadFeed(true);
        };
        window.addEventListener(FEED_REFRESH_EVENT, refreshListener);
        window.addEventListener(LEGACY_FEED_REFRESH_EVENT, refreshListener);

        return () => {
            window.clearInterval(intervalId);
            window.removeEventListener(FEED_REFRESH_EVENT, refreshListener);
            window.removeEventListener(LEGACY_FEED_REFRESH_EVENT, refreshListener);
        };
    }, [loadFeed]);

    useEffect(() => {
        const intervalId = window.setInterval(() => {
            setElapsedNow(Date.now());
        }, 1000);
        return () => {
            window.clearInterval(intervalId);
        };
    }, []);

    useEffect(() => {
        if (!managerId) {
            return;
        }

        let isDisposed = false;
        let eventSource: EventSource | null = null;

        try {
            eventSource = new EventSource(getManagerLiveSessionsStreamUrl(managerId));
        } catch (err) {
            setLiveError(err instanceof Error ? err.message : "Failed to connect live monitor");
            return;
        }

        eventSource.onmessage = (event) => {
            if (isDisposed) {
                return;
            }
            try {
                const payload = JSON.parse(event.data) as LiveSessionsResponse;
                updateLiveSnapshot(payload);
            } catch {
                setLiveError("Received an invalid live session update");
            }
        };

        eventSource.onerror = () => {
            if (!isDisposed && eventSource?.readyState === EventSource.CLOSED) {
                setLiveError("Live session stream disconnected");
            }
        };

        return () => {
            isDisposed = true;
            eventSource?.close();
        };
    }, [managerId, updateLiveSnapshot]);

    const repOptions = useMemo(
        () => Array.from(new Set(feed.map((item) => item.rep_name ?? item.rep_id))).sort((a, b) => a.localeCompare(b)),
        [feed]
    );

    const scenarioOptions = useMemo(
        () => Array.from(new Set(feed.map((item) => item.scenario_name ?? item.scenario_id ?? "Unknown scenario"))).sort((a, b) => a.localeCompare(b)),
        [feed]
    );

    const filteredFeed = useMemo(() => {
        return feed.filter((item) => {
            const searchable = `${item.rep_name ?? item.rep_id} ${item.scenario_name ?? item.scenario_id ?? ""} ${item.session_id}`.toLowerCase();
            const matchesQuery = !query.trim() || searchable.includes(query.trim().toLowerCase());
            const matchesRep = repFilter === "all" || (item.rep_name ?? item.rep_id) === repFilter;
            const matchesScenario = scenarioFilter === "all" || (item.scenario_name ?? item.scenario_id ?? "Unknown scenario") === scenarioFilter;
            const matchesReview =
                reviewFilter === "all" ||
                (reviewFilter === "reviewed" ? item.manager_reviewed : !item.manager_reviewed);

            const startedAt = item.started_at ? new Date(item.started_at) : null;
            const matchesStart = !startDate || (startedAt ? startedAt >= new Date(`${startDate}T00:00:00`) : false);
            const matchesEnd = !endDate || (startedAt ? startedAt <= new Date(`${endDate}T23:59:59`) : false);

            return matchesQuery && matchesRep && matchesScenario && matchesReview && matchesStart && matchesEnd;
        });
    }, [endDate, feed, query, repFilter, reviewFilter, scenarioFilter, startDate]);

    const summary = useMemo(() => {
        const redFlags = feed.filter((item) => typeof item.overall_score === "number" && item.overall_score < 6).length;
        const unreviewed = feed.filter((item) => !item.manager_reviewed).length;
        return {
            total: feed.length,
            redFlags,
            unreviewed,
            avgScore: averageScore(feed),
            completionRate: analytics?.completion_rate ?? null,
        };
    }, [analytics, feed]);

    const liveSessions = liveSnapshot?.live_sessions ?? [];
    const liveCheckedAtMs = liveSnapshot?.checked_at ? new Date(liveSnapshot.checked_at).getTime() : elapsedNow;
    const liveSessionCountLabel = `${liveSessions.length} rep${liveSessions.length === 1 ? " is" : "s are"} drilling right now`;

    const displayElapsedSeconds = useCallback((session: LiveSessionCard) => {
        const offsetSeconds = Number.isFinite(liveCheckedAtMs)
            ? Math.max(0, Math.floor((elapsedNow - liveCheckedAtMs) / 1000))
            : 0;
        return session.elapsed_seconds + offsetSeconds;
    }, [elapsedNow, liveCheckedAtMs]);

    if (loading && !feed.length) {
        return (
            <main className="mx-auto max-w-7xl px-6 py-6">
                <EmptyState variant="loading" message="Loading manager feed..." />
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
            <header className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight text-ink">Manager Feed</h1>
                    <p className="mt-1 text-sm text-muted">
                        Review every completed drill, batch mark reviewed items, and jump directly into replay.
                    </p>
                </div>
                <button
                    onClick={() => void loadFeed(true)}
                    disabled={refreshing}
                    className="inline-flex items-center gap-2 rounded-xl border border-white/35 bg-white/55 px-4 py-2.5 text-sm font-medium text-ink transition hover:bg-white/70 disabled:opacity-60"
                >
                    <RefreshCcw className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`} />
                    {refreshing ? "Refreshing..." : "Refresh Feed"}
                </button>
            </header>

            <section className="mb-6 grid gap-4 md:grid-cols-4">
                {[
                    { label: "Sessions", value: summary.total, tone: "text-ink" },
                    { label: "Needs Review", value: summary.unreviewed, tone: summary.unreviewed ? "text-amber-700" : "text-ink" },
                    { label: "Red Flags", value: summary.redFlags, tone: summary.redFlags ? "text-error" : "text-ink" },
                    {
                        label: "Team Average",
                        value: summary.avgScore !== null ? summary.avgScore.toFixed(1) : "--",
                        tone: "text-ink"
                    },
                ].map((card) => (
                    <div key={card.label} className="rounded-3xl border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl">
                        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-muted">{card.label}</div>
                        <div className={`mt-3 text-3xl font-black tracking-tight ${card.tone}`}>{card.value}</div>
                    </div>
                ))}
            </section>

            {liveLoading && !liveSnapshot ? (
                <section className="mb-6 rounded-3xl border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl">
                    <div className="h-4 w-28 animate-pulse rounded-full bg-white/45" />
                    <div className="mt-4 h-12 animate-pulse rounded-2xl bg-white/35" />
                </section>
            ) : null}

            {liveError ? (
                <div className="mb-6 rounded-2xl border border-error/15 bg-error/[0.06] px-5 py-3.5 text-sm text-error">
                    Live monitor unavailable: {liveError}
                </div>
            ) : null}

            {liveSessions.length ? (
                <motion.section
                    className="mb-6 rounded-3xl border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl"
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.25, ease: "easeOut" }}
                >
                    <div className="flex flex-col gap-2 border-b border-white/30 pb-4 sm:flex-row sm:items-center sm:justify-between">
                        <div>
                            <div className="inline-flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-red-700">
                                <span className="animate-pulse text-red-600" aria-hidden="true">●</span>
                                Live Now
                            </div>
                            <p className="mt-2 text-lg font-semibold text-ink">{liveSessionCountLabel}</p>
                        </div>
                        <span className="text-xs text-muted">
                            Snapshot {new Date(liveSnapshot?.checked_at ?? Date.now()).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" })}
                        </span>
                    </div>

                    <div className="mt-4 grid gap-3">
                        {liveSessions.map((session) => (
                            <div
                                key={session.session_id}
                                className="flex flex-col gap-3 rounded-2xl border border-white/30 bg-white/35 p-4 sm:flex-row sm:items-center sm:justify-between"
                            >
                                <div>
                                    <p className="text-sm font-semibold text-ink">
                                        {session.rep_name} {"\u2014"} {session.scenario_name} {"\u2014"} {formatElapsed(displayElapsedSeconds(session))}
                                    </p>
                                    <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-muted">
                                        <span>Stage: <span className="font-semibold text-ink">{formatStageLabel(session.stage)}</span></span>
                                        <span>{session.turn_count} turn{session.turn_count === 1 ? "" : "s"}</span>
                                    </div>
                                </div>
                                <button
                                    onClick={() => navigate(`/manager/sessions/${session.session_id}/live`)}
                                    aria-label={`Watch ${session.rep_name} live session`}
                                    className="inline-flex items-center justify-center rounded-full bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-hover"
                                >
                                    Watch Live →
                                </button>
                            </div>
                        ))}
                    </div>
                </motion.section>
            ) : null}

            <section className="mb-6 rounded-3xl border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl">
                <div className="mb-4 flex items-center gap-2 text-sm font-semibold text-ink">
                    <Filter className="h-4 w-4 text-accent" />
                    Feed Filters
                </div>

                <div className="grid gap-3 xl:grid-cols-[1.4fr_repeat(4,minmax(0,1fr))]">
                    <label className="relative">
                        <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted/60" />
                        <input
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            placeholder="Search rep, scenario, or session"
                            className="w-full rounded-2xl border border-white/35 bg-white/60 py-3 pl-11 pr-4 text-sm text-ink outline-none transition focus:border-accent/50 focus:ring-2 focus:ring-accent/20"
                        />
                    </label>

                    <select
                        value={repFilter}
                        onChange={(event) => setRepFilter(event.target.value)}
                        className="rounded-2xl border border-white/35 bg-white/60 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent/50 focus:ring-2 focus:ring-accent/20"
                    >
                        <option value="all">All reps</option>
                        {repOptions.map((option) => (
                            <option key={option} value={option}>
                                {option}
                            </option>
                        ))}
                    </select>

                    <select
                        value={scenarioFilter}
                        onChange={(event) => setScenarioFilter(event.target.value)}
                        className="rounded-2xl border border-white/35 bg-white/60 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent/50 focus:ring-2 focus:ring-accent/20"
                    >
                        <option value="all">All scenarios</option>
                        {scenarioOptions.map((option) => (
                            <option key={option} value={option}>
                                {option}
                            </option>
                        ))}
                    </select>

                    <label className="relative">
                        <CalendarRange className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted/60" />
                        <input
                            type="date"
                            value={startDate}
                            onChange={(event) => setStartDate(event.target.value)}
                            className="w-full rounded-2xl border border-white/35 bg-white/60 py-3 pl-11 pr-4 text-sm text-ink outline-none transition focus:border-accent/50 focus:ring-2 focus:ring-accent/20"
                        />
                    </label>

                    <label className="relative">
                        <CalendarRange className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted/60" />
                        <input
                            type="date"
                            value={endDate}
                            onChange={(event) => setEndDate(event.target.value)}
                            className="w-full rounded-2xl border border-white/35 bg-white/60 py-3 pl-11 pr-4 text-sm text-ink outline-none transition focus:border-accent/50 focus:ring-2 focus:ring-accent/20"
                        />
                    </label>
                </div>

                <div className="mt-4 flex flex-wrap gap-2">
                    {(["all", "unreviewed", "reviewed"] as ReviewFilter[]).map((value) => {
                        const active = reviewFilter === value;
                        return (
                            <button
                                key={value}
                                onClick={() => setReviewFilter(value)}
                                className={`rounded-full px-4 py-2 text-sm font-medium transition ${active
                                    ? "bg-accent text-white shadow-lg shadow-accent/20"
                                    : "border border-white/35 bg-white/50 text-ink hover:bg-white/70"
                                    }`}
                            >
                                {value === "all" ? "All Sessions" : value === "unreviewed" ? "Unreviewed" : "Reviewed"}
                            </button>
                        );
                    })}
                </div>
            </section>

            <AnimatePresence>
                {error ? (
                    <motion.div
                        className="mb-6 flex items-center gap-3 rounded-2xl border border-error/15 bg-error/[0.06] px-5 py-3.5 text-sm text-error shadow-lg shadow-error/5"
                        initial={{ opacity: 0, y: -10, scale: 0.97 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: -10, scale: 0.97 }}
                        transition={{ duration: 0.2 }}
                    >
                        <AlertCircle className="h-4 w-4 shrink-0" />
                        <span>{error}</span>
                    </motion.div>
                ) : null}
            </AnimatePresence>

            {!filteredFeed.length ? (
                <div className="rounded-3xl border border-white/30 bg-white/40 px-6 py-10 shadow-xl shadow-black/5 backdrop-blur-2xl">
                    {feed.length ? (
                        <EmptyState
                            variant="empty"
                            message="No sessions match the current filters."
                            icon={ShieldAlert}
                        />
                    ) : (
                        <div className="space-y-5 text-center">
                            <EmptyState
                                variant="empty"
                                message="No sessions are available for this team yet."
                                icon={ShieldAlert}
                            />
                            <button
                                type="button"
                                aria-label="Open assignment builder"
                                onClick={() => navigate("/manager/assignments/new")}
                                className="inline-flex items-center justify-center rounded-xl bg-accent px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-accent/20 transition hover:bg-accent-hover"
                            >
                                Assign Drill
                            </button>
                        </div>
                    )}
                </div>
            ) : (
                <FeedList
                    items={filteredFeed}
                    activeSessionId={null}
                    riskByRepId={riskByRepId}
                    onSelect={(sessionId) => navigate(`/manager/sessions/${sessionId}/replay`)}
                />
            )}

            {analytics?.completion_rate !== undefined ? (
                <p className="mt-4 text-sm text-muted">
                    Team completion rate: <span className="font-semibold text-ink">{Math.round(analytics.completion_rate * 100)}%</span>
                </p>
            ) : null}
        </motion.main>
    );
}
