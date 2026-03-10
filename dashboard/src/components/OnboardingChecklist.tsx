import { AnimatePresence, motion } from "framer-motion";
import { CheckCircle2, ChevronRight, Circle, Sparkles } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useOnboardingStatus } from "../hooks/useOnboardingStatus";

function ChecklistSkeleton() {
  return (
    <div className="mb-6 rounded-[28px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div className="space-y-2">
          <div className="h-5 w-40 rounded-full bg-accent-soft/70" />
          <div className="h-4 w-28 rounded-full bg-white/80" />
        </div>
        <div className="h-2 w-32 rounded-full bg-white/80" />
      </div>
      <div className="space-y-3">
        {Array.from({ length: 3 }).map((_, index) => (
          <div key={index} className="h-14 rounded-2xl bg-white/70" />
        ))}
      </div>
    </div>
  );
}

export function OnboardingChecklist() {
  const navigate = useNavigate();
  const { data, error, isLoading, refetch } = useOnboardingStatus();

  if (isLoading) {
    return <ChecklistSkeleton />;
  }

  if (error) {
    return (
      <div className="mb-6 rounded-[28px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/60 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
              <Sparkles className="h-3.5 w-3.5 text-accent" />
              Setup Guide
            </div>
            <h2 className="mt-3 text-lg font-bold text-ink">Couldn&apos;t load onboarding steps</h2>
            <p className="mt-1 text-sm text-muted">{error}</p>
          </div>
          <button
            type="button"
            onClick={() => {
              void refetch();
            }}
            className="rounded-full border border-white/35 bg-white/70 px-4 py-2 text-sm font-semibold text-ink transition hover:bg-white/90"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!data || data.is_complete) {
    return null;
  }

  const completedCount = data.steps.filter((step) => step.is_complete).length;
  const progress = data.steps.length > 0 ? (completedCount / data.steps.length) * 100 : 0;

  return (
    <AnimatePresence>
      <motion.section
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, height: 0 }}
        className="mb-6 rounded-[28px] border border-white/30 bg-white/40 p-6 shadow-xl shadow-black/5 backdrop-blur-2xl"
      >
        <div className="mb-4 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-white/35 bg-white/60 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted">
              <Sparkles className="h-3.5 w-3.5 text-accent" />
              Setup Guide
            </div>
            <h2 className="mt-3 text-lg font-bold text-ink">Get DoorDrill ready</h2>
            <p className="mt-1 text-sm text-muted">
              {completedCount} of {data.steps.length} steps complete
            </p>
          </div>
          <div className="w-full max-w-40">
            <div className="h-2 overflow-hidden rounded-full bg-white/80">
              <motion.div
                className="h-full rounded-full bg-accent"
                initial={{ width: 0 }}
                animate={{ width: `${progress}%` }}
                transition={{ duration: 0.5, ease: "easeOut" }}
              />
            </div>
          </div>
        </div>

        <div className="space-y-3">
          {data.steps.map((step) => (
            <motion.button
              key={step.id}
              type="button"
              onClick={() => {
                const target = step.cta_url;
                if (target.startsWith("/") && !target.startsWith("//")) {
                  navigate(target);
                }
              }}
              className="flex w-full items-center gap-3 rounded-2xl border border-white/25 bg-white/45 p-4 text-left transition hover:bg-white/70"
              whileTap={{ scale: 0.99 }}
              aria-label={step.is_complete ? `${step.label} complete` : `Complete step ${step.label}`}
            >
              {step.is_complete ? (
                <CheckCircle2 className="h-5 w-5 shrink-0 text-accent" />
              ) : (
                <Circle className="h-5 w-5 shrink-0 text-muted/40" />
              )}
              <span className={`flex-1 text-sm font-medium ${step.is_complete ? "text-muted line-through" : "text-ink"}`}>
                {step.label}
              </span>
              {!step.is_complete ? <ChevronRight className="h-4 w-4 text-muted" /> : null}
            </motion.button>
          ))}
        </div>
      </motion.section>
    </AnimatePresence>
  );
}
