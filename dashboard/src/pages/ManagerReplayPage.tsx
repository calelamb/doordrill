import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { motion } from "framer-motion";
import { AlertCircle, ArrowLeft, RefreshCcw } from "lucide-react";

import { ReplayPanel } from "../components/ReplayPanel";
import { EmptyState } from "../components/shared/EmptyState";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { fetchReplay } from "../lib/api";
import type { ReplayResponse } from "../lib/types";

export function ManagerReplayPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";
  const focusTurnId = searchParams.get("turnId");
  const focusCategory = searchParams.get("category");

  const [replay, setReplay] = useState<ReplayResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadReplay = useCallback(async () => {
    if (!managerId || !id) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await fetchReplay(managerId, id);
      setReplay(data);
    } catch (err) {
      if (isAuthError(err)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setError(err instanceof Error ? err.message : "Failed to load replay");
    } finally {
      setLoading(false);
    }
  }, [id, managerId, navigate]);

  useEffect(() => {
    void loadReplay();
  }, [loadReplay]);

  return (
    <motion.main
      className="mx-auto max-w-7xl px-6 py-6"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: "easeOut" }}
    >
      <header className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <Link to="/manager/feed" className="mb-2 inline-flex items-center gap-2 text-sm text-muted transition hover:text-ink">
            <ArrowLeft className="h-4 w-4" />
            Back to Feed
          </Link>
          <h1 className="text-3xl font-bold tracking-tight text-ink">Session Replay</h1>
          <p className="mt-1 text-sm text-muted">Review transcript, playback, grading rationale, and coaching actions.</p>
        </div>
        <button
          onClick={() => void loadReplay()}
          disabled={loading}
          className="inline-flex items-center gap-2 rounded-xl border border-white/35 bg-white/55 px-4 py-2.5 text-sm font-medium text-ink transition hover:bg-white/70 disabled:opacity-60"
        >
          <RefreshCcw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </header>

      {loading ? <EmptyState variant="loading" message="Loading session replay..." /> : null}

      {!loading && error ? (
        <div className="rounded-3xl border border-error/15 bg-error/[0.06] px-6 py-10">
          <EmptyState variant="error" message={error} onRetry={() => void loadReplay()} />
        </div>
      ) : null}

      {!loading && !error && !replay ? (
        <div className="rounded-3xl border border-white/30 bg-white/40 px-6 py-10 shadow-xl shadow-black/5 backdrop-blur-2xl">
          <EmptyState variant="empty" message="No replay data found for this session." />
        </div>
      ) : null}

      {!loading && !error && replay ? (
        <ReplayPanel
          managerId={managerId}
          replay={replay}
          onActionDone={loadReplay}
          focusTurnId={focusTurnId}
          focusCategory={focusCategory}
        />
      ) : null}

      {!loading && error ? (
        <div className="mt-4 flex items-center gap-2 text-sm text-error">
          <AlertCircle className="h-4 w-4" />
          Replay could not be loaded with the current session state.
        </div>
      ) : null}
    </motion.main>
  );
}
