import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, Building2, Save } from "lucide-react";

import { fetchManagerOrganization, updateManagerOrganization } from "../lib/api";
import { clearStoredAuth, isAuthError } from "../lib/auth";
import { dispatchOnboardingRefresh } from "../lib/onboardingEvents";

const INDUSTRY_OPTIONS = [
  { value: "pest_control", label: "Pest Control" },
  { value: "solar", label: "Solar" },
  { value: "roofing", label: "Roofing" },
  { value: "alarms", label: "Home Security" },
  { value: "windows", label: "Windows" },
];

export function OrganizationSettingsPage() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [industry, setIndustry] = useState("pest_control");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadOrganization() {
      setLoading(true);
      setError(null);
      try {
        const organization = await fetchManagerOrganization();
        if (cancelled) {
          return;
        }
        setName(organization.name);
        setIndustry(organization.industry);
      } catch (loadError) {
        if (cancelled) {
          return;
        }
        if (isAuthError(loadError)) {
          clearStoredAuth();
          navigate("/login", { replace: true });
          return;
        }
        setError(loadError instanceof Error ? loadError.message : "Failed to load organization");
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadOrganization();
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await updateManagerOrganization({ name: name.trim(), industry });
      dispatchOnboardingRefresh();
      setSaved(true);
    } catch (saveError) {
      if (isAuthError(saveError)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setError(saveError instanceof Error ? saveError.message : "Failed to save organization");
    } finally {
      setSaving(false);
    }
  }

  return (
    <motion.main
      className="mx-auto max-w-3xl px-6 py-8"
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.32, ease: "easeOut" }}
    >
      <section className="rounded-[32px] border border-white/30 bg-white/45 p-8 shadow-xl shadow-black/5 backdrop-blur-2xl">
        <div className="mb-8">
          <div className="inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/60 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
            <Building2 className="h-3.5 w-3.5 text-accent" />
            Step 1
          </div>
          <h1 className="mt-3 text-3xl font-black tracking-tight text-ink">Set up your organization</h1>
          <p className="mt-2 text-sm leading-6 text-muted">
            Make sure the dashboard reflects your actual team and industry before you start inviting reps.
          </p>
        </div>

        {loading ? (
          <div className="rounded-2xl border border-white/25 bg-white/60 px-4 py-8 text-center text-sm text-muted">
            Loading organization profile...
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-5">
            <label className="block">
              <span className="mb-2 block text-sm font-medium text-ink">Organization name</span>
              <input
                type="text"
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
                className="w-full rounded-2xl border border-white/35 bg-white/65 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent/40 focus:ring-2 focus:ring-accent/20"
              />
            </label>

            <label className="block">
              <span className="mb-2 block text-sm font-medium text-ink">Industry</span>
              <select
                value={industry}
                onChange={(event) => setIndustry(event.target.value)}
                className="w-full rounded-2xl border border-white/35 bg-white/65 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent/40 focus:ring-2 focus:ring-accent/20"
                aria-label="Select organization industry"
              >
                {INDUSTRY_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            {error ? <div className="rounded-2xl border border-error/15 bg-error/[0.06] px-4 py-3 text-sm text-error">{error}</div> : null}
            {saved ? (
              <div className="rounded-2xl border border-accent/15 bg-accent-soft/35 px-4 py-3 text-sm text-accent">
                Organization saved.
              </div>
            ) : null}

            <div className="flex flex-wrap items-center justify-between gap-3">
              <button
                type="submit"
                disabled={saving}
                className="inline-flex items-center gap-2 rounded-2xl bg-accent px-5 py-3 text-sm font-semibold text-white transition hover:bg-accent-hover disabled:opacity-60"
              >
                <Save className="h-4 w-4" />
                {saving ? "Saving..." : "Save Organization"}
              </button>
              <button
                type="button"
                onClick={() => navigate("/scenarios/new")}
                className="inline-flex items-center gap-2 rounded-2xl border border-white/35 bg-white/70 px-5 py-3 text-sm font-semibold text-ink transition hover:bg-white/90"
              >
                Next Step
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          </form>
        )}
      </section>
    </motion.main>
  );
}
