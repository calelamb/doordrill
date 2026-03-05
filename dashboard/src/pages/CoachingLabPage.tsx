import { useCallback, useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { BookOpenText, MessageSquareQuote, Scale, TrendingUp } from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip as RechartsTooltip,
  XAxis,
  YAxis,
} from "recharts";

import { EmptyState } from "../components/shared/EmptyState";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { fetchManagerCoachingAnalytics } from "../lib/api";
import type { CoachingAnalyticsResponse } from "../lib/types";

const PERIOD_OPTIONS = [
  { key: "7", label: "7D" },
  { key: "30", label: "30D" },
  { key: "90", label: "90D" },
] as const;

type PeriodKey = (typeof PERIOD_OPTIONS)[number]["key"];

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`;
}

export function CoachingLabPage() {
  const navigate = useNavigate();
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";

  const [period, setPeriod] = useState<PeriodKey>("30");
  const [data, setData] = useState<CoachingAnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!managerId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetchManagerCoachingAnalytics(managerId, { period });
      setData(response);
    } catch (err) {
      if (isAuthError(err)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load coaching analytics");
    } finally {
      setLoading(false);
    }
  }, [managerId, navigate, period]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  const upliftChart = useMemo(
    () =>
      (data?.coaching_uplift ?? [])
        .filter((item) => typeof item.delta === "number")
        .slice(0, 10)
        .map((item) => ({ rep_name: item.rep_name, delta: item.delta ?? 0 })),
    [data?.coaching_uplift]
  );

  const tagChart = useMemo(
    () => (data?.weakness_tag_uplift ?? []).slice(0, 8).map((item) => ({ ...item, delta_pct: item.delta })),
    [data?.weakness_tag_uplift]
  );

  const calibrationChart = useMemo(
    () => (data?.manager_calibration ?? []).map((item) => ({ ...item, avg_delta: item.average_override_delta ?? 0 })),
    [data?.manager_calibration]
  );

  if (loading) return <EmptyState variant="loading" message="Loading coaching lab..." />;
  if (error) return <EmptyState variant="error" message={error} onRetry={() => void loadData()} />;
  if (!data) return <EmptyState variant="empty" message="No coaching data available yet." />;

  return (
    <motion.main
      className="mx-auto max-w-7xl px-6 py-6 space-y-6"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
    >
      <header className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h1 className="text-3xl font-black tracking-tight text-ink">Coaching Lab</h1>
          <p className="mt-1 text-sm text-muted">Measure coaching uplift, review behavior, and calibration drift.</p>
        </div>
        <div className="flex rounded-2xl border border-white/35 bg-white/55 p-1">
          {PERIOD_OPTIONS.map((option) => (
            <button
              key={option.key}
              onClick={() => setPeriod(option.key)}
              className={`rounded-xl px-4 py-2 text-sm font-semibold transition ${period === option.key ? "bg-accent text-white" : "text-muted hover:bg-white/70 hover:text-ink"}`}
            >
              {option.label}
            </button>
          ))}
        </div>
      </header>

      <section className="grid gap-4 md:grid-cols-4">
        {[
          { label: "Coaching Notes", value: String(data.summary.coaching_note_count), icon: BookOpenText },
          { label: "Reviews", value: String(data.summary.review_count), icon: MessageSquareQuote },
          { label: "Override Rate", value: formatPercent(data.summary.override_rate), icon: Scale },
          {
            label: "Avg Override Δ",
            value: typeof data.summary.average_override_delta === "number" ? `${data.summary.average_override_delta >= 0 ? "+" : ""}${data.summary.average_override_delta.toFixed(1)}` : "--",
            icon: TrendingUp,
          },
        ].map((card) => (
          <div key={card.label} className="rounded-[28px] border border-white/30 bg-white/40 p-5 shadow-xl shadow-black/5 backdrop-blur-2xl">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">{card.label}</div>
                <div className="mt-3 text-3xl font-black tracking-tight text-ink">{card.value}</div>
              </div>
              <div className="rounded-2xl bg-accent/10 p-3 text-accent">
                <card.icon className="h-5 w-5" />
              </div>
            </div>
          </div>
        ))}
      </section>

      <section className="grid gap-6 xl:grid-cols-[1fr_1fr]">
        <div className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <h2 className="text-lg font-bold tracking-tight text-ink">Coaching Uplift by Rep</h2>
          <div className="mt-4 h-[300px] w-full">
            {upliftChart.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={upliftChart} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(45,90,61,0.08)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="rep_name" tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <RechartsTooltip />
                  <Bar dataKey="delta" radius={[12, 12, 0, 0]} fill="#2d5a3d" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState variant="empty" message="No before/after coaching samples yet." />
            )}
          </div>
        </div>

        <div className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <h2 className="text-lg font-bold tracking-tight text-ink">Weakness Tag Uplift</h2>
          <div className="mt-4 h-[300px] w-full">
            {tagChart.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={tagChart} layout="vertical" margin={{ top: 10, right: 10, left: 20, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(45,90,61,0.08)" strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis type="category" dataKey="tag" width={120} tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <RechartsTooltip />
                  <Bar dataKey="delta_pct" radius={[0, 12, 12, 0]} fill="#b77a13" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState variant="empty" message="No tag-level uplift yet." />
            )}
          </div>
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-[0.9fr_1.1fr]">
        <div className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <h2 className="text-lg font-bold tracking-tight text-ink">Calibration Drift</h2>
          <div className="mt-4 h-[300px] w-full">
            {calibrationChart.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={calibrationChart} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke="rgba(45,90,61,0.08)" strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="reviewer_name" tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fill: "var(--color-muted)", fontSize: 12 }} axisLine={false} tickLine={false} />
                  <RechartsTooltip />
                  <Bar dataKey="avg_delta" radius={[12, 12, 0, 0]} fill="#2d5a3d" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <EmptyState variant="empty" message="No override calibration data yet." />
            )}
          </div>
        </div>

        <div className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <h2 className="text-lg font-bold tracking-tight text-ink">Recent Coaching Notes</h2>
          <div className="mt-4 space-y-3">
            {data.recent_notes.length ? (
              data.recent_notes.map((note) => (
                <div key={note.id} className="rounded-2xl border border-white/25 bg-white/45 p-4">
                  <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                    <div>
                      <div className="text-sm font-semibold text-ink">{note.rep_name}</div>
                      <div className="mt-1 text-xs text-muted">{note.scenario_name} · {new Date(note.created_at).toLocaleString()}</div>
                      <p className="mt-3 text-sm leading-6 text-ink">{note.note}</p>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {note.weakness_tags.map((tag) => (
                          <span key={tag} className="rounded-full bg-accent-soft px-2.5 py-1 text-[11px] font-medium text-accent">
                            {tag}
                          </span>
                        ))}
                      </div>
                    </div>
                    <span className={`rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] ${note.visible_to_rep ? "bg-accent-soft text-accent" : "bg-white/70 text-muted"}`}>
                      {note.visible_to_rep ? "rep-visible" : "private"}
                    </span>
                  </div>
                </div>
              ))
            ) : (
              <EmptyState variant="empty" message="No coaching notes have been added yet." />
            )}
          </div>
        </div>
      </section>
    </motion.main>
  );
}
