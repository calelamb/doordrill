import { FormEvent, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowRight, Sparkles, Target } from "lucide-react";

import { createScenario, fetchManagerOrganization } from "../lib/api";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { dispatchOnboardingRefresh } from "../lib/onboardingEvents";

const DEFAULT_STAGES = ["door_knock", "initial_pitch", "objection_handling", "close_attempt", "ended"];
const DEFAULT_RUBRIC = {
  opening: { weight: 0.15, description: "Introduces self and earns attention cleanly." },
  pitch_delivery: { weight: 0.25, description: "Explains value clearly and specifically." },
  objection_handling: { weight: 0.3, description: "Addresses the homeowner's real concern directly." },
  closing_technique: { weight: 0.2, description: "Asks for a realistic next step or close." },
  professionalism: { weight: 0.1, description: "Stays calm, respectful, and credible." },
} as const;

function personaForDifficulty(difficulty: number) {
  if (difficulty <= 2) {
    return {
      attitude: "friendly",
      concerns: ["clarity", "credibility"],
      softening_condition: "You warm up when the rep sounds specific, calm, and respectful.",
    };
  }
  if (difficulty >= 4) {
    return {
      attitude: "skeptical",
      concerns: ["price", "trust", "timing"],
      softening_condition: "You only stay engaged if the rep handles resistance directly and reduces risk.",
    };
  }
  return {
    attitude: "guarded",
    concerns: ["value", "time"],
    softening_condition: "You stay open if the rep is concise and homeowner-focused.",
  };
}

export function ScenarioCreatePage() {
  const navigate = useNavigate();
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [difficulty, setDifficulty] = useState(1);
  const [industry, setIndustry] = useState("pest_control");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function loadOrganization() {
      setLoading(true);
      try {
        const organization = await fetchManagerOrganization();
        if (!cancelled) {
          setIndustry(organization.industry);
        }
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
    if (!managerId) {
      return;
    }

    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await createScenario({
        name: name.trim(),
        industry,
        difficulty,
        description: description.trim(),
        persona: personaForDifficulty(difficulty),
        rubric: DEFAULT_RUBRIC,
        stages: DEFAULT_STAGES,
        created_by_id: managerId,
      });
      dispatchOnboardingRefresh();
      setSaved(true);
    } catch (saveError) {
      if (isAuthError(saveError)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setError(saveError instanceof Error ? saveError.message : "Failed to create scenario");
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
            <Sparkles className="h-3.5 w-3.5 text-accent" />
            Step 2
          </div>
          <h1 className="mt-3 text-3xl font-black tracking-tight text-ink">Create your first drill scenario</h1>
          <p className="mt-2 text-sm leading-6 text-muted">
            Give managers a real scenario to assign before you start inviting reps.
          </p>
        </div>

        {loading ? (
          <div className="rounded-2xl border border-white/25 bg-white/60 px-4 py-8 text-center text-sm text-muted">
            Loading scenario defaults...
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-5">
            <label className="block">
              <span className="mb-2 block text-sm font-medium text-ink">Scenario name</span>
              <input
                type="text"
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Friendly Homeowner"
                className="w-full rounded-2xl border border-white/35 bg-white/65 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent/40 focus:ring-2 focus:ring-accent/20"
              />
            </label>

            <label className="block">
              <span className="mb-2 block text-sm font-medium text-ink">Scenario description</span>
              <textarea
                required
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                rows={4}
                placeholder="A homeowner gives the rep a fair chance to open strong and explain the offer."
                className="w-full rounded-2xl border border-white/35 bg-white/65 px-4 py-3 text-sm text-ink outline-none transition focus:border-accent/40 focus:ring-2 focus:ring-accent/20"
              />
            </label>

            <label className="block">
              <span className="mb-2 block text-sm font-medium text-ink">Difficulty</span>
              <input
                type="range"
                min={1}
                max={5}
                step={1}
                value={difficulty}
                onChange={(event) => setDifficulty(Number(event.target.value))}
                aria-label="Set scenario difficulty"
                className="w-full accent-[var(--color-accent)]"
              />
              <div className="mt-2 flex items-center justify-between rounded-2xl border border-white/25 bg-white/60 px-4 py-3">
                <div className="inline-flex items-center gap-2 text-sm font-semibold text-ink">
                  <Target className="h-4 w-4 text-accent" />
                  Difficulty {difficulty}/5
                </div>
                <div className="text-xs uppercase tracking-[0.18em] text-muted">
                  {difficulty <= 2 ? "Beginner friendly" : difficulty >= 4 ? "Advanced pressure" : "Balanced"}
                </div>
              </div>
            </label>

            {error ? <div className="rounded-2xl border border-error/15 bg-error/[0.06] px-4 py-3 text-sm text-error">{error}</div> : null}
            {saved ? (
              <div className="rounded-2xl border border-accent/15 bg-accent-soft/35 px-4 py-3 text-sm text-accent">
                Scenario created.
              </div>
            ) : null}

            <div className="flex flex-wrap items-center justify-between gap-3">
              <button
                type="submit"
                disabled={saving || !name.trim() || !description.trim()}
                className="inline-flex items-center gap-2 rounded-2xl bg-accent px-5 py-3 text-sm font-semibold text-white transition hover:bg-accent-hover disabled:opacity-60"
              >
                {saving ? "Creating..." : "Create Scenario"}
              </button>
              <button
                type="button"
                onClick={() => navigate("/reps/invite")}
                className="inline-flex items-center gap-2 rounded-2xl border border-white/35 bg-white/70 px-5 py-3 text-sm font-semibold text-ink transition hover:bg-white/90"
              >
                Invite Reps
                <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          </form>
        )}
      </section>
    </motion.main>
  );
}
