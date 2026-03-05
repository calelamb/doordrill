import { useCallback, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import { BellRing, History, ShieldAlert } from "lucide-react";

import { EmptyState } from "../components/shared/EmptyState";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { fetchManagerActions, fetchManagerAlerts } from "../lib/api";
import type { AlertItem, ManagerActionLog } from "../lib/types";

function severityTone(alert: AlertItem) {
  if (alert.severity === "high") return "border-error/15 bg-error/[0.06] text-error";
  if (alert.severity === "medium") return "border-amber-400/20 bg-amber-100/40 text-amber-900";
  return "border-accent/15 bg-accent-soft/35 text-accent";
}

export function ActionsPage() {
  const navigate = useNavigate();
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";

  const [alerts, setAlerts] = useState<AlertItem[]>([]);
  const [actions, setActions] = useState<ManagerActionLog[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    if (!managerId) return;
    setLoading(true);
    setError(null);
    try {
      const [alertData, actionData] = await Promise.all([
        fetchManagerAlerts(managerId, { period: "30" }),
        fetchManagerActions(managerId, 50),
      ]);
      setAlerts(alertData);
      setActions(actionData);
    } catch (err) {
      if (isAuthError(err)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load manager activity");
    } finally {
      setLoading(false);
    }
  }, [managerId, navigate]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  if (loading) return <EmptyState variant="loading" message="Loading manager activity..." />;
  if (error) return <EmptyState variant="error" message={error} onRetry={() => void loadData()} />;

  return (
    <motion.main
      className="mx-auto max-w-7xl px-6 py-6 space-y-6"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
    >
      <header>
        <h1 className="text-3xl font-black tracking-tight text-ink">Activity Center</h1>
        <p className="mt-1 text-sm text-muted">Operational alerts and the manager audit trail in one place.</p>
      </header>

      <section className="grid gap-6 xl:grid-cols-[0.85fr_1.15fr]">
        <div className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <div className="mb-4 flex items-center gap-2">
            <BellRing className="h-4 w-4 text-accent" />
            <h2 className="text-lg font-bold tracking-tight text-ink">Alerts</h2>
          </div>
          <div className="space-y-3">
            {alerts.length ? alerts.map((alert) => (
              <button
                key={alert.id}
                onClick={() => {
                  if (alert.session_id) navigate(`/manager/sessions/${alert.session_id}/replay`);
                  else if (alert.rep_id) navigate(`/manager/reps/${alert.rep_id}/progress`);
                }}
                className={`w-full rounded-2xl border px-4 py-4 text-left transition hover:translate-x-0.5 ${severityTone(alert)}`}
              >
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold">{alert.title}</div>
                    <p className="mt-1 text-sm leading-6 opacity-85">{alert.description}</p>
                  </div>
                  <span className="rounded-full bg-white/60 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em]">
                    {alert.severity}
                  </span>
                </div>
              </button>
            )) : <EmptyState variant="empty" message="No active alerts right now." />}
          </div>
        </div>

        <div className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <div className="mb-4 flex items-center gap-2">
            <History className="h-4 w-4 text-accent" />
            <h2 className="text-lg font-bold tracking-tight text-ink">Manager Audit Trail</h2>
          </div>
          <div className="space-y-3">
            {actions.length ? actions.map((action) => (
              <div key={action.id} className="rounded-2xl border border-white/25 bg-white/45 p-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="rounded-full bg-accent-soft px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-accent">
                        {action.action_type}
                      </span>
                      <span className="rounded-full bg-white/65 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted">
                        {action.target_type}
                      </span>
                    </div>
                    <p className="mt-3 text-sm leading-6 text-ink">{action.summary ?? "No summary recorded."}</p>
                  </div>
                  <div className="text-right text-xs text-muted">
                    <div>{new Date(action.occurred_at).toLocaleString()}</div>
                    <div className="mt-1 font-mono text-[11px]">{action.target_id.slice(0, 12)}</div>
                  </div>
                </div>
              </div>
            )) : (
              <div className="rounded-2xl border border-dashed border-white/25 bg-white/35 px-6 py-10">
                <EmptyState variant="empty" message="No manager actions recorded yet." />
              </div>
            )}
          </div>
        </div>
      </section>

      <section className="rounded-[32px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-4 w-4 text-accent" />
          <h2 className="text-lg font-bold tracking-tight text-ink">Operational Focus</h2>
        </div>
        <p className="mt-3 max-w-3xl text-sm leading-7 text-muted">
          Use this page as the triage queue. Alerts surface what needs attention now; the audit trail shows what has already been reviewed, overridden, coached, or reassigned.
        </p>
      </section>
    </motion.main>
  );
}
