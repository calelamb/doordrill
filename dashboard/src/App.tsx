import { useEffect, useState } from "react";

import { FeedList } from "./components/FeedList";
import { ReplayPanel } from "./components/ReplayPanel";
import { fetchManagerFeed, fetchReplay } from "./lib/api";
import type { FeedItem, ReplayResponse } from "./lib/types";

export function App() {
  const [managerId, setManagerId] = useState("");
  const [feed, setFeed] = useState<FeedItem[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [replay, setReplay] = useState<ReplayResponse | null>(null);
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
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch replay");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (activeSessionId) {
      void refreshReplay(activeSessionId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeSessionId]);

  return (
    <main className="app-shell">
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
    </main>
  );
}
