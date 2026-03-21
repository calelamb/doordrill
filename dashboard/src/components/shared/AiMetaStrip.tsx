import type { AiMeta } from "../../lib/types";
import { describeAiMeta } from "../../lib/aiStatus";

type AiMetaStripProps = {
  meta?: AiMeta | null;
};

export function AiMetaStrip({ meta }: AiMetaStripProps) {
  const presentation = describeAiMeta(meta);
  if (!presentation) {
    return null;
  }

  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] ${presentation.toneClass}`}>
        {presentation.label}
      </span>
      {presentation.detail ? (
        <span className="rounded-full border border-white/35 bg-white/70 px-2.5 py-1 text-[11px] font-medium text-muted">
          {presentation.detail}
        </span>
      ) : null}
      {meta?.fallback_used ? (
        <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11px] font-medium text-amber-800">
          Auto failover
        </span>
      ) : null}
    </div>
  );
}
