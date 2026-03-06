import { motion } from "framer-motion";
import { ArrowRight } from "lucide-react";

type ScoreTrajectoryBarProps = {
  currentScore: number | null;
  projectedScore: number | null;
  warningThreshold?: number;
  size?: "sm" | "md";
};

function scoreToPercent(score: number | null): number {
  if (typeof score !== "number" || Number.isNaN(score)) {
    return 0;
  }
  return Math.max(0, Math.min(100, (score / 10) * 100));
}

export function ScoreTrajectoryBar({
  currentScore,
  projectedScore,
  warningThreshold = 6,
  size = "md",
}: ScoreTrajectoryBarProps) {
  const currentPercent = scoreToPercent(currentScore);
  const projectedPercent = scoreToPercent(projectedScore ?? currentScore);
  const segmentLeft = Math.min(currentPercent, projectedPercent);
  const segmentWidth = Math.max(0, Math.abs(projectedPercent - currentPercent));
  const projectedBelowThreshold =
    typeof projectedScore === "number" && projectedScore < warningThreshold;
  const barHeightClass = size === "sm" ? "h-3" : "h-4";
  const dotSizeClass = size === "sm" ? "h-3.5 w-3.5" : "h-4 w-4";
  const arrowSizeClass = size === "sm" ? "h-4 w-4" : "h-5 w-5";

  return (
    <div className={`relative ${barHeightClass} overflow-visible rounded-full bg-white/45`}>
      <motion.div
        className="absolute inset-y-0 left-0 rounded-full bg-accent"
        initial={{ width: 0 }}
        animate={{ width: `${currentPercent}%` }}
        transition={{ duration: 0.7, ease: "easeOut" }}
      />

      {segmentWidth > 0 ? (
        <motion.div
          className={`absolute top-1/2 -translate-y-1/2 border-t-2 border-dashed ${
            projectedBelowThreshold ? "border-red-600" : "border-accent/70"
          }`}
          style={{ left: `${segmentLeft}%` }}
          initial={{ width: 0, opacity: 0 }}
          animate={{ width: `${segmentWidth}%`, opacity: 1 }}
          transition={{ type: "spring", stiffness: 160, damping: 18, delay: 0.12 }}
        />
      ) : null}

      {typeof currentScore === "number" ? (
        <motion.span
          className={`absolute top-1/2 -translate-y-1/2 ${dotSizeClass} rounded-full border-2 border-white bg-accent shadow-lg shadow-accent/25`}
          style={{ left: `calc(${currentPercent}% - 8px)` }}
          initial={{ opacity: 0, scale: 0.7 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ type: "spring", stiffness: 220, damping: 18 }}
        />
      ) : null}

      {typeof projectedScore === "number" ? (
        <motion.span
          className={`absolute top-1/2 -translate-y-1/2 ${projectedBelowThreshold ? "text-red-600" : "text-accent"}`}
          style={{ left: `calc(${projectedPercent}% - 9px)` }}
          initial={{ opacity: 0, scale: 0.7 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ type: "spring", stiffness: 210, damping: 18, delay: 0.1 }}
        >
          <ArrowRight className={arrowSizeClass} />
        </motion.span>
      ) : null}
    </div>
  );
}
