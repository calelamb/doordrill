import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, BookOpenText, FileWarning, Loader2, RefreshCcw, Trash2 } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { DocumentUploadZone } from "../components/DocumentUploadZone";
import { KnowledgeBaseQueryPanel } from "../components/KnowledgeBaseQueryPanel";
import { EmptyState } from "../components/shared/EmptyState";
import { clearStoredAuth, getValidStoredAuth, isAuthError } from "../lib/auth";
import { deleteDocument, listDocuments, uploadDocument } from "../lib/knowledge";
import { cardVariants, pageVariants } from "../lib/motion";
import type { KnowledgeDocument } from "../lib/types";

function formatTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function formatFileType(fileType: string) {
  return fileType.toUpperCase();
}

function StatusChip({ document }: { document: KnowledgeDocument }) {
  if (document.status === "ready") {
    return (
      <span className="inline-flex items-center gap-2 rounded-full bg-emerald-100 px-3 py-1.5 text-xs font-semibold text-emerald-800">
        <span className="h-2 w-2 rounded-full bg-emerald-600" />
        Ready
        {typeof document.chunk_count === "number" ? <span>{document.chunk_count} chunks</span> : null}
      </span>
    );
  }

  if (document.status === "failed") {
    return (
      <span
        title={document.error_message ?? "Processing failed"}
        className="inline-flex items-center gap-2 rounded-full bg-red-100 px-3 py-1.5 text-xs font-semibold text-red-700"
      >
        <FileWarning className="h-3.5 w-3.5" />
        Failed
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-amber-100 px-3 py-1.5 text-xs font-semibold text-amber-800">
      <Loader2 className="h-3.5 w-3.5 animate-spin" />
      {document.status === "pending" ? "Pending" : "Processing"}
    </span>
  );
}

export function KnowledgeBasePage() {
  const navigate = useNavigate();
  const auth = getValidStoredAuth();
  const managerId = auth?.user.id ?? "";

  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploadState, setUploadState] = useState<"idle" | "uploading" | "success" | "error">("idle");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<KnowledgeDocument | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const requestIdRef = useRef(0);

  const hasActiveProcessing = useMemo(
    () => documents.some((document) => document.status === "pending" || document.status === "processing"),
    [documents],
  );
  const hasReadyDocuments = useMemo(() => documents.some((document) => document.status === "ready"), [documents]);

  const loadDocuments = useCallback(async () => {
    if (!managerId) {
      return;
    }
    const requestId = ++requestIdRef.current;
    try {
      const items = await listDocuments(managerId);
      if (requestIdRef.current !== requestId) {
        return;
      }
      setDocuments(items);
      setError(null);
    } catch (loadError) {
      if (isAuthError(loadError)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      if (requestIdRef.current !== requestId) {
        return;
      }
      setError(loadError instanceof Error ? loadError.message : "Failed to load documents.");
    } finally {
      if (requestIdRef.current === requestId) {
        setLoading(false);
      }
    }
  }, [managerId, navigate]);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  useEffect(() => {
    if (!hasActiveProcessing) {
      return;
    }
    const intervalId = window.setInterval(() => {
      void loadDocuments();
    }, 5_000);
    return () => window.clearInterval(intervalId);
  }, [hasActiveProcessing, loadDocuments]);

  const handleUpload = useCallback(
    async (file: File, name: string) => {
      if (!managerId) {
        return;
      }
      setUploadState("uploading");
      setUploadProgress(0);
      setUploadError(null);
      try {
        const created = await uploadDocument(file, name, managerId, setUploadProgress);
        setUploadState("success");
        setDocuments((current) => [created, ...current]);
        void loadDocuments();
      } catch (uploadErr) {
        if (isAuthError(uploadErr)) {
          clearStoredAuth();
          navigate("/login", { replace: true });
          return;
        }
        setUploadState("error");
        setUploadError(uploadErr instanceof Error ? uploadErr.message : "Upload failed.");
      }
    },
    [loadDocuments, managerId, navigate],
  );

  const handleDelete = useCallback(async () => {
    if (!deleteTarget || !managerId) {
      return;
    }
    setIsDeleting(true);
    try {
      await deleteDocument(deleteTarget.id, managerId);
      setDocuments((current) => current.filter((document) => document.id !== deleteTarget.id));
      setDeleteTarget(null);
    } catch (deleteErr) {
      if (isAuthError(deleteErr)) {
        clearStoredAuth();
        navigate("/login", { replace: true });
        return;
      }
      setError(deleteErr instanceof Error ? deleteErr.message : "Delete failed.");
    } finally {
      setIsDeleting(false);
    }
  }, [deleteTarget, managerId, navigate]);

  return (
    <motion.main
      className="mx-auto max-w-7xl space-y-6 px-6 py-6"
      initial="hidden"
      animate="visible"
      variants={pageVariants}
    >
      <motion.section variants={cardVariants} className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div className="space-y-3">
          <p className="text-xs font-semibold uppercase tracking-[0.28em] text-accent/70">Knowledge Base</p>
          <div>
            <h1 className="text-4xl font-semibold tracking-tight text-ink">Training Materials</h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-muted">
              Upload scripts, objection playbooks, and methodology guides. The AI will use them to grade reps and personalize coaching.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => {
            setLoading(true);
            void loadDocuments();
          }}
          className="inline-flex items-center justify-center gap-2 rounded-2xl border border-border-strong bg-white/70 px-4 py-3 text-sm font-semibold text-ink transition hover:border-accent/40 hover:bg-white"
        >
          <RefreshCcw className="h-4 w-4" />
          Refresh
        </button>
      </motion.section>

      <motion.section variants={cardVariants}>
        <DocumentUploadZone
          onFileSelected={() => {
            setUploadState("idle");
            setUploadProgress(0);
            setUploadError(null);
          }}
          onUpload={handleUpload}
          uploadState={uploadState}
          uploadProgress={uploadProgress}
          errorMessage={uploadError}
        />
      </motion.section>

      <motion.section
        variants={cardVariants}
        className="rounded-[32px] border border-border/80 bg-white/55 p-6 shadow-[0_24px_60px_rgba(45,90,61,0.08)] backdrop-blur-2xl"
      >
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.24em] text-accent/70">Library</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight text-ink">Document status and processing</h2>
            <p className="mt-2 text-sm text-muted">
              Pending and processing files auto-refresh every 5 seconds until they settle.
            </p>
          </div>
          <div className="rounded-full bg-accent-soft/70 px-4 py-2 text-xs font-medium text-accent">
            {documents.length} {documents.length === 1 ? "document" : "documents"}
          </div>
        </div>

        {loading ? (
          <EmptyState variant="loading" message="Loading training materials..." />
        ) : error ? (
          <EmptyState variant="error" message={error} onRetry={() => {
            setLoading(true);
            void loadDocuments();
          }} />
        ) : documents.length === 0 ? (
          <EmptyState
            variant="empty"
            icon={BookOpenText}
            message="Upload your training scripts, objection playbooks, or methodology guides to start grounding the AI in your company playbook."
          />
        ) : (
          <div className="mt-6 space-y-4">
            {documents.map((document) => (
              <article
                key={document.id}
                className="grid gap-4 rounded-[28px] border border-border/70 bg-surface-solid/85 p-5 lg:grid-cols-[1.3fr_0.7fr_0.45fr]"
              >
                <div className="space-y-3">
                  <div className="flex flex-wrap items-center gap-3">
                    <h3 className="text-lg font-semibold text-ink">{document.name}</h3>
                    <span className="rounded-full border border-border-strong/70 bg-white/80 px-3 py-1 text-xs font-semibold tracking-[0.14em] text-muted">
                      {formatFileType(document.file_type)}
                    </span>
                  </div>
                  <div className="space-y-1 text-sm text-muted">
                    <p>{document.original_filename}</p>
                    <p>Uploaded {formatTimestamp(document.created_at)}</p>
                    {document.status === "failed" && document.error_message ? (
                      <p className="text-error" title={document.error_message}>
                        {document.error_message}
                      </p>
                    ) : null}
                  </div>
                </div>

                <div className="space-y-3">
                  <StatusChip document={document} />
                  <div className="grid grid-cols-2 gap-3 text-sm">
                    <div className="rounded-2xl bg-white/80 p-3">
                      <p className="text-xs uppercase tracking-[0.18em] text-muted">Chunks</p>
                      <p className="mt-1 font-semibold text-ink">{document.chunk_count ?? "—"}</p>
                    </div>
                    <div className="rounded-2xl bg-white/80 p-3">
                      <p className="text-xs uppercase tracking-[0.18em] text-muted">Tokens</p>
                      <p className="mt-1 font-semibold text-ink">{document.token_count ?? "—"}</p>
                    </div>
                  </div>
                </div>

                <div className="flex items-start justify-end">
                  <button
                    type="button"
                    onClick={() => setDeleteTarget(document)}
                    className="inline-flex items-center gap-2 rounded-2xl border border-red-200 bg-red-50 px-4 py-2.5 text-sm font-semibold text-red-700 transition hover:bg-red-100"
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </motion.section>

      <motion.section variants={cardVariants}>
        <KnowledgeBaseQueryPanel managerId={managerId} hasReadyDocuments={hasReadyDocuments} />
      </motion.section>

      {deleteTarget ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/25 px-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-[28px] border border-border-strong bg-surface-solid p-6 shadow-[0_30px_80px_rgba(26,46,26,0.2)]">
            <div className="flex items-start gap-3">
              <div className="rounded-2xl bg-red-100 p-3 text-red-700">
                <AlertTriangle className="h-5 w-5" />
              </div>
              <div>
                <h3 className="text-xl font-semibold text-ink">Delete document?</h3>
                <p className="mt-2 text-sm leading-6 text-muted">
                  <span className="font-semibold text-ink">{deleteTarget.name}</span> and all of its chunks will be removed from the knowledge base.
                </p>
              </div>
            </div>

            <div className="mt-6 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setDeleteTarget(null)}
                className="rounded-2xl border border-border-strong bg-white/80 px-4 py-2.5 text-sm font-semibold text-ink transition hover:bg-white"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={isDeleting}
                onClick={() => void handleDelete()}
                className="rounded-2xl bg-red-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-red-700 disabled:opacity-60"
              >
                {isDeleting ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </motion.main>
  );
}
