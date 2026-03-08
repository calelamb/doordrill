import type { FormEvent } from "react";
import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { BookOpenText, ChevronDown, ChevronUp, Loader2, Search } from "lucide-react";

import { EmptyState } from "./shared/EmptyState";
import { queryDocuments } from "../lib/knowledge";
import type { KnowledgeQueryChunk } from "../lib/types";

type KnowledgeBaseQueryPanelProps = {
  managerId: string;
  hasReadyDocuments: boolean;
};

function formatSimilarity(score: number) {
  return `${Math.round(Math.max(0, Math.min(1, score)) * 100)}% match`;
}

export function KnowledgeBaseQueryPanel({ managerId, hasReadyDocuments }: KnowledgeBaseQueryPanelProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<KnowledgeQueryChunk[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasSearched, setHasSearched] = useState(false);

  const helperText = useMemo(() => {
    if (!hasReadyDocuments) {
      return "Upload and process at least one document before searching the knowledge base.";
    }
    return "Search raw passages only. These are the exact chunks the AI retrieval layer can see.";
  }, [hasReadyDocuments]);

  async function runQuery() {
    const trimmedQuery = query.trim();
    if (!trimmedQuery || !managerId || !hasReadyDocuments) {
      return;
    }

    setLoading(true);
    setError(null);
    setHasSearched(true);

    try {
      const response = await queryDocuments(managerId, trimmedQuery, 5);
      setResults(response.chunks);
    } catch (queryError) {
      setResults([]);
      setError(queryError instanceof Error ? queryError.message : "Search failed.");
    } finally {
      setLoading(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await runQuery();
  }

  return (
    <section className="rounded-[32px] border border-border/80 bg-white/55 p-6 shadow-[0_24px_60px_rgba(45,90,61,0.08)] backdrop-blur-2xl">
      <button
        type="button"
        onClick={() => setIsOpen((current) => !current)}
        className="flex w-full items-center justify-between gap-4 text-left"
        aria-expanded={isOpen}
        aria-controls="knowledge-base-query-panel"
      >
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-accent/70">Direct Q&A</p>
          <div>
            <h2 className="text-2xl font-semibold tracking-tight text-ink">Ask your training material</h2>
            <p className="mt-2 text-sm text-muted">{helperText}</p>
          </div>
        </div>
        <div className="inline-flex items-center gap-2 rounded-full border border-border-strong/70 bg-white/75 px-4 py-2 text-sm font-medium text-ink">
          <span>{isOpen ? "Hide" : "Open"}</span>
          {isOpen ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
        </div>
      </button>

      <AnimatePresence initial={false}>
        {isOpen ? (
          <motion.div
            id="knowledge-base-query-panel"
            initial={{ opacity: 0, height: 0, marginTop: 0 }}
            animate={{ opacity: 1, height: "auto", marginTop: 24 }}
            exit={{ opacity: 0, height: 0, marginTop: 0 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="overflow-hidden"
          >
            <form onSubmit={(event) => void handleSubmit(event)} className="rounded-[28px] border border-border/70 bg-surface-solid/85 p-4">
              <div className="flex flex-col gap-3 lg:flex-row">
                <label className="flex-1">
                  <span className="sr-only">Search uploaded documents</span>
                  <div className="flex items-center gap-3 rounded-2xl border border-border bg-white/90 px-4 py-3">
                    <Search className="h-4 w-4 text-muted" />
                    <input
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="Ex. What does our script say about the already-have-service objection?"
                      className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-muted"
                    />
                  </div>
                </label>
                <button
                  type="submit"
                  disabled={loading || !hasReadyDocuments || !query.trim()}
                  className="inline-flex items-center justify-center rounded-2xl bg-accent px-5 py-3 text-sm font-semibold text-white transition hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {loading ? (
                    <span className="inline-flex items-center gap-2">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Searching...
                    </span>
                  ) : (
                    "Search Material"
                  )}
                </button>
              </div>
            </form>

            {loading ? (
              <EmptyState variant="loading" message="Searching uploaded material..." />
            ) : error ? (
              <EmptyState
                variant="error"
                message={error}
                onRetry={() => {
                  if (!query.trim()) {
                    return;
                  }
                  void runQuery();
                }}
              />
            ) : !hasReadyDocuments ? (
              <EmptyState
                variant="empty"
                icon={BookOpenText}
                message="No searchable material is ready yet. Upload a document and wait for processing to finish."
              />
            ) : hasSearched && results.length === 0 ? (
              <EmptyState
                variant="empty"
                icon={BookOpenText}
                message="No relevant sections found. Try rephrasing or uploading more material."
              />
            ) : results.length > 0 ? (
              <div className="mt-6 space-y-4">
                {results.map((chunk) => (
                  <article
                    key={chunk.chunk_id}
                    className="rounded-[28px] border border-border/70 bg-[linear-gradient(135deg,rgba(255,255,255,0.92),rgba(244,248,242,0.86))] p-5"
                  >
                    <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                      <div>
                        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted">Source document</p>
                        <h3 className="mt-2 text-lg font-semibold text-ink">{chunk.document_name}</h3>
                      </div>
                      <div className="inline-flex items-center rounded-full bg-accent-soft/80 px-3 py-1.5 text-xs font-semibold text-accent">
                        {formatSimilarity(chunk.similarity_score)}
                      </div>
                    </div>
                    <p className="mt-4 whitespace-pre-wrap text-sm leading-7 text-ink/90">{chunk.text}</p>
                  </article>
                ))}
              </div>
            ) : (
              <EmptyState
                variant="empty"
                icon={BookOpenText}
                message="Search for a script, objection playbook, or methodology phrase to inspect raw passages."
              />
            )}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  );
}
