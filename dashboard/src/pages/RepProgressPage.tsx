import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, TrendingDown, TrendingUp } from "lucide-react";
import {
    ResponsiveContainer,
    LineChart,
    Line,
    XAxis,
    YAxis,
    Tooltip as RechartsTooltip,
    ReferenceLine,
    RadarChart,
    PolarGrid,
    PolarAngleAxis,
    PolarRadiusAxis,
    Radar
} from "recharts";

import { EmptyState } from "../components/shared/EmptyState";
import { ScoreChip } from "../components/shared/ScoreChip";
import { SkillChip } from "../components/shared/SkillChip";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { fetchManagerFeed, fetchRepProgress } from "../lib/api";
import type { CategoryScoreValue, FeedItem, RepProgress } from "../lib/types";

const CATEGORY_META = [
    { key: "opening", label: "Opening" },
    { key: "pitch_delivery", label: "Pitch" },
    { key: "objection_handling", label: "Objection Handling" },
    { key: "closing_technique", label: "Closing" },
    { key: "professionalism", label: "Professionalism" },
] as const;

function scoreValue(value: CategoryScoreValue | undefined): number | null {
    if (typeof value === "number") {
        return value;
    }
    return typeof value?.score === "number" ? value.score : null;
}

function formatDuration(durationSeconds?: number | null): string {
    if (!durationSeconds) {
        return "--";
    }
    const minutes = Math.floor(durationSeconds / 60);
    const seconds = durationSeconds % 60;
    return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export function RepProgressPage() {
    const { id } = useParams<{ id: string }>();
    const repId = id || "unknown";
    const navigate = useNavigate();
    const auth = getValidStoredAuth();
    const managerId = auth?.user.id ?? "";

    const [progress, setProgress] = useState<RepProgress | null>(null);
    const [feed, setFeed] = useState<FeedItem[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const loadData = useCallback(async () => {
        if (!managerId) {
            return;
        }
        setLoading(true);
        setError(null);
        try {
            const [progressData, feedData] = await Promise.all([
                fetchRepProgress(managerId, repId),
                fetchManagerFeed(managerId)
            ]);
            setProgress(progressData);
            setFeed(feedData.filter((item) => item.rep_id === repId));
        } catch (err) {
            if (isAuthError(err)) {
                clearStoredAuth();
                navigate("/login", { replace: true });
                return;
            }
            setError(err instanceof Error ? err.message : "Failed to fetch rep progress");
        } finally {
            setLoading(false);
        }
    }, [managerId, navigate, repId]);

    useEffect(() => {
        void loadData();
    }, [loadData]);

    const repName = feed[0]?.rep_name ?? repId;

    const scoredSessions = useMemo(
        () => (progress?.latest_sessions ?? []).filter((session) => typeof session.overall_score === "number"),
        [progress]
    );

    const bestScore = useMemo(() => {
        if (!scoredSessions.length) {
            return "--";
        }
        return Math.max(...scoredSessions.map((session) => session.overall_score ?? 0)).toFixed(1);
    }, [scoredSessions]);

    const lineData = useMemo(() => {
        return (progress?.latest_sessions ?? [])
            .slice(0, 30)
            .reverse()
            .map((session) => ({
                date: session.started_at
                    ? new Date(session.started_at).toLocaleDateString(undefined, { month: "short", day: "numeric" })
                    : "Unknown",
                score: session.overall_score ?? 0
            }));
    }, [progress]);

    const trendDelta = useMemo(() => {
        if (scoredSessions.length < 2) {
            return null;
        }
        const latest = scoredSessions[0]?.overall_score ?? 0;
        const oldest = scoredSessions[scoredSessions.length - 1]?.overall_score ?? 0;
        return latest - oldest;
    }, [scoredSessions]);

    const radarData = useMemo(() => {
        const source = feed
            .filter((item) => typeof item.overall_score === "number")
            .slice(0, 30);
        return CATEGORY_META.map((category) => {
            const values = source
                .map((item) => scoreValue(item.category_scores?.[category.key]))
                .filter((value): value is number => typeof value === "number");
            const average = values.length
                ? values.reduce((sum, value) => sum + value, 0) / values.length
                : 0;
            return {
                subject: category.label,
                score: Number(average.toFixed(1))
            };
        });
    }, [feed]);

    const weakSkills = useMemo(() => radarData.filter((skill) => skill.score < 6.0), [radarData]);

    const sessionRows = useMemo(() => {
        const feedBySessionId = new Map(feed.map((item) => [item.session_id, item]));
        return (progress?.latest_sessions ?? []).map((session) => ({
            ...session,
            feed: feedBySessionId.get(session.session_id)
        }));
    }, [feed, progress]);

    if (loading) {
        return <EmptyState variant="loading" message="Loading rep progress..." />;
    }

    if (error) {
        return <EmptyState variant="error" message={error} onRetry={() => void loadData()} />;
    }

    if (!progress) {
        return <EmptyState variant="empty" message="No data found for this rep." />;
    }

    return (
        <motion.main
            className="max-w-7xl mx-auto px-6 py-6 space-y-6"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: "easeOut" }}
        >
            <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                <div>
                    <Link to="/manager/feed" className="text-muted text-sm hover:text-ink transition-colors mb-2 inline-block">
                        &larr; All Sessions
                    </Link>
                    <h1 className="text-3xl font-bold tracking-tight text-ink">Rep Progress</h1>
                    <p className="mt-1 text-sm text-muted">{repName} · {progress.rep_id}</p>
                </div>
                <button
                    onClick={() => navigate("/manager/assignments/new")}
                    className="bg-accent text-white rounded-xl px-5 py-2.5 text-sm font-medium hover:bg-accent-hover transition-colors shadow-lg shadow-accent/25"
                >
                    Assign Drill
                </button>
            </header>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-4 text-center">
                    <span className="text-xs text-muted uppercase tracking-wide block mb-1">Sessions Completed</span>
                    <strong className="text-2xl font-bold text-ink">{progress.session_count}</strong>
                </div>
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-4 text-center">
                    <span className="text-xs text-muted uppercase tracking-wide block mb-1">Average Score</span>
                    <strong className="text-2xl font-bold text-ink">{progress.average_score?.toFixed(1) ?? "--"}</strong>
                </div>
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-4 text-center">
                    <span className="text-xs text-muted uppercase tracking-wide block mb-1">Best Score</span>
                    <strong className="text-2xl font-bold text-ink">{bestScore}</strong>
                </div>
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-4 text-center">
                    <span className="text-xs text-muted uppercase tracking-wide block mb-1">Improvement Δ</span>
                    <div className="flex items-center justify-center gap-1">
                        {trendDelta !== null && trendDelta >= 0 ? (
                            <TrendingUp className="w-5 h-5 text-green-600" />
                        ) : (
                            <TrendingDown className="w-5 h-5 text-red-600" />
                        )}
                        <strong className="text-2xl font-bold text-ink">
                            {trendDelta === null ? "--" : `${trendDelta >= 0 ? "+" : ""}${trendDelta.toFixed(1)}`}
                        </strong>
                    </div>
                </div>
            </div>

            <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6">
                <div className="flex items-center justify-between mb-6">
                    <h2 className="text-base font-semibold text-ink">Score Trend</h2>
                    <div className="bg-white/50 backdrop-blur-xl border border-white/30 rounded-full px-3 py-1 text-xs font-medium text-ink">
                        Last 30 sessions
                    </div>
                </div>

                {lineData.length > 0 ? (
                    <div className="h-[220px] w-full">
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={lineData} margin={{ top: 5, right: 20, left: -20, bottom: 0 }}>
                                <XAxis dataKey="date" tick={{ fontSize: 12, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                                <YAxis domain={[0, 10]} tickCount={6} tick={{ fontSize: 12, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                                <RechartsTooltip
                                    contentStyle={{ backgroundColor: "rgba(255,255,255,0.92)", backdropFilter: "blur(10px)", borderRadius: "12px", border: "1px solid rgba(255,255,255,0.3)" }}
                                    itemStyle={{ color: "var(--color-ink)", fontWeight: 600 }}
                                    labelStyle={{ color: "var(--color-muted)", fontSize: 12, marginBottom: 4 }}
                                />
                                <ReferenceLine y={7.0} stroke="#fbbf24" strokeDasharray="3 3" opacity={0.5} />
                                <Line type="monotone" dataKey="score" stroke="var(--color-accent)" strokeWidth={2} dot={{ fill: "var(--color-accent)", r: 3 }} activeDot={{ r: 5 }} />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                ) : (
                    <EmptyState variant="empty" message="No sessions recorded yet." />
                )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6">
                    <h2 className="text-base font-semibold text-ink mb-2">Category Radar</h2>
                    <p className="text-sm text-muted mb-4">Current-period average across the five rubric categories.</p>
                    <div className="h-[240px] w-full flex items-center justify-center">
                        <ResponsiveContainer width="100%" height="100%">
                            <RadarChart cx="50%" cy="50%" outerRadius="72%" data={radarData}>
                                <PolarGrid stroke="var(--color-border-strong)" />
                                <PolarAngleAxis dataKey="subject" tick={{ fill: "var(--color-muted)", fontSize: 12 }} />
                                <PolarRadiusAxis angle={30} domain={[0, 10]} tick={false} axisLine={false} />
                                <Radar name="Rep" dataKey="score" stroke="var(--color-accent)" fill="var(--color-accent-soft)" fillOpacity={0.45} />
                            </RadarChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6 flex flex-col">
                    <h2 className="text-base font-semibold text-ink mb-4">Weak Areas</h2>
                    {weakSkills.length > 0 ? (
                        <>
                            <div className="flex flex-wrap gap-2 mb-6">
                                {weakSkills.map((skill) => (
                                    <SkillChip key={skill.subject} label={skill.subject} variant="weak" />
                                ))}
                            </div>
                            <button
                                onClick={() => navigate("/manager/assignments/new")}
                                className="mt-auto w-full flex items-center justify-center gap-2 bg-white/50 backdrop-blur-xl border border-white/30 text-ink rounded-xl px-4 py-3 text-sm font-medium hover:bg-white/70 transition-colors"
                            >
                                Assign Follow-Up Drill
                                <ArrowRight className="w-4 h-4 text-muted" />
                            </button>
                        </>
                    ) : (
                        <EmptyState variant="empty" message="No categories are averaging below 6.0 this period." />
                    )}
                </div>
            </div>

            <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6 overflow-hidden flex flex-col">
                <h2 className="text-base font-semibold text-ink mb-4">Session History</h2>

                {sessionRows.length > 0 ? (
                    <div className="overflow-x-auto">
                        <table className="w-full text-left border-collapse">
                            <thead>
                                <tr className="border-b border-white/20">
                                    <th className="py-3 px-2 text-xs font-semibold tracking-wide text-muted uppercase">Date</th>
                                    <th className="py-3 px-2 text-xs font-semibold tracking-wide text-muted uppercase">Scenario</th>
                                    <th className="py-3 px-2 text-xs font-semibold tracking-wide text-muted uppercase">Duration</th>
                                    <th className="py-3 px-2 text-xs font-semibold tracking-wide text-muted uppercase">Score</th>
                                    <th className="py-3 px-2 text-xs font-semibold tracking-wide text-muted uppercase text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-white/10">
                                {sessionRows.map((session) => (
                                    <tr key={session.session_id} className="hover:bg-white/20 transition-colors">
                                        <td className="py-3 px-2 text-sm text-ink">
                                            {session.started_at
                                                ? new Date(session.started_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })
                                                : "--"}
                                        </td>
                                        <td className="py-3 px-2 text-sm text-ink">
                                            {session.feed?.scenario_name ?? session.feed?.scenario_id ?? "Unknown scenario"}
                                        </td>
                                        <td className="py-3 px-2 text-sm text-muted">{formatDuration(session.feed?.duration_seconds)}</td>
                                        <td className="py-3 px-2">
                                            <ScoreChip score={session.overall_score} />
                                        </td>
                                        <td className="py-3 px-2 text-right">
                                            <button
                                                onClick={() => navigate(`/manager/sessions/${session.session_id}/replay`)}
                                                className="text-accent text-sm font-medium hover:underline"
                                            >
                                                View Replay
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <EmptyState variant="empty" message="No session history available." />
                )}
            </div>
        </motion.main>
    );
}
