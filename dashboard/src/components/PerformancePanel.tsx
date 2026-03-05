import type { ManagerActionLog, ManagerAnalytics, RepProgress } from "../lib/types";

type Props = {
  analytics: ManagerAnalytics | null;
  repProgress: RepProgress | null;
  actions: ManagerActionLog[];
};

export function PerformancePanel({ analytics, repProgress, actions }: Props) {
  return (
    <div className="panel perf-panel">
      <h2>Performance</h2>

      {!analytics ? (
        <p className="muted">Load manager data to see analytics.</p>
      ) : (
        <div className="metrics-grid">
          <div className="metric-card">
            <span>Assignments</span>
            <strong>{analytics.assignment_count}</strong>
          </div>
          <div className="metric-card">
            <span>Sessions</span>
            <strong>{analytics.sessions_count}</strong>
          </div>
          <div className="metric-card">
            <span>Completion Rate</span>
            <strong>{Math.round(analytics.completion_rate * 100)}%</strong>
          </div>
          <div className="metric-card">
            <span>Avg Score</span>
            <strong>{analytics.average_score ?? "--"}</strong>
          </div>
        </div>
      )}

      <h3>Rep Progress Snapshot</h3>
      {repProgress ? (
        <div className="rep-progress-block">
          <p>
            Sessions: <strong>{repProgress.session_count}</strong> | Scored: <strong>{repProgress.scored_session_count}</strong> |
            Avg: <strong>{repProgress.average_score ?? "--"}</strong>
          </p>
          <ul className="mini-list">
            {repProgress.latest_sessions.slice(0, 6).map((item) => (
              <li key={item.session_id}>
                <span>{item.session_id.slice(0, 8)}</span>
                <span>{item.overall_score ?? "--"}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="muted">Select a session to load rep progress.</p>
      )}

      <h3>Manager Actions</h3>
      <ul className="mini-list actions">
        {actions.length === 0 ? <li className="muted">No recent actions.</li> : null}
        {actions.slice(0, 8).map((action) => (
          <li key={action.id}>
            <span>{action.action_type}</span>
            <small>{new Date(action.occurred_at).toLocaleTimeString()}</small>
          </li>
        ))}
      </ul>
    </div>
  );
}
