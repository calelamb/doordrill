import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "framer-motion";
import { TrendingUp, TrendingDown } from "lucide-react";
import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip, ReferenceLine, Cell } from "recharts";

import { fetchManagerAnalytics } from "../lib/api";
import type { ManagerAnalytics } from "../lib/types";
import { EmptyState } from "../components/shared/EmptyState";

// Mock data to flesh out dashboard tables/charts not provided directly by singular ManagerAnalytics API yet
const MOCK_REPS = [
    { id: "REP001", name: "Alice Chen", assigned: 12, completed: 12, avgScore: 8.4 },
    { id: "REP002", name: "Bob Smith", assigned: 15, completed: 10, avgScore: 6.8 },
    { id: "REP003", name: "Charlie Davis", assigned: 8, completed: 2, avgScore: 5.2 },
    { id: "REP004", name: "Diana Prince", assigned: 20, completed: 19, avgScore: 9.1 },
];

const MOCK_SCENARIOS = [
    { name: "First time homeowner", passRate: 85 },
    { name: "Angry resident", passRate: 42 },
    { name: "Price objection hard", passRate: 60 },
    { name: "Spouse isn't home", passRate: 75 },
];

const MOCK_DISTRIBUTION = [
    { bucket: "0-1", count: 0 },
    { bucket: "1-2", count: 1 },
    { bucket: "2-3", count: 3 },
    { bucket: "3-4", count: 8 },
    { bucket: "4-5", count: 12 }, // red
    { bucket: "5-6", count: 25 }, // orange
    { bucket: "6-7", count: 42 }, // amber
    { bucket: "7-8", count: 45 }, // amber
    { bucket: "8-9", count: 38 }, // emerald
    { bucket: "9-10", count: 18 }, // emerald
];

function getBucketColor(bucketIndex: number) {
    if (bucketIndex < 5) return "#fecaca"; // red-200
    if (bucketIndex < 6) return "#fed7aa"; // orange-200
    if (bucketIndex < 8) return "#fde68a"; // amber-200
    return "#a7f3d0"; // emerald-200
}

