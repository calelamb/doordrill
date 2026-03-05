import { useEffect, useState } from "react";

import { FeedList } from "./components/FeedList";
import { PerformancePanel } from "./components/PerformancePanel";
import { ReplayPanel } from "./components/ReplayPanel";
import { RepPanel } from "./components/RepPanel";
import { fetchManagerActions, fetchManagerAnalytics, fetchManagerFeed, fetchReplay, fetchRepProgress } from "./lib/api";
import type { FeedItem, ManagerActionLog, ManagerAnalytics, ReplayResponse, RepProgress } from "./lib/types";

export function App() {
  const [mode, setMode] = useState<"manager" | "rep">("manager");
  const [managerId, setManagerId] = useState("");
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [replay, setReplay] = useState<ReplayResponse | null>(null);
  const [analytics, setAnalytics] = useState<ManagerAnalytics | null>(null);
  const [repProgress, setRepProgress] = useState<RepProgress | null>(null);
  const [actions, setActions] = useState<ManagerActionLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function refreshFeed() {
    if (!managerId) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const items = await fetchManagerFeed(managerId);
      setFeed(items);
      const [analyticsData, actionData] = await Promise.all([
        fetchManagerAnalytics(managerId),
        fetchManagerActions(managerId)
      ]);
      setAnalytics(analyticsData);
      setActions(actionData);
      if (!activeSessionId && items[0]) {
        setActiveSessionId(items[0].session_id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch feed");
    } finally {
      setLoading(false);
    }
  }

  async function refreshReplay(sessionId: string) {
    if (!managerId) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await fetchReplay(managerId, sessionId);
      setReplay(data);
      const feedItem = feed.find((item) => item.session_id === sessionId);
      if (feedItem) {
        const progress = await fetchRepProgress(managerId, feedItem.rep_id);
        setRepProgress(progress);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch replay");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (mode === "manager" && activeSessionId) {
      void refreshReplay(activeSessionId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSessionId, mode]);

  if (mode === "rep") {
    return (
      <>
        <div className="mode-switch">
          <button onClick={() => setMode("manager")} className="ghost-btn">
            Manager Mode
          </button>
          <button className="active-btn">Rep Mode</button>
        </div>
        <RepPanel />
      </>
    );
  }

  return (
    <main className="app-shell">
      <div className="mode-switch">
        <button className="active-btn">Manager Mode</button>
        <button onClick={() => setMode("rep")} className="ghost-btn">
          Rep Mode
        </button>
      </div>

      <header className="topbar">
        <h1>DoorDrill Manager Console</h1>
        <div className="toolbar">
          <input
            placeholder="Manager ID"
            value={managerId}
            onChange={(e) => setManagerId(e.target.value)}
          />
          <button onClick={() => void refreshFeed()} disabled={!managerId || loading}>
            {loading ? "Loading..." : "Load Feed"}
          </button>
        </div>
      </header>

      {error ? <p className="error">{error}</p> : null}

      <section className="layout">
        <FeedList
          items={feed}
          activeSessionId={activeSessionId}
          onSelect={(sessionId) => {
            setActiveSessionId(sessionId);
            void refreshReplay(sessionId);
          }}
        />
        <ReplayPanel
          managerId={managerId}
          replay={replay}
          onActionDone={async () => {
            await refreshFeed();
            if (activeSessionId) {
              await refreshReplay(activeSessionId);
            }
          }}
        />
      </section>
      <section className="layout secondary">
        <PerformancePanel analytics={analytics} repProgress={repProgress} actions={actions} />
      </section>
    </main>
  );
}
