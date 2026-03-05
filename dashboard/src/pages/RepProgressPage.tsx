import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { TrendingUp, TrendingDown, ChevronRight } from "lucide-react";
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip as RechartsTooltip, ReferenceLine, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Radar } from "recharts";

import { fetchRepProgress } from "../lib/api";
import type { RepProgress } from "../lib/types";
import { EmptyState } from "../components/shared/EmptyState";
import { ScoreChip } from "../components/shared/ScoreChip";
import { SkillChip } from "../components/shared/SkillChip";

// Mock data for skills since API doesn't provide category breakdowns per rep yet
const MOCK_SKILLS = [
    { subject: 'Opening', score: 8.5 },
    { subject: 'Pitch', score: 7.2 },
    { subject: 'Objection', score: 5.4 },
    { subject: 'Closing', score: 6.1 },
    { subject: 'Professionalism', score: 9.0 },
];

export function RepProgressPage() {
    const { id } = useParams<{ id: string }>();
    const repId = id || "unknown";
    const navigate = useNavigate();

    const [progress, setProgress] = useState<RepProgress | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        async function loadData() {
            setLoading(true);
            setError(null);
            try {
                // Hardcoding managerId for demo purposes, would normally come from context
                const data = await fetchRepProgress("mgr_123", repId);
                setProgress(data);
            } catch (err) {
                setError(err instanceof Error ? err.message : "Failed to fetch rep progress");
            } finally {
                setLoading(false);
            }
        }
        void loadData();
    }, [repId]);

    const bestScore = useMemo(() => {
        if (!progress || !progress.latest_sessions.length) return "--";
        const scores = progress.latest_sessions.map(s => s.overall_score).filter(s => s !== null) as number[];
        if (!scores.length) return "--";
        return Math.max(...scores).toFixed(1);
    }, [progress]);

    const lineData = useMemo(() => {
        if (!progress) return [];
        return [...progress.latest_sessions].reverse().map((s) => ({
            date: s.started_at ? new Date(s.started_at).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : 'Unknown',
            score: s.overall_score || 0
        }));
    }, [progress]);

    const weakSkills = MOCK_SKILLS.filter(s => s.score < 6.0);

    if (loading) {
        return <EmptyState variant="loading" message="Loading rep progress..." />;
    }

    if (error) {
        return <EmptyState variant="error" message={error} onRetry={() => window.location.reload()} />;
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
            {/* 6.1 Page Header */}
            <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                <div>
                    <Link to="/manager/feed" className="text-muted text-sm hover:text-ink transition-colors mb-2 inline-block">
                        &larr; All Sessions
                    </Link>
                    <h1 className="text-3xl font-bold tracking-tight text-ink">Rep Overview</h1>
                    <p className="mt-1 text-sm text-muted">ID: {progress.rep_id}</p>
                </div>
                <div>
                    <button
                        onClick={() => navigate("/manager/assignments/new")}
                        className="bg-accent text-white rounded-xl px-5 py-2.5 text-sm font-medium hover:bg-accent-hover transition-colors shadow-lg shadow-accent/25"
                    >
                        Assign Drill
                    </button>
                </div>
            </header>

            {/* 6.2 Metric Cards Row */}
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
                        <TrendingUp className="w-5 h-5 text-green-600" />
                        <strong className="text-2xl font-bold text-ink">+0.8</strong>
                    </div>
                </div>
            </div>

            {/* 6.3 Score Over Time Chart */}
            <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6">
                <div className="flex items-center justify-between mb-6">
                    <h2 className="text-base font-semibold text-ink">Score Trend</h2>
                    <div className="bg-white/50 backdrop-blur-xl border border-white/30 rounded-full px-3 py-1 text-xs font-medium text-ink">
                        All Time
                    </div>
                </div>

                {lineData.length > 0 ? (
                    <div className="h-[200px] w-full">
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={lineData} margin={{ top: 5, right: 20, left: -20, bottom: 0 }}>
                                <XAxis dataKey="date" tick={{ fontSize: 12, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                                <YAxis domain={[0, 10]} tickCount={6} tick={{ fontSize: 12, fill: "var(--color-muted)" }} axisLine={false} tickLine={false} />
                                <RechartsTooltip
                                    contentStyle={{ backgroundColor: 'rgba(255,255,255,0.9)', backdropFilter: 'blur(10px)', borderRadius: '12px', border: '1px solid rgba(255,255,255,0.3)' }}
                                    itemStyle={{ color: 'var(--color-ink)', fontWeight: 600 }}
                                    labelStyle={{ color: 'var(--color-muted)', fontSize: 12, marginBottom: 4 }}
                                />
                                <ReferenceLine y={7.0} stroke="#fbbf24" strokeDasharray="3 3" opacity={0.5} label={{ position: 'insideTopLeft', value: '7.0 target', fill: '#d97706', fontSize: 11 }} />
                                <Line type="monotone" dataKey="score" stroke="var(--color-accent)" strokeWidth={2} dot={{ fill: 'var(--color-accent)', r: 3 }} activeDot={{ r: 5 }} />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                ) : (
                    <EmptyState variant="empty" message="No sessions recorded yet." />
                )}
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* 6.4 Category Radar Chart */}
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6">
                    <h2 className="text-base font-semibold text-ink mb-2">Skill Breakdown</h2>
                    <div className="h-[220px] w-full flex items-center justify-center">
                        <ResponsiveContainer width="100%" height="100%">
                            <RadarChart cx="50%" cy="50%" outerRadius="70%" data={MOCK_SKILLS}>
                                <PolarGrid stroke="var(--color-border-strong)" />
                                <PolarAngleAxis dataKey="subject" tick={{ fill: 'var(--color-muted)', fontSize: 12 }} />
                                <PolarRadiusAxis angle={30} domain={[0, 10]} tick={false} axisLine={false} />
                                <Radar name="Rep" dataKey="score" stroke="var(--color-accent)" fill="var(--color-accent-soft)" fillOpacity={0.4} />
                            </RadarChart>
                        </ResponsiveContainer>
                    </div>
                </div>

                {/* 6.5 Weak Area Tags Card */}
                <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6 flex flex-col">
                    <h2 className="text-base font-semibold text-ink mb-4">Areas to Improve</h2>

                    {weakSkills.length > 0 ? (
                        <div className="flex-1 flex flex-col">
                            <div className="flex flex-wrap gap-2 mb-6">
                                {weakSkills.map(skill => (
                                    <SkillChip key={skill.subject} label={skill.subject} variant="weak" />
                                ))}
                            </div>

                            <div className="mt-auto">
                                <button
                                    onClick={() => navigate("/manager/assignments/new")}
                                    className="w-full flex items-center justify-center gap-2 bg-white/50 backdrop-blur-xl border border-white/30 text-ink rounded-xl px-4 py-3 text-sm font-medium hover:bg-white/70 transition-colors"
                                >
                                    Assign Drill for Weak Areas
                                    <ChevronRight className="w-4 h-4 text-muted" />
                                </button>
                            </div>
                        </div>
                    ) : (
                        <div className="flex-1 flex items-center justify-center">
                            <EmptyState variant="empty" message="No weak areas this period 🎉" />
                        </div>
                    )}
                </div>
            </div>

            {/* 6.6 Session History Table */}
            <div className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6 overflow-hidden flex flex-col">
                <h2 className="text-base font-semibold text-ink mb-4">Session History</h2>

                {progress.latest_sessions.length > 0 ? (
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
                                {progress.latest_sessions.map((session) => (
                                    <tr key={session.session_id} className="hover:bg-white/20 transition-colors">
                                        <td className="py-3 px-2 text-sm text-muted">
                                            {session.started_at ? new Date(session.started_at).toLocaleDateString() : 'Unknown'}
                                        </td>
                                        <td className="py-3 px-2 text-sm font-medium text-ink">
                                            {/* Mock scenario name since it's not in latest_sessions natively, normally fetched or joined */}
                                            Scenario {session.session_id.slice(0, 4)}
                                        </td>
                                        <td className="py-3 px-2 text-sm text-muted">
                                            04:20
                                        </td>
                                        <td className="py-3 px-2">
                                            <ScoreChip score={session.overall_score} size="sm" />
                                        </td>
                                        <td className="py-3 px-2 text-right">
                                            <Link to={`/manager/sessions/${session.session_id}/replay`} className="text-sm text-accent font-medium hover:underline">
                                                View
                                            </Link>
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
