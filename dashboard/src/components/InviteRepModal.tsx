import { FormEvent, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { CheckCircle2, Copy, Mail, Send, X } from "lucide-react";

import { createManagerInvitation } from "../lib/api";
import { getValidStoredAuth, isAuthError } from "../lib/auth";
import { dispatchOnboardingRefresh } from "../lib/onboardingEvents";
import type { ManagerInvitation } from "../lib/types";

type InviteRepModalProps = {
  onClose?: () => void;
  onAuthError?: () => void;
};

export function InviteRepModal({ onClose, onAuthError }: InviteRepModalProps) {
  const auth = getValidStoredAuth();
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<ManagerInvitation | null>(null);
  const [copied, setCopied] = useState(false);

  const defaultTeamId = auth?.user.team_id ?? null;
  const canSubmit = useMemo(() => email.trim().length > 3 && !submitting, [email, submitting]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSubmit) {
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const result = await createManagerInvitation({
        email: email.trim(),
        team_id: defaultTeamId,
        role: "rep",
      });
      setSuccess(result);
      dispatchOnboardingRefresh();
    } catch (submitError) {
      if (isAuthError(submitError)) {
        onAuthError?.();
        return;
      }
      const message = submitError instanceof Error ? submitError.message : "Failed to create invite";
      if (message.includes("already invited")) {
        setError("That rep already has a pending invite.");
      } else if (message.includes("already registered")) {
        setError("That email is already registered.");
      } else {
        setError(message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function handleCopyInviteLink() {
    if (!success?.invite_url) {
      return;
    }
    await navigator.clipboard.writeText(success.invite_url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 10, scale: 0.985 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.22, ease: "easeOut" }}
      className="w-full max-w-xl rounded-[32px] border border-white/30 bg-white/45 p-6 shadow-2xl shadow-black/10 backdrop-blur-2xl"
    >
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/65 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
            <Mail className="h-3.5 w-3.5 text-accent" />
            Invite Rep
          </div>
          <h1 className="mt-3 text-2xl font-black tracking-tight text-ink">Invite your first rep</h1>
          <p className="mt-1 text-sm text-muted">
            Send a secure email invite with a short-lived registration link.
          </p>
        </div>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            aria-label="Close invite rep modal"
            className="rounded-full border border-white/35 bg-white/60 p-2 text-muted transition hover:bg-white/80 hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        ) : null}
      </div>

      {success ? (
        <div className="space-y-4">
          <div className="rounded-[24px] border border-accent/15 bg-accent-soft/35 p-5">
            <div className="flex items-start gap-3">
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-accent" />
              <div>
                <div className="text-base font-bold text-ink">Invite sent</div>
                <p className="mt-1 text-sm leading-6 text-muted">
                  {success.email} now has an email invite. You can also share the deep link manually if needed.
                </p>
              </div>
            </div>
          </div>

          <div className="rounded-[24px] border border-white/25 bg-white/65 p-4">
            <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">Invite Link</div>
            <div className="mt-2 break-all text-sm text-ink">{success.invite_url}</div>
            <div className="mt-4 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => {
                  void handleCopyInviteLink();
                }}
                aria-label="Copy invite link"
                className="inline-flex items-center gap-2 rounded-2xl border border-white/35 bg-white/80 px-4 py-2 text-sm font-semibold text-ink transition hover:bg-white"
              >
                <Copy className="h-4 w-4" />
                {copied ? "Copied" : "Copy Link"}
              </button>
              {onClose ? (
                <button
                  type="button"
                  onClick={onClose}
                  className="inline-flex items-center gap-2 rounded-2xl bg-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-accent-hover"
                >
                  Back to dashboard
                </button>
              ) : null}
            </div>
          </div>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-5">
          <label className="block">
            <span className="mb-2 block text-sm font-medium text-ink">Rep email</span>
            <input
              type="email"
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="rep@company.com"
              className="w-full rounded-2xl border border-white/35 bg-white/65 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent/40 focus:ring-2 focus:ring-accent/20"
            />
          </label>

          {error ? (
            <div className="rounded-2xl border border-error/15 bg-error/[0.06] px-4 py-3 text-sm text-error">{error}</div>
          ) : null}

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="text-xs uppercase tracking-[0.18em] text-muted">
              {defaultTeamId ? "Invite will use your current team" : "Invite will default to the rep role"}
            </div>
            <button
              type="submit"
              disabled={!canSubmit}
              aria-label="Send rep invite"
              className="inline-flex items-center gap-2 rounded-2xl bg-accent px-5 py-3 text-sm font-semibold text-white transition hover:bg-accent-hover disabled:opacity-60"
            >
              <Send className="h-4 w-4" />
              {submitting ? "Sending..." : "Send Invite"}
            </button>
          </div>
        </form>
      )}
    </motion.section>
  );
}
