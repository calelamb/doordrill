import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { LayoutDashboard, UserCog, Loader2, AlertCircle, Search } from "lucide-react";

import { FeedList } from "./components/FeedList";
import { PerformancePanel } from "./components/PerformancePanel";
import { ReplayPanel } from "./components/ReplayPanel";
import { RepPanel } from "./components/RepPanel";
import { fetchManagerActions, fetchManagerAnalytics, fetchManagerFeed, fetchReplay, fetchRepProgress } from "./lib/api";
import type { FeedItem, ManagerActionLog, ManagerAnalytics, ReplayResponse, RepProgress } from "./lib/types";

const fadeIn = {
  initial: { opacity: 0, scale: 0.95 },
  animate: { opacity: 1, scale: 1 },
  exit: { opacity: 0, scale: 0.95 },
  transition: { duration: 0.2, ease: "easeOut" as const }
};

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
        <div className="mx-auto max-w-7xl px-6 pt-4 flex gap-2">
          <button
            onClick={() => setMode("manager")}
            className="inline-flex items-center gap-2 rounded-xl border border-border bg-surface-solid px-4 py-2.5 text-sm font-medium text-muted transition-colors hover:bg-accent-soft hover:text-ink"
          >
            <LayoutDashboard className="h-4 w-4" />
            Manager Mode
          </button>
          <button className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-sm">
            <UserCog className="h-4 w-4" />
            Rep Mode
          </button>
        </div>
        <RepPanel />
      </>
    );
  }

  return (
    <motion.main
      className="mx-auto max-w-7xl px-6 py-6"
      {...fadeIn}
    >
      {/* Mode Switch */}
      <div className="mb-6 flex gap-2">
        <button className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-sm">
          <LayoutDashboard className="h-4 w-4" />
          Manager Mode
        </button>
        <button
          onClick={() => setMode("rep")}
          className="inline-flex items-center gap-2 rounded-xl border border-border bg-surface-solid px-4 py-2.5 text-sm font-medium text-muted transition-colors hover:bg-accent-soft hover:text-ink"
        >
          <UserCog className="h-4 w-4" />
          Rep Mode
        </button>
      </div>

      {/* Header */}
      <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-2xl font-bold tracking-tight text-ink">
          DoorDrill Manager Console
        </h1>
        <div className="flex gap-2">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" />
            <input
              placeholder="Manager ID"
              value={managerId}
              onChange={(e) => setManagerId(e.target.value)}
              className="rounded-xl border border-border bg-surface-solid py-2.5 pl-9 pr-3 text-sm backdrop-blur-xl placeholder:text-muted/60 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
          <button
            onClick={() => void refreshFeed()}
            disabled={!managerId || loading}
            className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
            {loading ? "Loading..." : "Load Feed"}
          </button>
        </div>
      </header>

      {/* Error Banner */}
      <AnimatePresence>
        {error ? (
          <motion.div
            className="mb-6 flex items-center gap-2 rounded-2xl border border-error/20 bg-error/5 px-4 py-3 text-sm text-error backdrop-blur-xl"
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
          >
            <AlertCircle className="h-4 w-4 shrink-0" />
            {error}
          </motion.div>
        ) : null}
      </AnimatePresence>

      {/* Bento Grid: Feed + Replay */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-[340px_1fr]">
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

      {/* Performance Section */}
      <motion.section
        className="mt-6"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3, delay: 0.1 }}
      >
        <PerformancePanel analytics={analytics} repProgress={repProgress} actions={actions} />
      </motion.section>
    </motion.main>
  );
}
