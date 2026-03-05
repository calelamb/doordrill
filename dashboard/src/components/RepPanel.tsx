import { useState } from "react";

import { createRepSession, fetchRepAssignments, fetchRepSession } from "../lib/api";
import type { RepAssignment, RepSessionDetail } from "../lib/types";

export function RepPanel() {
  const [repId, setRepId] = useState("");
  const [assignments, setAssignments] = useState<RepAssignment[]>([]);
  const [activeSession, setActiveSession] = useState<RepSessionDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadAssignments() {
    if (!repId) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const items = await fetchRepAssignments(repId);
      setAssignments(items);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load rep assignments");
    } finally {
      setLoading(false);
    }
  }

  async function startSession(assignment: RepAssignment) {
    setLoading(true);
    setError(null);
    try {
      const session = await createRepSession(repId, assignment.id, assignment.scenario_id);
      const detail = await fetchRepSession(repId, session.id);
      setActiveSession(detail);
      await loadAssignments();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start session");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <h1>DoorDrill Rep Console</h1>
        <div className="toolbar">
          <input placeholder="Rep ID" value={repId} onChange={(e) => setRepId(e.target.value)} />
          <button onClick={() => void loadAssignments()} disabled={!repId || loading}>
            {loading ? "Loading..." : "Load Assignments"}
          </button>
        </div>
      </header>

      {error ? <p className="error">{error}</p> : null}

      <section className="layout secondary">
        <div className="panel">
          <h2>Assignments</h2>
          <ul className="mini-list">
            {assignments.length === 0 ? <li className="muted">No assignments loaded.</li> : null}
            {assignments.map((assignment) => (
              <li key={assignment.id}>
                <div>
                  <strong>{assignment.id.slice(0, 8)}</strong>
                  <div className="muted">{assignment.status}</div>
                </div>
                <button onClick={() => void startSession(assignment)} disabled={loading || !repId}>
                  Start
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="panel">
          <h2>Latest Session</h2>
          {!activeSession ? <p className="muted">Start a session to load feedback.</p> : null}
          {activeSession ? (
            <>
              <p>
                Session <strong>{activeSession.session.id.slice(0, 8)}</strong> · {activeSession.session.status}
              </p>
              <p>
                Score: <strong>{activeSession.scorecard?.overall_score ?? "--"}</strong>
              </p>
              <p className="muted">{activeSession.scorecard?.ai_summary ?? "Scorecard pending."}</p>
            </>
          ) : null}
        </div>
      </section>
    </main>
  );
}
