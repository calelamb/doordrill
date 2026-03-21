import { getApiErrorCode } from "./apiError";
import type { AiMeta } from "./types";

type AiStatusPresentation = {
  label: string;
  toneClass: string;
  detail?: string | null;
};

export function describeAiMeta(meta: AiMeta | null | undefined): AiStatusPresentation | null {
  if (!meta) {
    return null;
  }

  const status = (meta.status || "").toLowerCase();
  if (status === "cached") {
    return {
      label: "Cached",
      toneClass: "border-slate-200 bg-slate-50 text-slate-700",
      detail: `${meta.provider} · ${meta.latency_ms}ms`,
    };
  }
  if (status === "fallback") {
    return {
      label: "Fallback",
      toneClass: "border-amber-200 bg-amber-50 text-amber-800",
      detail: `${meta.provider} · ${meta.latency_ms}ms`,
    };
  }
  if (status === "mock") {
    return {
      label: "Mock",
      toneClass: "border-violet-200 bg-violet-50 text-violet-800",
      detail: meta.model,
    };
  }
  if (status === "no_data") {
    return {
      label: "No Data",
      toneClass: "border-slate-200 bg-slate-50 text-slate-700",
      detail: null,
    };
  }
  return {
    label: "Live",
    toneClass: "border-emerald-200 bg-emerald-50 text-emerald-800",
    detail: `${meta.provider} · ${meta.latency_ms}ms`,
  };
}

export function describeAiError(error: unknown): AiStatusPresentation | null {
  const code = getApiErrorCode(error);
  if (code === "ai_timeout") {
    return {
      label: "Timed Out",
      toneClass: "border-amber-200 bg-amber-50 text-amber-800",
      detail: null,
    };
  }
  if (code === "ai_no_data") {
    return {
      label: "No Data",
      toneClass: "border-slate-200 bg-slate-50 text-slate-700",
      detail: null,
    };
  }
  if (code === "ai_not_configured" || code === "ai_provider_unavailable" || code === "ai_invalid_response") {
    return {
      label: "Unavailable",
      toneClass: "border-rose-200 bg-rose-50 text-rose-800",
      detail: null,
    };
  }
  return null;
}
