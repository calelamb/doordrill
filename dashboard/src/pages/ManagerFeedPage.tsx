import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { AlertCircle, Loader2, Search } from "lucide-react";

import { FeedList } from "../components/FeedList";
import { PerformancePanel } from "../components/PerformancePanel";
import { ReplayPanel } from "../components/ReplayPanel";
import { fetchManagerActions, fetchManagerAnalytics, fetchManagerFeed, fetchReplay, fetchRepProgress } from "../lib/api";
import type { FeedItem, ManagerActionLog, ManagerAnalytics, ReplayResponse, RepProgress } from "../lib/types";

export function ManagerFeedPage() {
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
        if (activeSessionId) {
            void refreshReplay(activeSessionId);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [activeSessionId]);

    return (
        <motion.main
            className="max-w-7xl mx-auto"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, delay: 0.1, ease: "easeOut" }}
        >
            {/* Header */}
            <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight text-ink">Manager Console</h1>
                    <p className="mt-1 text-sm text-muted">Monitor rep performance and review drill sessions</p>
                </div>
                <div className="flex gap-2.5">
                    <div className="relative">
                        <Search className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted/60" />
                        <input
                            placeholder="Manager ID"
                            value={managerId}
                            onChange={(e) => setManagerId(e.target.value)}
                            className="w-48 rounded-xl border border-white/30 bg-white/40 py-2.5 pl-10 pr-3.5 text-sm backdrop-blur-2xl placeholder:text-muted/50 transition-all duration-200 focus:border-accent/40 focus:bg-white/60 focus:outline-none focus:ring-2 focus:ring-accent/20 shadow-sm"
                        />
                    </div>
                    <button
                        onClick={() => void refreshFeed()}
                        disabled={!managerId || loading}
                        className="inline-flex items-center gap-2 rounded-xl bg-accent px-5 py-2.5 text-sm font-medium text-white shadow-lg shadow-accent/25 transition-all duration-200 hover:bg-accent-hover hover:shadow-accent/35 disabled:opacity-50 disabled:shadow-none"
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
                        className="mb-6 flex items-center gap-3 rounded-2xl border border-error/15 bg-error/[0.06] px-5 py-3.5 text-sm text-error backdrop-blur-2xl shadow-lg shadow-error/5"
                        initial={{ opacity: 0, y: -10, scale: 0.97 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: -10, scale: 0.97 }}
                        transition={{ duration: 0.2 }}
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
                initial={{ opacity: 0, y: 16 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.2, ease: "easeOut" }}
            >
                <PerformancePanel analytics={analytics} repProgress={repProgress} actions={actions} />
            </motion.section>
        </motion.main>
    );
}
