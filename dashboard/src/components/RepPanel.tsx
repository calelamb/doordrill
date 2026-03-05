import { useEffect, useRef, useState } from "react";

import { createRepSession, fetchRepAssignments, fetchRepSession, getRepSessionWsUrl } from "../lib/api";
import type { RepAssignment, RepSessionDetail } from "../lib/types";

type LiveEvent = {
  id: number;
  type: string;
  at: string;
  payload: Record<string, unknown>;
};

const MAX_LIVE_EVENTS = 120;

export function RepPanel() {
  const socketRef = useRef<WebSocket | null>(null);
  const sequenceRef = useRef(1);
  const eventIndexRef = useRef(1);

  const [repId, setRepId] = useState("");
  const [assignments, setAssignments] = useState<RepAssignment[]>([]);
  const [activeSession, setActiveSession] = useState<RepSessionDetail | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [liveConnected, setLiveConnected] = useState(false);
  const [liveStatus, setLiveStatus] = useState("disconnected");
  const [liveEvents, setLiveEvents] = useState<LiveEvent[]>([]);
  const [utterance, setUtterance] = useState("");
  const [aiLiveText, setAiLiveText] = useState("");
  const [lastTranscript, setLastTranscript] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function nextSequence() {
    const seq = sequenceRef.current;
    sequenceRef.current += 1;
    return seq;
  }

  function addLiveEvent(type: string, payload: Record<string, unknown>) {
    const event: LiveEvent = {
      id: eventIndexRef.current++,
      type,
      at: new Date().toISOString(),
      payload
    };
    setLiveEvents((items) => [event, ...items].slice(0, MAX_LIVE_EVENTS));
  }

  function closeSocket(sendSessionEnd: boolean) {
    const ws = socketRef.current;
    if (!ws) {
      return;
    }
    if (sendSessionEnd && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "client.session.end", sequence: nextSequence(), payload: {} }));
    }
    ws.close();
    socketRef.current = null;
    setLiveConnected(false);
    setLiveStatus("disconnected");
  }

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

  async function refreshActiveSession() {
    if (!repId || !activeSessionId) {
      return;
    }
    const detail = await fetchRepSession(repId, activeSessionId);
    setActiveSession(detail);
  }

  async function startSession(assignment: RepAssignment) {
    setLoading(true);
    setError(null);
    try {
      closeSocket(false);
      setLiveEvents([]);
      setAiLiveText("");
      setLastTranscript("");
      sequenceRef.current = 1;

      const session = await createRepSession(repId, assignment.id, assignment.scenario_id);
      const detail = await fetchRepSession(repId, session.id);
      setActiveSessionId(session.id);
      setActiveSession(detail);
      await loadAssignments();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start session");
    } finally {
      setLoading(false);
    }
  }

  function connectLiveSession() {
    if (!activeSessionId) {
      return;
    }
    closeSocket(false);

    const ws = new WebSocket(getRepSessionWsUrl(activeSessionId));
    socketRef.current = ws;
    setLiveStatus("connecting");
    setError(null);

    ws.onopen = () => {
      setLiveConnected(true);
      setLiveStatus("connected");
      addLiveEvent("client.connected", { session_id: activeSessionId });
    };

    ws.onclose = () => {
      setLiveConnected(false);
      setLiveStatus("disconnected");
      addLiveEvent("client.disconnected", { session_id: activeSessionId });
    };

    ws.onerror = () => {
      setError("WebSocket connection error");
      setLiveStatus("error");
    };

    ws.onmessage = (event) => {
      let message: { type?: string; payload?: Record<string, unknown> };
      try {
        message = JSON.parse(event.data) as { type?: string; payload?: Record<string, unknown> };
      } catch {
        return;
      }
      const eventType = message.type ?? "unknown";
      const payload = message.payload ?? {};
      addLiveEvent(eventType, payload);

      if (eventType === "server.ai.text.delta") {
        const token = String(payload.token ?? "");
        setAiLiveText((text) => `${text}${token}`);
      }

      if (eventType === "server.stt.final") {
        setLastTranscript(String(payload.text ?? ""));
      }

      if (eventType === "server.session.state" && payload.state === "ai_speaking") {
        setAiLiveText("");
      }

      if (eventType === "server.turn.committed") {
        void refreshActiveSession();
      }

      if (eventType === "server.error") {
        setError(String(payload.message ?? "Session error"));
      }
    };
  }

  function sendUtterance() {
    const ws = socketRef.current;
    const text = utterance.trim();
    if (!ws || ws.readyState !== WebSocket.OPEN || !text) {
      return;
    }
    const durationMs = Math.max(350, Math.min(4000, text.length * 45));

    ws.send(JSON.stringify({ type: "client.vad.state", sequence: nextSequence(), payload: { speaking: true } }));
    ws.send(
      JSON.stringify({
        type: "client.audio.chunk",
        sequence: nextSequence(),
        payload: {
          transcript_hint: text,
          codec: "opus",
          utterance_duration_ms: durationMs
        }
      })
    );
    ws.send(JSON.stringify({ type: "client.vad.state", sequence: nextSequence(), payload: { speaking: false } }));

    addLiveEvent("client.audio.chunk", { transcript_hint: text, utterance_duration_ms: durationMs });
    setUtterance("");
  }

  async function endLiveSession() {
    closeSocket(true);
    await refreshActiveSession();
    await loadAssignments();
  }

  useEffect(() => {
    return () => closeSocket(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

      <section className="layout secondary">
        <div className="panel">
          <div className="replay-header">
            <h2>Live Drill Console</h2>
            <span className="pill">{liveStatus}</span>
          </div>
          <div className="action-row">
            <button onClick={connectLiveSession} disabled={!activeSessionId || liveConnected}>
              Connect
            </button>
            <button onClick={() => void endLiveSession()} disabled={!activeSessionId || !liveConnected}>
              End Session
            </button>
          </div>
          <label>
            Rep utterance
            <textarea
              rows={3}
              value={utterance}
              onChange={(e) => setUtterance(e.target.value)}
              placeholder="Type what the rep says, then send as a live turn..."
            />
          </label>
          <div className="action-row">
            <button onClick={sendUtterance} disabled={!liveConnected || !utterance.trim()}>
              Send Turn
            </button>
          </div>
          <p>
            Last transcript: <strong>{lastTranscript || "--"}</strong>
          </p>
          <p>
            AI response stream: <strong>{aiLiveText || "--"}</strong>
          </p>
        </div>

        <div className="panel">
          <h2>Live Event Stream</h2>
          <ul className="timeline">
            {liveEvents.length === 0 ? <li className="muted">No events yet.</li> : null}
            {liveEvents.map((event) => (
              <li key={event.id}>
                <span>{event.id}</span>
                <strong>{event.type}</strong>
                <small>{new Date(event.at).toLocaleTimeString()}</small>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </main>
  );
}
