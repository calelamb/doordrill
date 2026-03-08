import { useId, useRef, useState } from "react";
import { AlertCircle, CheckCircle2, FileText, Loader2, UploadCloud } from "lucide-react";

import { validateKnowledgeFile } from "../lib/knowledge";

type DocumentUploadZoneProps = {
  onFileSelected?: (file: File) => void;
  onUpload: (file: File, name: string) => Promise<void>;
  uploadState: "idle" | "uploading" | "success" | "error";
  uploadProgress: number;
  errorMessage?: string | null;
};

function formatFileSize(bytes: number) {
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DocumentUploadZone({
  onFileSelected,
  onUpload,
  uploadState,
  uploadProgress,
  errorMessage,
}: DocumentUploadZoneProps) {
  const inputId = useId();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [documentName, setDocumentName] = useState("");
  const [dragActive, setDragActive] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const activeError = localError || errorMessage || null;

  function acceptFile(file: File | null) {
    if (!file) {
      return;
    }
    const validationError = validateKnowledgeFile(file);
    if (validationError) {
      setSelectedFile(null);
      setDocumentName("");
      setLocalError(validationError);
      return;
    }

    setSelectedFile(file);
    setDocumentName(file.name.replace(/\.[^.]+$/, ""));
    setLocalError(null);
    onFileSelected?.(file);
  }

  async function handleUpload() {
    if (!selectedFile) {
      setLocalError("Choose a document before uploading.");
      return;
    }
    if (!documentName.trim()) {
      setLocalError("Add a display name for this document.");
      return;
    }
    setLocalError(null);
    await onUpload(selectedFile, documentName.trim());
  }

  return (
    <section className="rounded-[32px] border border-border/80 bg-white/55 p-6 shadow-[0_24px_60px_rgba(45,90,61,0.08)] backdrop-blur-2xl">
      <div className="flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.24em] text-accent/70">Upload Material</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight text-ink">Bring in scripts, playbooks, and manuals</h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted">
            Drop a document here or browse for a file. Accepted types: PDF, DOCX, TXT. Max size: 25MB.
          </p>
        </div>
        <div className="rounded-full border border-border-strong/80 bg-surface-solid/80 px-4 py-2 text-xs font-medium text-muted">
          Files stay org-scoped and power grading plus coaching.
        </div>
      </div>

      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onDragEnter={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragOver={(event) => {
          event.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={(event) => {
          event.preventDefault();
          if (event.currentTarget === event.target) {
            setDragActive(false);
          }
        }}
        onDrop={(event) => {
          event.preventDefault();
          setDragActive(false);
          acceptFile(event.dataTransfer.files?.[0] ?? null);
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            inputRef.current?.click();
          }
        }}
        className={`mt-6 rounded-[28px] border border-dashed px-6 py-8 transition-all duration-200 ${
          dragActive
            ? "border-accent bg-accent-soft/70 shadow-[0_0_0_6px_rgba(45,90,61,0.08)]"
            : "border-border-strong/70 bg-[linear-gradient(135deg,rgba(255,255,255,0.78),rgba(244,248,242,0.8))] hover:border-accent/45 hover:bg-white/70"
        }`}
        aria-label="Upload training material"
      >
        <input
          id={inputId}
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.txt"
          className="hidden"
          onChange={(event) => acceptFile(event.target.files?.[0] ?? null)}
        />

        <div className="flex flex-col items-center gap-4 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-accent text-white shadow-lg shadow-accent/25">
            <UploadCloud className="h-8 w-8" />
          </div>
          <div className="space-y-2">
            <p className="text-lg font-semibold text-ink">Drop files here or click to browse</p>
            <p className="text-sm text-muted">Use clear file names so managers can spot the right playbook fast.</p>
          </div>
        </div>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-[1.4fr_0.6fr]">
        <div className="rounded-[24px] border border-border/70 bg-surface-solid/85 p-4">
          <label htmlFor={`${inputId}-name`} className="text-xs font-semibold uppercase tracking-[0.18em] text-muted">
            Display Name
          </label>
          <input
            id={`${inputId}-name`}
            value={documentName}
            onChange={(event) => setDocumentName(event.target.value)}
            placeholder="Ex. Summer Territory Objection Manual"
            className="mt-3 w-full rounded-2xl border border-border bg-white/90 px-4 py-3 text-sm text-ink outline-none transition-colors focus:border-accent"
          />
          <div className="mt-4 flex flex-wrap items-center gap-3 text-sm text-muted">
            <span className="inline-flex items-center gap-2 rounded-full bg-accent-soft/70 px-3 py-1.5 text-accent">
              <FileText className="h-4 w-4" />
              {selectedFile ? selectedFile.name : "No file selected"}
            </span>
            {selectedFile ? <span>{formatFileSize(selectedFile.size)}</span> : null}
          </div>
        </div>

        <div className="rounded-[24px] border border-border/70 bg-surface-solid/85 p-4">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-muted">Upload Status</p>
          <div className="mt-4 min-h-[104px]">
            {uploadState === "uploading" ? (
              <div className="space-y-3">
                <div className="flex items-center gap-2 text-sm font-medium text-ink">
                  <Loader2 className="h-4 w-4 animate-spin text-accent" />
                  Uploading and queueing processing
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-accent-soft/60">
                  <div
                    className="h-full rounded-full bg-accent transition-[width] duration-200"
                    style={{ width: `${Math.max(8, uploadProgress)}%` }}
                  />
                </div>
                <p className="text-xs text-muted">{uploadProgress}% complete</p>
              </div>
            ) : null}

            {uploadState === "success" ? (
              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-2 font-medium text-accent">
                  <CheckCircle2 className="h-4 w-4" />
                  Upload queued successfully
                </div>
                <p className="text-muted">The document is now processing in the background.</p>
              </div>
            ) : null}

            {uploadState === "error" ? (
              <div className="space-y-2 text-sm">
                <div className="flex items-center gap-2 font-medium text-error">
                  <AlertCircle className="h-4 w-4" />
                  Upload failed
                </div>
                <p className="text-muted">{activeError ?? "Try a different file or retry the upload."}</p>
              </div>
            ) : null}

            {uploadState === "idle" ? (
              <div className="space-y-2 text-sm text-muted">
                <p>Accepted: PDF, DOCX, TXT</p>
                <p>Drag-over highlights the drop zone so uploads feel obvious on desktop and mobile.</p>
              </div>
            ) : null}
          </div>
          {activeError ? <p className="mt-4 text-sm text-error">{activeError}</p> : null}
          <button
            type="button"
            disabled={uploadState === "uploading"}
            onClick={() => void handleUpload()}
            className="mt-4 inline-flex w-full items-center justify-center rounded-2xl bg-accent px-4 py-3 text-sm font-semibold text-white transition hover:bg-accent-hover disabled:opacity-60"
          >
            {uploadState === "uploading" ? "Uploading..." : "Upload Document"}
          </button>
        </div>
      </div>
    </section>
  );
}
