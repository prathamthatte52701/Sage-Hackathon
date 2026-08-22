import React, { useRef, useState } from "react";
import { UploadCloud, GitBranch, AlertTriangle, FileArchive, ArrowRight, Loader2 } from "lucide-react";
import ErrorBanner from "./ErrorBanner";
import { uploadProject, importFromGithub } from "../api/client";

const MAX_SIZE = 300 * 1024 * 1024;

export default function ProjectUpload({ sessionId, onUploaded }) {
  const inputRef = useRef(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);
  const [warning, setWarning] = useState(null);
  const [fileName, setFileName] = useState(null);

  const [source, setSource] = useState("zip"); // "zip" | "github"
  const [repoUrl, setRepoUrl] = useState("");
  const [importing, setImporting] = useState(false);

  async function handleGithubImport(e) {
    e.preventDefault();
    if (!repoUrl.trim() || importing) return;
    setError(null);
    setImporting(true);
    try {
      const data = await importFromGithub(repoUrl.trim(), sessionId);
      onUploaded?.(data);
    } catch (err) {
      setError(err.message || "Could not import this repository.");
    } finally {
      setImporting(false);
    }
  }

  async function handleFile(file) {
    if (!file) return;
    setError(null);
    setWarning(null);

    if (!file.name.toLowerCase().endsWith(".zip")) {
      setError("Only .zip files are supported. Please select a zipped project archive.");
      return;
    }
    if (file.size > MAX_SIZE) {
      setWarning("This file looks larger than 300MB - the server may reject it.");
    }

    setFileName(file.name);
    setUploading(true);
    setProgress(0);
    try {
      const data = await uploadProject(file, sessionId, (progressEvent) => {
        if (progressEvent.total) {
          setProgress(Math.round((progressEvent.loaded / progressEvent.total) * 100));
        }
      });
      onUploaded?.(data);
    } catch (err) {
      setError(err.message || "Upload failed. Please try again.");
    } finally {
      setUploading(false);
    }
  }

  function onDrop(e) {
    e.preventDefault();
    setDragOver(false);
    if (uploading) return;
    handleFile(e.dataTransfer.files?.[0]);
  }

  return (
    <div className="max-w-2xl mx-auto space-y-6">
      <div className="text-center space-y-2">
        <h2 className="text-xl font-bold text-[#F4F7FB] tracking-tight">
          Analyze a Codebase
        </h2>
        <p className="text-xs text-[#9AA4B2]">
          Import a GitHub repository or drop a project ZIP archive to trigger evidence-backed code review.
        </p>
      </div>

      {/* Source Selector Tabs */}
      <div className="flex justify-center">
        <div className="inline-flex rounded-lg border border-[#232936] bg-[#10131A] p-1">
          <button
            type="button"
            onClick={() => setSource("zip")}
            className={`flex items-center gap-2 rounded-md px-4 py-2 text-xs font-semibold transition-all ${
              source === "zip"
                ? "bg-[#151922] text-[#F4F7FB] border border-[#232936] shadow"
                : "text-[#9AA4B2] hover:text-[#F4F7FB]"
            }`}
          >
            <FileArchive className="w-4 h-4 text-[#7C8CFF]" />
            <span>ZIP Archive</span>
          </button>
          <button
            type="button"
            onClick={() => setSource("github")}
            className={`flex items-center gap-2 rounded-md px-4 py-2 text-xs font-semibold transition-all ${
              source === "github"
                ? "bg-[#151922] text-[#F4F7FB] border border-[#232936] shadow"
                : "text-[#9AA4B2] hover:text-[#F4F7FB]"
            }`}
          >
            <GitBranch className="w-4 h-4 text-[#7C8CFF]" />
            <span>GitHub Repository</span>
          </button>
        </div>
      </div>

      {/* Main Import Box (Specification §9) */}
      <div className="cm-card p-8 border-[#232936] bg-[#10131A]">
        {source === "github" ? (
          <form onSubmit={handleGithubImport} className="space-y-4">
            <div className="space-y-2">
              <label className="text-xs font-mono font-medium text-[#9AA4B2]">
                GITHUB REPOSITORY URL
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  disabled={importing}
                  placeholder="https://github.com/owner/repository"
                  className="flex-1 rounded-lg border border-[#232936] bg-[#090B10] px-4 py-2.5 text-sm text-[#F4F7FB] font-mono placeholder:text-[#687386] focus:border-[#7C8CFF] focus:outline-none disabled:opacity-50"
                />
                <button
                  type="submit"
                  disabled={!repoUrl.trim() || importing}
                  className="cm-btn-primary px-5 py-2.5 text-xs shrink-0 disabled:opacity-50"
                >
                  {importing ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Importing...</span>
                    </>
                  ) : (
                    <>
                      <span>Import</span>
                      <ArrowRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              </div>
              <p className="text-[11px] font-mono text-[#687386]">
                Supports public GitHub repositories with auto-indexing.
              </p>
            </div>
            <ErrorBanner message={error} onDismiss={() => setError(null)} />
          </form>
        ) : (
          <div className="space-y-4">
            <div
              onDragOver={(e) => {
                e.preventDefault();
                if (!uploading) setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => !uploading && inputRef.current?.click()}
              className={`flex flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-10 text-center transition-all ${
                uploading
                  ? "cursor-not-allowed border-[#232936] bg-[#090B10]/50 opacity-60"
                  : dragOver
                  ? "cursor-pointer border-[#7C8CFF] bg-[#7C8CFF]/10"
                  : "cursor-pointer border-[#232936] bg-[#090B10] hover:border-[#7C8CFF]/50 hover:bg-[#151922]"
              }`}
            >
              <input
                ref={inputRef}
                type="file"
                accept=".zip"
                className="hidden"
                onChange={(e) => handleFile(e.target.files?.[0])}
              />
              <div className="w-12 h-12 rounded-full bg-[#7C8CFF]/10 border border-[#7C8CFF]/30 flex items-center justify-center text-[#7C8CFF]">
                <UploadCloud className="w-6 h-6" />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-semibold text-[#F4F7FB]">
                  {uploading ? "Uploading project ZIP..." : "Drop your project ZIP here"}
                </p>
                <p className="text-xs text-[#9AA4B2]">
                  Or click to browse from your computer
                </p>
              </div>
              <span className="text-[11px] font-mono text-[#687386]">
                Supports archives up to 300MB
              </span>
            </div>

            {uploading && (
              <div className="space-y-1.5 font-mono text-xs">
                <div className="flex items-center justify-between text-[#9AA4B2]">
                  <span className="truncate">{fileName}</span>
                  <span className="text-[#7C8CFF] font-semibold">{progress}%</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-[#090B10]">
                  <div
                    className="h-full bg-[#7C8CFF] transition-all duration-150"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            )}

            {warning && !error && (
              <div className="flex items-center gap-2 p-3 rounded-lg border border-[#F4C95D]/30 bg-[#F4C95D]/10 text-xs text-[#F4C95D]">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{warning}</span>
              </div>
            )}

            <ErrorBanner message={error} onDismiss={() => setError(null)} />
          </div>
        )}
      </div>
    </div>
  );
}
