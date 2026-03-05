import { FormEvent, useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { AlertCircle, ArrowRight, Lock, Mail, Shield } from "lucide-react";

import { getValidStoredAuth } from "../lib/auth";
import { loginManager } from "../lib/api";

export function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const existing = getValidStoredAuth();

  const redirectTarget = useMemo(() => {
    const state = location.state as { from?: string } | null;
    return state?.from || "/manager/feed";
  }, [location.state]);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (existing) {
      navigate("/manager/feed", { replace: true });
    }
  }, [existing, navigate]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await loginManager(email, password);
      navigate(redirectTarget, { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to sign in");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen px-6 py-10 flex items-center justify-center">
      <motion.section
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35, ease: "easeOut" }}
        className="w-full max-w-4xl grid overflow-hidden rounded-[28px] border border-white/40 bg-white/45 shadow-2xl shadow-black/10 backdrop-blur-2xl lg:grid-cols-[1.05fr_0.95fr]"
      >
        <div className="relative overflow-hidden border-b border-white/30 px-8 py-10 lg:border-b-0 lg:border-r">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(45,90,61,0.18),transparent_45%),radial-gradient(circle_at_bottom_right,rgba(139,105,20,0.14),transparent_35%)]" />
          <div className="relative space-y-8">
            <div className="inline-flex items-center gap-3 rounded-full border border-white/50 bg-white/55 px-4 py-2 text-sm font-medium text-ink shadow-sm">
              <span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent text-white">
                <Shield className="h-4 w-4" />
              </span>
              DoorDrill Manager Console
            </div>

            <div className="space-y-4">
              <h1 className="max-w-md text-4xl font-black tracking-tight text-ink">
                Review every drill, catch misses fast, coach from evidence.
              </h1>
              <p className="max-w-lg text-sm leading-6 text-muted">
                Sign in with your manager account to access the feed, replay sessions, and performance analytics.
                The dashboard requires a valid JWT before any manager route will load.
              </p>
            </div>

            <div className="grid gap-3 text-sm">
              {[
                "Session replay with synchronized transcript and evidence-linked scoring",
                "Batch review workflows for unreviewed sessions",
                "Rep progress and team analytics across the last 7, 30, or 90 days",
              ].map((item) => (
                <div key={item} className="rounded-2xl border border-white/40 bg-white/45 px-4 py-3 text-ink shadow-sm">
                  {item}
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="px-8 py-10">
          <form onSubmit={handleSubmit} className="mx-auto max-w-md space-y-5">
            <div className="space-y-2">
              <h2 className="text-2xl font-bold tracking-tight text-ink">Manager Login</h2>
              <p className="text-sm text-muted">Missing or expired JWTs redirect here automatically.</p>
            </div>

            <label className="block">
              <span className="mb-2 block text-sm font-medium text-ink">Email</span>
              <div className="relative">
                <Mail className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted/60" />
                <input
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  className="w-full rounded-2xl border border-white/35 bg-white/60 py-3 pl-11 pr-4 text-sm text-ink outline-none transition focus:border-accent/50 focus:ring-2 focus:ring-accent/20"
                  placeholder="manager@company.com"
                />
              </div>
            </label>

            <label className="block">
              <span className="mb-2 block text-sm font-medium text-ink">Password</span>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-muted/60" />
                <input
                  type="password"
                  autoComplete="current-password"
                  required
                  minLength={8}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  className="w-full rounded-2xl border border-white/35 bg-white/60 py-3 pl-11 pr-4 text-sm text-ink outline-none transition focus:border-accent/50 focus:ring-2 focus:ring-accent/20"
                  placeholder="Minimum 8 characters"
                />
              </div>
            </label>

            {error ? (
              <div className="flex items-start gap-3 rounded-2xl border border-error/15 bg-error/[0.06] px-4 py-3 text-sm text-error">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
            ) : null}

            <button
              type="submit"
              disabled={loading}
              className="inline-flex w-full items-center justify-center gap-2 rounded-2xl bg-accent px-5 py-3 text-sm font-semibold text-white transition hover:bg-accent-hover disabled:opacity-60"
            >
              {loading ? "Signing in..." : "Sign In"}
              <ArrowRight className="h-4 w-4" />
            </button>
          </form>
        </div>
      </motion.section>
    </main>
  );
}