export function AnalyticsPage() {
    const [analytics, setAnalytics] = useState<ManagerAnalytics | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [period, setPeriod] = useState<"7d" | "30d" | "90d" | "custom">("30d");

    useEffect(() => {
        async function loadData() {
            setLoading(true);
            setError(null);
            try {
                const data = await fetchManagerAnalytics("mgr_123");
                setAnalytics(data);
            } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to fetch analytics");
            } finally {
                setLoading(false);
            }
        }
        void loadData();
    }, [period]);

    if (loading) return <EmptyState variant="loading" message="Loading analytics..." />;
    if (error) return <EmptyState variant="error" message={error} onRetry={() => window.location.reload()} />;
    if (!analytics) return <EmptyState variant="empty" message="No analytics data found." />;

    const poorScenarios = MOCK_SCENARIOS.filter(s => s.passRate < 50).length;

    return (
        <motion.main
            className="max-w-7xl mx-auto px-6 py-6 space-y-6"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: "easeOut" }}
        >
            {/* 7.1 Page Header & Date Range Selector */}
            <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight text-ink">Analytics</h1>
                    <p className="mt-1 text-sm text-muted">Review team performance metrics</p>
                </div>

                <div className="flex bg-white/40 backdrop-blur-2xl border border-white/30 rounded-xl p-1 shadow-sm">
                    {(["7d", "30d", "90d", "custom"] as const).map((p) => {
                        const isActive = p === period;
                        const labels = { "7d": "7 days", "30d": "30 days", "90d": "90 days", custom: "Custom" };
                        return (
                            <button
                                key={p}
                                onClick={() => setPeriod(p)}
                                className={`px-4 py-2 text-sm font-medium rounded-lg transition-all ${isActive ? "bg-accent text-white shadow-md shadow-accent/25" : "text-muted hover:bg-white/60 hover:text-ink"
                                    }`}
                            >
                                {labels[p]}
                            </button>
                        )
                    })}
                </div>
            </header>

            {/* 7.2 Top Metric Cards */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-4 text-center">
                    <span className="text-xs text-muted uppercase tracking-wide block mb-1">Team Average Score</span>
                    <div className="flex items-center justify-center gap-1">
                        <strong className="text-2xl font-bold text-ink">{analytics.average_score?.toFixed(1) ?? "--"}</strong>
                        <TrendingUp className="w-5 h-5 text-green-600 ml-1" />
                    </div>
                </div>
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-4 text-center">
                    <span className="text-xs text-muted uppercase tracking-wide block mb-1">Sessions This Period</span>
                    <strong className="text-2xl font-bold text-ink">{analytics.sessions_count}</strong>
                </div>
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-4 text-center">
                    <span className="text-xs text-muted uppercase tracking-wide block mb-1">Completion Rate</span>
                    <strong className="text-2xl font-bold text-ink">{(analytics.completion_rate * 100).toFixed(0)}%</strong>
                </div>
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-4 text-center">
                    <span className="text-xs text-muted uppercase tracking-wide block mb-1">Scenarios &lt; 50% Pass</span>
                    <div className="flex items-center justify-center gap-1">
                        <strong className="text-2xl font-bold text-ink">{poorScenarios}</strong>
                        <TrendingDown className="w-5 h-5 text-red-600 ml-1" />
                    </div>
                </div>
            </div>

            {/* 7.3 Completion Rate by Rep */}
            <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6">
                <h2 className="text-base font-semibold text-ink mb-4">Rep Completion Rate</h2>
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
                            {[...MOCK_REPS].sort((a, b) => {
                                const aRate = a.completed / a.assigned;
                                const bRate = b.completed / b.assigned;
                                return bRate - aRate;
                            }).map((rep) => {
                                const rate = Math.round((rep.completed / rep.assigned) * 100);
                                const rateColor = rate >= 80 ? 'bg-green-500' : rate >= 50 ? 'bg-amber-500' : 'bg-red-500';

                                return (
                                    <tr key={rep.id} className="hover:bg-white/20 transition-colors cursor-pointer" onClick={() => window.location.href = `/manager/reps/${rep.id}/progress`}>
                                        <td className="py-3 px-2 flex items-center gap-2">
                                            <span className="text-sm font-medium text-ink hover:text-accent hover:underline">{rep.name}</span>
                                        </td>
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
                                        <td className="py-3 px-2 text-sm font-bold text-ink">{rep.avgScore.toFixed(1)}</td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* 7.4 Scenario Pass Rate */}
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6">
                    <div className="mb-6">
                        <h2 className="text-base font-semibold text-ink">Scenario Pass Rate</h2>
                        <p className="text-sm text-muted">% of sessions scoring &ge; 7.0</p>
                    </div>
                    <div className="h-[240px] w-full">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart layout="vertical" data={MOCK_SCENARIOS.map(s => ({ ...s, shortName: s.name.length > 20 ? s.name.slice(0, 19) + "…" : s.name }))} margin={{ top: 0, right: 30, left: 20, bottom: 0 }}>
                                <XAxis type="number" domain={[0, 100]} tickFormatter={(val) => `${val}%`} tick={{ fontSize: 12, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                                <YAxis dataKey="shortName" type="category" width={100} tick={{ fontSize: 12, fill: "var(--color-ink)" }} axisLine={false} tickLine={false} />
                                <RechartsTooltip
                                    cursor={{ fill: 'rgba(255,255,255,0.4)' }}
                                    contentStyle={{ backgroundColor: 'rgba(255,255,255,0.9)', backdropFilter: 'blur(10px)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.3)' }}
                                    formatter={(value: any) => [`${value}%`, 'Pass Rate']}
                                />
                                <ReferenceLine x={70} stroke="#fbbf24" strokeDasharray="3 3" opacity={0.5} />
                                <Bar dataKey="passRate" fill="var(--color-accent)" radius={[0, 4, 4, 0]} barSize={24} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* 7.5 Score Distribution Histogram */}
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6">
                    <div className="mb-6">
                        <h2 className="text-base font-semibold text-ink">Score Distribution</h2>
                    </div>
                    <div className="h-[240px] w-full">
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={MOCK_DISTRIBUTION} margin={{ top: 10, right: 0, left: -20, bottom: 0 }}>
                                <XAxis dataKey="bucket" tick={{ fontSize: 11, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} interval={0} angle={-30} textAnchor="end" />
                                <YAxis tick={{ fontSize: 12, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                                <RechartsTooltip
                                    cursor={{ fill: 'rgba(255,255,255,0.4)' }}
                                    contentStyle={{ backgroundColor: 'rgba(255,255,255,0.9)', backdropFilter: 'blur(10px)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.3)' }}
                                    formatter={(value: any) => [value, 'Sessions']}
                                />
                                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                                    {MOCK_DISTRIBUTION.map((entry, index) => (
                                        <Cell key={`cell-${index}`} fill={getBucketColor(index)} />
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
