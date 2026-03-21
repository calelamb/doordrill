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
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Left Column: Analytics (spanning 2 columns on lg) */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: "easeOut" }}
        className="lg:col-span-2 bg-white/50 backdrop-blur-2xl border border-white/50 shadow-xl shadow-black/5 rounded-3xl p-6 flex flex-col hover:shadow-2xl transition-all duration-300"
      >
        <h2 className="text-xl font-bold tracking-tight text-ink mb-6 flex items-center gap-2">
          <Activity className="w-6 h-6 text-accent" />
          Performance
        </h2>

        {!analytics ? (
          <p className="text-muted text-sm flex-1 flex items-center justify-center min-h-[160px]">Load manager data to see analytics.</p>
        ) : (
          <div className="grid grid-cols-2 gap-4 mb-2 flex-1">
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
                  className="bg-white/40 backdrop-blur-xl border border-white/40 rounded-2xl p-5 flex flex-col items-start gap-3 hover:bg-white/60 hover:scale-[1.02] transition-all duration-200"
                >
                  <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
                    <Icon className="w-5 h-5 text-accent" />
                  </div>
                  <strong className="text-3xl font-black tracking-tight text-ink leading-none">
                    {value}
                  </strong>
                  <span className="text-sm font-semibold text-muted">{label}</span>
                </motion.div>
              );
            })}
          </div>
        )}
      </motion.div>

      {/* Right Column: Rep Progress & Manager Actions */}
      <div className="flex flex-col gap-6 h-full">
        {/* Rep Progress Component */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.1, ease: "easeOut" }}
          className="bg-white/50 backdrop-blur-2xl border border-white/50 shadow-xl shadow-black/5 rounded-3xl p-6 hover:shadow-2xl transition-all duration-300"
        >
          <h3 className="text-sm font-bold uppercase tracking-widest text-muted mb-4 flex items-center gap-2">
            <TrendingUp className="w-4 h-4" />
            Rep Progress
          </h3>
          {repProgress ? (
            <div className="flex flex-col gap-4">
              <div className="flex justify-between items-center bg-white/40 rounded-xl px-4 py-3">
                <div className="flex flex-col items-center">
                  <span className="text-xs text-muted font-semibold uppercase tracking-wider mb-1">Sessions</span>
                  <span className="text-xl font-bold text-ink">{repProgress.session_count}</span>
                </div>
                <div className="w-px h-8 bg-border" />
                <div className="flex flex-col items-center">
                  <span className="text-xs text-muted font-semibold uppercase tracking-wider mb-1">Scored</span>
                  <span className="text-xl font-bold text-ink">{repProgress.scored_session_count}</span>
                </div>
                <div className="w-px h-8 bg-border" />
                <div className="flex flex-col items-center">
                  <span className="text-xs text-muted font-semibold uppercase tracking-wider mb-1">Avg</span>
                  <span className="text-xl font-black text-accent">{repProgress.average_score ?? "--"}</span>
                </div>
              </div>
              <ul className="flex flex-col gap-1.5 mt-2">
                {repProgress.latest_sessions.slice(0, 4).map((item, index) => (
                  <motion.li
                    key={item.session_id}
                    initial={{ opacity: 0, x: -6 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.25, delay: index * 0.04 }}
                    className="flex flex-row items-center justify-between py-2 px-3 rounded-xl bg-white/30 hover:bg-white/70 transition-colors duration-200 cursor-default"
                  >
                    <span className="text-sm font-medium text-ink/80">{item.session_id.slice(0, 8)}</span>
                    <span className="bg-accent/15 text-accent font-bold rounded-lg px-2.5 py-1 text-xs outline outline-1 outline-accent/20">
                      {item.overall_score ?? "--"}
                    </span>
                  </motion.li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-muted text-sm min-h-[100px] flex items-center">Select a session to load rep progress.</p>
          )}
        </motion.div>

        {/* Manager Actions Component */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.2, ease: "easeOut" }}
          className="bg-white/50 backdrop-blur-2xl border border-white/50 shadow-xl shadow-black/5 rounded-3xl p-6 flex-1 hover:shadow-2xl transition-all duration-300 relative overflow-hidden"
        >
          <div className="absolute top-0 right-0 w-32 h-32 bg-accent/5 rounded-bl-full pointer-events-none" />
          <h3 className="text-sm font-bold uppercase tracking-widest text-muted mb-4 relative z-10">
            Recent Actions
          </h3>
          <ul className="flex flex-col gap-2 relative z-10">
            {actions.length === 0 ? (
              <li className="text-muted text-sm py-4 list-none text-center">No recent actions logged.</li>
            ) : null}
            {actions.slice(0, 5).map((action, index) => (
              <motion.li
                key={action.id}
                initial={{ opacity: 0, x: -6 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ duration: 0.25, delay: index * 0.04 }}
                className="group flex flex-col py-2.5 px-3 rounded-xl hover:bg-white/60 transition-colors duration-200 list-none cursor-default"
              >
                <div className="flex items-center gap-3">
                  <span className="w-2 h-2 rounded-full bg-accent group-hover:scale-125 transition-transform" />
                  <span className="text-sm font-bold text-ink flex-1">{action.action_type}</span>
                </div>
                <div className="flex items-center gap-1.5 ml-5 mt-1 text-xs text-muted/80 font-medium">
                  <Clock className="w-3.5 h-3.5" />
                  {new Date(action.occurred_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </div>
              </motion.li>
            ))}
          </ul>
        </motion.div>
      </div>
    </div>
  );
}
