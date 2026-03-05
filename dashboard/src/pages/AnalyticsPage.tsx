import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { TrendingDown, TrendingUp } from "lucide-react";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip, ReferenceLine, Cell } from "recharts";

import { EmptyState } from "../components/shared/EmptyState";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { fetchManagerAssignments, fetchManagerFeed, fetchManagerTeam } from "../lib/api";
import type { FeedItem, ManagerAssignment, ManagerTeamMember } from "../lib/types";

const PERIOD_OPTIONS = [
    { key: "7d", label: "7 days", days: 7 },
    { key: "30d", label: "30 days", days: 30 },
    { key: "90d", label: "90 days", days: 90 },
    { key: "custom", label: "Custom", days: 30 },
] as const;

type PeriodKey = (typeof PERIOD_OPTIONS)[number]["key"];

function getBucketColor(bucketIndex: number) {
    if (bucketIndex < 5) return "#fecaca";
    if (bucketIndex < 6) return "#fed7aa";
    if (bucketIndex < 8) return "#fde68a";
    return "#a7f3d0";
}

function averageScore(items: FeedItem[]) {
    const scores = items.map((item) => item.overall_score).filter((score): score is number => typeof score === "number");
    if (!scores.length) {
        return null;
    }
    return scores.reduce((sum, score) => sum + score, 0) / scores.length;
}

function bucketScores(items: FeedItem[]) {
    const buckets = Array.from({ length: 10 }, (_, index) => ({ bucket: `${index}-${index + 1}`, count: 0 }));
    for (const item of items) {
        if (typeof item.overall_score !== "number") {
            continue;
        }
        const index = Math.min(9, Math.max(0, Math.floor(item.overall_score)));
        buckets[index].count += 1;
    }
    return buckets;
}

function resolveRange(period: PeriodKey, customStart: string, customEnd: string) {
    const end = customEnd ? new Date(`${customEnd}T23:59:59`) : new Date();
    if (period === "custom" && customStart) {
        return {
            start: new Date(`${customStart}T00:00:00`),
            end
        };
    }
    const days = PERIOD_OPTIONS.find((option) => option.key === period)?.days ?? 30;
    const start = new Date(end);
    start.setDate(end.getDate() - days + 1);
    start.setHours(0, 0, 0, 0);
    return { start, end };
}

