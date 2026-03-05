import type { ManagerActionLog, ManagerAnalytics, RepProgress } from "../lib/types";
import { motion } from "framer-motion";
import { ClipboardList, Monitor, TrendingUp, Star, Activity, Clock } from "lucide-react";

type Props = {
  analytics: ManagerAnalytics | null;
  repProgress: RepProgress | null;
  actions: ManagerActionLog[];
};

const metricIcons = [
  { icon: ClipboardList, label: "Assignments", key: "assignment_count" as const },
  { icon: Monitor, label: "Sessions", key: "sessions_count" as const },
  { icon: TrendingUp, label: "Completion Rate", key: "completion_rate" as const },
  { icon: Star, label: "Avg Score", key: "average_score" as const },
];

export function PerformancePanel({ analytics, repProgress, actions }: Props) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: "easeOut" }}
      className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6"
    >
      <h2 className="text-lg font-bold tracking-tight text-ink mb-5 flex items-center gap-2">
        <Activity className="w-5 h-5 text-accent" />
        Performance
      </h2>

      {!analytics ? (
        <p className="text-muted text-sm">Load manager data to see analytics.</p>
      ) : (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {metricIcons.map(({ icon: Icon, label, key }, index) => {
            let value: string;
            if (key === "completion_rate") {
              value = `${Math.round(analytics.completion_rate * 100)}%`;
            } else if (key === "average_score") {
              value = String(analytics.average_score ?? "--");
            } else {
              value = String(analytics[key]);
            }

            return (
              <motion.div
                key={key}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3, delay: index * 0.06 }}
                className="bg-white/30 backdrop-blur-xl border border-white/20 rounded-xl p-4 flex flex-col items-start gap-2"
              >
                <div className="w-8 h-8 rounded-lg bg-accent/10 flex items-center justify-center">
                  <Icon className="w-4 h-4 text-accent" />
                </div>
                <strong className="text-2xl font-bold tracking-tight text-ink leading-none">
                  {value}
                </strong>
                <span className="text-xs font-medium text-muted">{label}</span>
              </motion.div>
            );
          })}
        </div>
      )}

      <h3 className="text-sm font-semibold uppercase tracking-wider text-muted mb-3 mt-6">
        Rep Progress Snapshot
      </h3>
      {repProgress ? (
        <div className="bg-white/30 backdrop-blur-xl border border-white/20 rounded-xl p-4 mb-6">
          <div className="flex flex-wrap gap-4 text-sm text-ink mb-3">
            <span>
              Sessions: <strong className="font-semibold">{repProgress.session_count}</strong>
            </span>
            <span className="text-muted">|</span>
            <span>
              Scored: <strong className="font-semibold">{repProgress.scored_session_count}</strong>
            </span>
            <span className="text-muted">|</span>
            <span>
              Avg: <strong className="font-semibold">{repProgress.average_score ?? "--"}</strong>
            </span>
          </div>
          <ul className="flex flex-col gap-2">
            {repProgress.latest_sessions.slice(0, 6).map((item, index) => (
              <motion.li
                key={item.session_id}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.25, delay: index * 0.04 }}
                className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-white/40 transition-colors duration-150 list-none"
              >
                <span className="text-sm text-ink font-mono">{item.session_id.slice(0, 8)}</span>
                <span className="bg-accent/10 text-accent font-semibold rounded-full px-2.5 py-0.5 text-xs">
                  {item.overall_score ?? "--"}
                </span>
              </motion.li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="text-muted text-sm mb-6">Select a session to load rep progress.</p>
      )}

      <h3 className="text-sm font-semibold uppercase tracking-wider text-muted mb-3">
        Manager Actions
      </h3>
      <ul className="flex flex-col gap-1">
        {actions.length === 0 ? (
          <li className="text-muted text-sm py-2 list-none">No recent actions.</li>
        ) : null}
        {actions.slice(0, 8).map((action, index) => (
          <motion.li
            key={action.id}
            initial={{ opacity: 0, x: -6 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ duration: 0.25, delay: index * 0.04 }}
            className="flex items-center gap-3 py-2 px-2 rounded-lg hover:bg-white/40 transition-colors duration-150 list-none"
          >
            <span className="relative flex items-center justify-center">
              <span className="w-2 h-2 rounded-full bg-accent" />
              {index < actions.slice(0, 8).length - 1 && (
                <span className="absolute top-3 left-1/2 -translate-x-1/2 w-px h-4 bg-accent/20" />
              )}
            </span>
            <span className="text-sm font-medium text-ink flex-1">{action.action_type}</span>
            <span className="text-xs text-muted flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {new Date(action.occurred_at).toLocaleTimeString()}
            </span>
          </motion.li>
        ))}
      </ul>
    </motion.div>
  );
}
