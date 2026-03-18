import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import {
  Activity,
  ClipboardList,
  Loader2,
  MessageCircle,
  Mic,
  Play,
  Power,
  Radio,
  Send,
  User,
  Wifi,
  WifiOff,
  Zap,
} from "lucide-react";

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
  const endSessionResolverRef = useRef<(() => void) | null>(null);
  const endSessionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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

  function resolvePendingSessionEnd() {
    if (endSessionTimerRef.current) {
      clearTimeout(endSessionTimerRef.current);
      endSessionTimerRef.current = null;
    }
    const resolver = endSessionResolverRef.current;
    endSessionResolverRef.current = null;
    if (resolver) {
      resolver();
    }
  }

  async function waitForSessionEnded(timeoutMs = 4000) {
    const ws = socketRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return;
    }
    await new Promise<void>((resolve) => {
      endSessionResolverRef.current = () => {
        endSessionResolverRef.current = null;
        resolve();
      };
      endSessionTimerRef.current = setTimeout(() => {
        resolvePendingSessionEnd();
      }, timeoutMs);
    });
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
      resolvePendingSessionEnd();
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

      if (eventType === "server.session.state" && payload.state === "ended") {
        resolvePendingSessionEnd();
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
    const ws = socketRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "client.session.end", sequence: nextSequence(), payload: {} }));
      await waitForSessionEnded();
    }
    closeSocket(false);
    await refreshActiveSession();
    await loadAssignments();
  }

  useEffect(() => {
    return () => closeSocket(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <main className="min-h-screen bg-gradient-to-br from-accent-soft/40 via-white/60 to-accent-soft/30 p-6 space-y-6">
      {/* Header */}
      <motion.header
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6 flex items-center justify-between"
      >
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-accent/10 flex items-center justify-center">
            <Radio className="w-5 h-5 text-accent" />
          </div>
          <h1 className="text-xl font-bold tracking-tight text-ink">DoorDrill Rep Console</h1>
        </div>
        <div className="flex items-center gap-3">
          <div className="relative">
            <User className="w-4 h-4 text-muted absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              placeholder="Rep ID"
              value={repId}
              onChange={(e) => setRepId(e.target.value)}
              className="bg-white/50 backdrop-blur-xl border border-white/30 rounded-xl pl-9 pr-3 py-2.5 text-sm text-ink placeholder:text-muted/50 focus:ring-2 focus:ring-accent focus:border-accent outline-none transition-all w-48"
            />
          </div>
          <button
            onClick={() => void loadAssignments()}
            disabled={!repId || loading}
            className="flex items-center gap-2 bg-accent text-white rounded-xl px-4 py-2.5 text-sm font-medium hover:bg-accent-hover transition-colors disabled:opacity-50 cursor-pointer disabled:cursor-not-allowed"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <ClipboardList className="w-4 h-4" />
            )}
            {loading ? "Loading..." : "Load Assignments"}
          </button>
        </div>
      </motion.header>

      {/* Error Banner */}
      {error ? (
        <motion.div
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-red-50/80 backdrop-blur-xl border border-red-200/50 rounded-xl px-4 py-3 flex items-center gap-2"
        >
          <Zap className="w-4 h-4 text-red-500 shrink-0" />
          <p className="text-sm text-red-700 font-medium">{error}</p>
        </motion.div>
      ) : null}

      {/* Assignments + Latest Session Row */}
      <div className="grid grid-cols-2 gap-6">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6"
        >
          <div className="flex items-center gap-2 mb-4">
            <ClipboardList className="w-4.5 h-4.5 text-accent" />
            <h2 className="text-base font-semibold tracking-tight text-ink">Assignments</h2>
          </div>
          <ul className="space-y-2">
            {assignments.length === 0 ? (
              <li className="text-muted text-sm py-4 text-center">No assignments loaded.</li>
            ) : null}
            {assignments.map((assignment) => (
              <li
                key={assignment.id}
                className="flex items-center justify-between bg-white/40 backdrop-blur-xl border border-white/20 rounded-xl px-4 py-3 hover:bg-white/60 transition-colors"
              >
                <div>
                  <strong className="text-sm font-semibold text-ink">{assignment.id.slice(0, 8)}</strong>
                  <div className="text-xs text-muted mt-0.5">{assignment.status}</div>
                </div>
                <button
                  onClick={() => void startSession(assignment)}
                  disabled={loading || !repId}
                  className="flex items-center gap-1.5 bg-accent text-white rounded-xl px-3 py-1.5 text-xs font-medium hover:bg-accent-hover transition-colors disabled:opacity-50 cursor-pointer disabled:cursor-not-allowed"
                >
                  <Play className="w-3 h-3" />
                  Start
                </button>
              </li>
            ))}
          </ul>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6"
        >
          <div className="flex items-center gap-2 mb-4">
            <Activity className="w-4.5 h-4.5 text-accent" />
            <h2 className="text-base font-semibold tracking-tight text-ink">Latest Session</h2>
          </div>
          {!activeSession ? (
            <p className="text-muted text-sm py-4 text-center">Start a session to load feedback.</p>
          ) : null}
          {activeSession ? (
            <div className="space-y-3">
              <div className="bg-white/40 backdrop-blur-xl border border-white/20 rounded-xl px-4 py-3">
                <p className="text-sm text-ink">
                  Session <strong className="font-semibold">{activeSession.session.id.slice(0, 8)}</strong>
                  <span className="mx-2 text-muted">·</span>
                  <span className="bg-accent/10 text-accent text-xs font-medium rounded-full px-2 py-0.5">
                    {activeSession.session.status}
                  </span>
                </p>
              </div>
              <div className="flex items-center gap-3 bg-white/40 backdrop-blur-xl border border-white/20 rounded-xl px-4 py-3">
                <span className="text-xs text-muted font-medium uppercase tracking-wide">Score</span>
                <strong className="text-2xl font-bold text-ink">
                  {activeSession.scorecard?.overall_score ?? "--"}
                </strong>
              </div>
              <p className="text-sm text-muted leading-relaxed px-1">
                {activeSession.scorecard?.ai_summary ?? "Scorecard pending."}
              </p>
            </div>
          ) : null}
        </motion.div>
      </div>

      {/* Live Drill Console + Event Stream Row */}
      <div className="grid grid-cols-2 gap-6">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6 space-y-5"
        >
          {/* Console Header */}
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Mic className="w-4.5 h-4.5 text-accent" />
              <h2 className="text-base font-semibold tracking-tight text-ink">Live Drill Console</h2>
            </div>
            <span className="flex items-center gap-2 text-xs font-medium rounded-full px-3 py-1 bg-white/50 border border-white/30">
              <span
                className={`w-2 h-2 rounded-full ${
                  liveStatus === "connected"
                    ? "bg-green-500 animate-pulse"
                    : liveStatus === "error"
                      ? "bg-red-500"
                      : "bg-gray-400"
                }`}
              />
              <span className={
                liveStatus === "connected"
                  ? "text-green-700"
                  : liveStatus === "error"
                    ? "text-red-600"
                    : "text-muted"
              }>
                {liveStatus}
              </span>
            </span>
          </div>

          {/* Connect / End Buttons */}
          <div className="flex gap-3">
            <button
              onClick={connectLiveSession}
              disabled={!activeSessionId || liveConnected}
              className="flex items-center gap-2 bg-accent text-white rounded-xl px-4 py-2.5 text-sm font-medium hover:bg-accent-hover transition-colors disabled:opacity-50 cursor-pointer disabled:cursor-not-allowed"
            >
              <Wifi className="w-4 h-4" />
              Connect
            </button>
            <button
              onClick={() => void endLiveSession()}
              disabled={!activeSessionId || !liveConnected}
              className="flex items-center gap-2 bg-white/50 backdrop-blur-xl border border-white/30 text-ink rounded-xl px-4 py-2.5 text-sm font-medium hover:bg-red-50 hover:border-red-200/50 hover:text-red-700 transition-colors disabled:opacity-50 cursor-pointer disabled:cursor-not-allowed"
            >
              <Power className="w-4 h-4" />
              End Session
            </button>
          </div>

          {/* Utterance Input */}
          <div>
            <label className="block text-xs font-medium text-muted mb-1.5">Rep utterance</label>
            <textarea
              rows={3}
              value={utterance}
              onChange={(e) => setUtterance(e.target.value)}
              placeholder="Type what the rep says, then send as a live turn..."
              className="w-full bg-white/50 backdrop-blur-xl border border-white/30 rounded-xl px-3 py-2.5 text-sm text-ink placeholder:text-muted/50 focus:ring-2 focus:ring-accent focus:border-accent focus:shadow-lg focus:shadow-accent/10 outline-none transition-all resize-none"
            />
          </div>
          <div className="flex gap-3">
            <button
              onClick={sendUtterance}
              disabled={!liveConnected || !utterance.trim()}
              className="flex items-center gap-2 bg-accent text-white rounded-xl px-4 py-2.5 text-sm font-medium hover:bg-accent-hover transition-colors disabled:opacity-50 cursor-pointer disabled:cursor-not-allowed"
            >
              <Send className="w-4 h-4" />
              Send Turn
            </button>
          </div>

          {/* Live Info */}
          <div className="border-t border-white/20 pt-4 space-y-2">
            <div className="bg-white/30 rounded-xl px-4 py-2.5">
              <span className="text-xs text-muted font-medium uppercase tracking-wide">Last transcript</span>
              <strong className="block text-sm text-ink mt-0.5">{lastTranscript || "--"}</strong>
            </div>
            <div className="bg-white/30 rounded-xl px-4 py-2.5">
              <span className="text-xs text-muted font-medium uppercase tracking-wide">AI response stream</span>
              <strong className="block text-sm text-ink mt-0.5">{aiLiveText || "--"}</strong>
            </div>
          </div>
        </motion.div>

        {/* Live Event Stream */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-white/40 backdrop-blur-2xl border border-white/30 shadow-xl shadow-black/5 rounded-2xl p-6"
        >
          <div className="flex items-center gap-2 mb-4">
            <MessageCircle className="w-4.5 h-4.5 text-accent" />
            <h2 className="text-base font-semibold tracking-tight text-ink">Live Event Stream</h2>
          </div>
          <ul className="space-y-1 max-h-[28rem] overflow-y-auto pr-1">
            {liveEvents.length === 0 ? (
              <li className="text-muted text-sm py-4 text-center">No events yet.</li>
            ) : null}
            {liveEvents.map((event, index) => (
              <li
                key={event.id}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm ${
                  index % 2 === 0 ? "bg-white/20" : "bg-white/10"
                }`}
              >
                <span className="text-xs text-muted font-mono w-6 text-right shrink-0">{event.id}</span>
                <strong className="font-mono text-xs text-ink truncate flex-1">{event.type}</strong>
                <small className="text-xs text-muted shrink-0">{new Date(event.at).toLocaleTimeString()}</small>
              </li>
            ))}
          </ul>
        </motion.div>
      </div>
    </main>
  );
}