export function AnalyticsPage() {
    const navigate = useNavigate();
    const auth = getValidStoredAuth();
    const managerId = auth?.user.id ?? "";

    const [feed, setFeed] = useState<FeedItem[]>([]);
    const [assignments, setAssignments] = useState<ManagerAssignment[]>([]);
    const [team, setTeam] = useState<ManagerTeamMember[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [period, setPeriod] = useState<PeriodKey>("30d");
    const [customStart, setCustomStart] = useState("");
    const [customEnd, setCustomEnd] = useState("");

    const loadData = useCallback(async () => {
        if (!managerId) {
            return;
        }
        setLoading(true);
        setError(null);
        try {
            const [feedData, assignmentData, teamData] = await Promise.all([
                fetchManagerFeed(managerId),
                fetchManagerAssignments(managerId),
                fetchManagerTeam(managerId)
            ]);
            setFeed(feedData);
            setAssignments(assignmentData);
            setTeam(teamData);
        } catch (err) {
            if (isAuthError(err)) {
                clearStoredAuth();
                navigate("/login", { replace: true });
                return;
            }
            setError(err instanceof Error ? err.message : "Failed to fetch analytics");
        } finally {
            setLoading(false);
        }
    }, [managerId, navigate]);

    useEffect(() => {
        void loadData();
    }, [loadData]);

    const { start, end } = useMemo(() => resolveRange(period, customStart, customEnd), [customEnd, customStart, period]);

    const filteredSessions = useMemo(() => {
        return feed.filter((item) => {
            if (!item.started_at) {
                return false;
            }
            const startedAt = new Date(item.started_at);
            return startedAt >= start && startedAt <= end;
        });
    }, [end, feed, start]);

    const previousSessions = useMemo(() => {
        const durationMs = end.getTime() - start.getTime();
        const previousEnd = new Date(start.getTime() - 1);
        const previousStart = new Date(previousEnd.getTime() - durationMs);
        return feed.filter((item) => {
            if (!item.started_at) {
                return false;
            }
            const startedAt = new Date(item.started_at);
            return startedAt >= previousStart && startedAt <= previousEnd;
        });
    }, [end, feed, start]);

    const filteredAssignments = useMemo(() => {
        return assignments.filter((assignment) => {
            if (!assignment.created_at) {
                return true;
            }
            const createdAt = new Date(assignment.created_at);
            return createdAt >= start && createdAt <= end;
        });
    }, [assignments, end, start]);

    const teamAverage = averageScore(filteredSessions);
    const previousAverage = averageScore(previousSessions);
    const averageDelta = teamAverage !== null && previousAverage !== null
        ? teamAverage - previousAverage
        : null;

    const completionRows = useMemo(() => {
        const repsById = new Map(team.map((member) => [member.id, member]));
        const rows = new Map<string, { repId: string; repName: string; assigned: number; completed: number; avgScore: number | null }>();

        for (const assignment of filteredAssignments) {
            const current = rows.get(assignment.rep_id) ?? {
                repId: assignment.rep_id,
                repName: repsById.get(assignment.rep_id)?.name ?? assignment.rep_id,
                assigned: 0,
                completed: 0,
                avgScore: null
            };
            current.assigned += 1;
            if (assignment.status === "completed") {
                current.completed += 1;
            }
            rows.set(assignment.rep_id, current);
        }

        for (const [repId, row] of rows) {
            const repScores = filteredSessions
                .filter((item) => item.rep_id === repId && typeof item.overall_score === "number")
                .map((item) => item.overall_score as number);
            row.avgScore = repScores.length
                ? repScores.reduce((sum, score) => sum + score, 0) / repScores.length
                : null;
        }

        return Array.from(rows.values()).sort((a, b) => {
            const aRate = a.assigned ? a.completed / a.assigned : 0;
            const bRate = b.assigned ? b.completed / b.assigned : 0;
            return bRate - aRate;
        });
    }, [filteredAssignments, filteredSessions, team]);

    const scenarioPassRates = useMemo(() => {
        const grouped = new Map<string, { name: string; total: number; passed: number }>();
        for (const item of filteredSessions) {
            const key = item.scenario_name ?? item.scenario_id ?? "Unknown scenario";
            const current = grouped.get(key) ?? { name: key, total: 0, passed: 0 };
            if (typeof item.overall_score === "number") {
                current.total += 1;
                if (item.overall_score >= 7) {
                    current.passed += 1;
                }
            }
            grouped.set(key, current);
        }
        return Array.from(grouped.values())
            .filter((item) => item.total > 0)
            .map((item) => ({
                name: item.name,
                shortName: item.name.length > 20 ? `${item.name.slice(0, 19)}…` : item.name,
                passRate: Number(((item.passed / item.total) * 100).toFixed(0))
            }))
            .sort((a, b) => b.passRate - a.passRate);
    }, [filteredSessions]);

    const scoreDistribution = useMemo(() => bucketScores(filteredSessions), [filteredSessions]);

    if (loading) return <EmptyState variant="loading" message="Loading analytics..." />;
    if (error) return <EmptyState variant="error" message={error} onRetry={() => void loadData()} />;
    if (!filteredSessions.length && !filteredAssignments.length) return <EmptyState variant="empty" message="No analytics data found for the selected date range." />;

    return (
        <motion.main
            className="max-w-7xl mx-auto px-6 py-6 space-y-6"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: "easeOut" }}
        >
            <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight text-ink">Analytics</h1>
                    <p className="mt-1 text-sm text-muted">Review team performance metrics</p>
                </div>

                <div className="space-y-3">
                    <div className="flex bg-white/40 backdrop-blur-2xl border border-white/30 rounded-xl p-1 shadow-sm">
                        {PERIOD_OPTIONS.map((option) => {
                            const isActive = option.key === period;
                            return (
                                <button
                                    key={option.key}
                                    onClick={() => setPeriod(option.key)}
                                    className={`px-4 py-2 text-sm font-medium rounded-lg transition-all ${isActive ? "bg-accent text-white shadow-md shadow-accent/25" : "text-muted hover:bg-white/60 hover:text-ink"
                                        }`}
                                >
                                    {option.label}
                                </button>
                            );
                        })}
                    </div>
                    {period === "custom" ? (
                        <div className="flex gap-2">
                            <input
                                type="date"
                                value={customStart}
                                onChange={(event) => setCustomStart(event.target.value)}
                                className="rounded-xl border border-white/30 bg-white/50 px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-accent/20"
                            />
                            <input
                                type="date"
                                value={customEnd}
                                onChange={(event) => setCustomEnd(event.target.value)}
                                className="rounded-xl border border-white/30 bg-white/50 px-3 py-2 text-sm text-ink outline-none focus:ring-2 focus:ring-accent/20"
                            />
                        </div>
                    ) : null}
                </div>
            </header>

            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-4 text-center">
                    <span className="text-xs text-muted uppercase tracking-wide block mb-1">Team Average Score</span>
                    <div className="flex items-center justify-center gap-1">
                        <strong className="text-2xl font-bold text-ink">{teamAverage?.toFixed(1) ?? "--"}</strong>
                        {averageDelta !== null ? (
                            averageDelta >= 0 ? <TrendingUp className="w-5 h-5 text-green-600 ml-1" /> : <TrendingDown className="w-5 h-5 text-red-600 ml-1" />
                        ) : null}
                    </div>
                    <div className="mt-2 text-xs text-muted">
                        {averageDelta === null ? "No previous-period comparison" : `${averageDelta >= 0 ? "+" : ""}${averageDelta.toFixed(1)} vs previous period`}
                    </div>
                </div>
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-4 text-center">
                    <span className="text-xs text-muted uppercase tracking-wide block mb-1">Sessions This Period</span>
                    <strong className="text-2xl font-bold text-ink">{filteredSessions.length}</strong>
                </div>
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-4 text-center">
                    <span className="text-xs text-muted uppercase tracking-wide block mb-1">Assignments This Period</span>
                    <strong className="text-2xl font-bold text-ink">{filteredAssignments.length}</strong>
                </div>
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-4 text-center">
                    <span className="text-xs text-muted uppercase tracking-wide block mb-1">Scenario Pass Entries</span>
                    <strong className="text-2xl font-bold text-ink">{scenarioPassRates.length}</strong>
                </div>
            </div>

            <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6">
                <h2 className="text-base font-semibold text-ink mb-4">Completion Rate by Rep</h2>
                {completionRows.length ? (
                    <div className="overflow-x-auto">
                        <table className="w-full text-left border-collapse">
                            <thead>
                                <tr className="border-b border-white/20">
                                    <th className="py-3 px-2 text-xs font-semibold tracking-wide text-muted uppercase">Rep Name</th>
                                    <th className="py-3 px-2 text-xs font-semibold tracking-wide text-muted uppercase">Assigned</th>
                                    <th className="py-3 px-2 text-xs font-semibold tracking-wide text-muted uppercase">Completed</th>
                                    <th className="py-3 px-2 text-xs font-semibold tracking-wide text-muted uppercase">Completion %</th>
                                    <th className="py-3 px-2 text-xs font-semibold tracking-wide text-muted uppercase">Avg Score</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-white/10">
                                {completionRows.map((rep) => {
                                    const rate = rep.assigned ? Math.round((rep.completed / rep.assigned) * 100) : 0;
                                    const rateColor = rate >= 80 ? "bg-green-500" : rate >= 50 ? "bg-amber-500" : "bg-red-500";
                                    return (
                                        <tr key={rep.repId} className="hover:bg-white/20 transition-colors cursor-pointer" onClick={() => navigate(`/manager/reps/${rep.repId}/progress`)}>
                                            <td className="py-3 px-2 text-sm font-medium text-ink hover:text-accent hover:underline">{rep.repName}</td>
                                            <td className="py-3 px-2 text-sm text-ink">{rep.assigned}</td>
                                            <td className="py-3 px-2 text-sm text-ink">{rep.completed}</td>
                                            <td className="py-3 px-2">
                                                <div className="flex items-center gap-2">
                                                    <div className="w-10 h-1.5 bg-white/40 rounded-full overflow-hidden shrink-0">
                                                        <div className={`h-full ${rateColor}`} style={{ width: `${Math.min(100, rate)}%` }} />
                                                    </div>
                                                    <span className="text-sm font-semibold text-ink">{rate}%</span>
                                                </div>
                                            </td>
                                            <td className="py-3 px-2 text-sm font-bold text-ink">{rep.avgScore?.toFixed(1) ?? "--"}</td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                ) : (
                    <EmptyState variant="empty" message="No assignment completion data in this range." />
                )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6">
                    <div className="mb-6">
                        <h2 className="text-base font-semibold text-ink">Scenario Pass Rate</h2>
                        <p className="text-sm text-muted">% of sessions scoring &ge; 7.0</p>
                    </div>
                    {scenarioPassRates.length ? (
                        <div className="h-[240px] w-full">
                            <ResponsiveContainer width="100%" height="100%">
                                <BarChart layout="vertical" data={scenarioPassRates} margin={{ top: 0, right: 30, left: 20, bottom: 0 }}>
                                    <XAxis type="number" domain={[0, 100]} tickFormatter={(val) => `${val}%`} tick={{ fontSize: 12, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                                    <YAxis dataKey="shortName" type="category" width={110} tick={{ fontSize: 12, fill: "var(--color-ink)" }} axisLine={false} tickLine={false} />
                                    <RechartsTooltip
                                        cursor={{ fill: "rgba(255,255,255,0.4)" }}
                                        contentStyle={{ backgroundColor: "rgba(255,255,255,0.9)", backdropFilter: "blur(10px)", borderRadius: "12px", border: "1px solid rgba(255,255,255,0.3)" }}
                                        formatter={(value: number | undefined) => [`${value ?? 0}%`, "Pass Rate"]}
                                    />
                                    <ReferenceLine x={70} stroke="#fbbf24" strokeDasharray="3 3" opacity={0.5} />
                                    <Bar dataKey="passRate" fill="var(--color-accent)" radius={[0, 4, 4, 0]} barSize={24} />
                                </BarChart>
                            </ResponsiveContainer>
                        </div>
                    ) : (
                        <EmptyState variant="empty" message="No scenario pass-rate data for this range." />
                    )}
                </div>

                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6">
                    <div className="mb-6">
                        <h2 className="text-base font-semibold text-ink">Score Distribution</h2>
                    </div>
                    <div className="h-[240px] w-full">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={scoreDistribution} margin={{ top: 10, right: 0, left: -20, bottom: 0 }}>
                                <XAxis dataKey="bucket" tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} interval={0} angle={-30} textAnchor="end" />
                                <YAxis tick={{ fontSize: 12, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                                <RechartsTooltip
                                    cursor={{ fill: "rgba(255,255,255,0.4)" }}
                                    contentStyle={{ backgroundColor: "rgba(255,255,255,0.9)", backdropFilter: "blur(10px)", borderRadius: "12px", border: "1px solid rgba(255,255,255,0.3)" }}
                                    formatter={(value: number | undefined) => [value ?? 0, "Sessions"]}
                                />
                                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                                    {scoreDistribution.map((entry, index) => (
                                        <Cell key={`cell-${entry.bucket}`} fill={getBucketColor(index)} />
                                    ))}
                                </Bar>
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>
            </div>
        </motion.main>
    );
}
