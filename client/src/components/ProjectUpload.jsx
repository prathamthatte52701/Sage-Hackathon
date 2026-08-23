import React, { useRef, useState } from "react";
import {
  UploadCloud,
  GitBranch,
  AlertTriangle,
  FileArchive,
  ArrowRight,
  Loader2,
  Play,
  CheckCircle2,
  Zap,
  Cpu,
  Layers,
} from "lucide-react";
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

  const sampleRepos = [
    { label: "CODE MASTER AI Demo", url: "prathamthatte52701/Sage-Hackathon" },
    { label: "Flask Web Framework", url: "pallets/flask" },
    { label: "FastAPI Core", url: "fastapi/fastapi" },
  ];

  async function handleGithubImport(targetUrl) {
    const urlToUse = (targetUrl || repoUrl).trim();
    if (!urlToUse || importing) return;
    setError(null);
    setImporting(true);
    try {
      const data = await importFromGithub(urlToUse, sessionId);
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

  // Sample Demo Runner
  async function handleSampleDemo() {
    setUploading(true);
    setError(null);
    try {
      const data = await importFromGithub("prathamthatte52701/Sage-Hackathon", sessionId);
      onUploaded?.(data);
    } catch (err) {
      setError(err.message || "Sample demo import failed.");
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
    <div className="max-w-4xl mx-auto space-y-8 select-none py-4">
      {/* Control Center Header */}
      <div className="text-center space-y-3">
        <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-[#7C8CFF]/10 border border-[#7C8CFF]/30 text-[#7C8CFF] text-xs font-mono font-semibold">
          <Cpu className="w-3.5 h-3.5" />
          <span>CODEBASE INGESTION CONTROL CENTER</span>
        </div>

        <h2 className="text-3xl font-extrabold text-[#F4F7FB] tracking-tight">
          Import & Analyze Repository
        </h2>
        <p className="text-xs text-[#9AA4B2] max-w-xl mx-auto leading-relaxed">
          Drop a project ZIP archive or input a GitHub repository URL to launch real-time AST rule scanning & grounded AI review.
        </p>
      </div>

      {/* Visual Ingestion Pipeline Flow */}
      <div className="p-3.5 rounded-xl bg-[#090B10] border border-[#232936] flex flex-wrap items-center justify-between gap-3 text-xs font-mono text-[#9AA4B2]">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-[#36D399]" />
          <span className="text-[#F4F7FB] font-semibold">1. REPOSITORY INGESTION</span>
        </div>
        <ArrowRight className="w-3.5 h-3.5 text-[#687386]" />
        <div className="flex items-center gap-2 text-[#7C8CFF]">
          <Zap className="w-3.5 h-3.5" />
          <span>2. AST SCANNING</span>
        </div>
        <ArrowRight className="w-3.5 h-3.5 text-[#687386]" />
        <div className="flex items-center gap-2 text-[#F4C95D]">
          <Layers className="w-3.5 h-3.5" />
          <span>3. AI GROUNDED RAG</span>
        </div>
        <ArrowRight className="w-3.5 h-3.5 text-[#687386]" />
        <div className="flex items-center gap-2 text-[#36D399]">
          <CheckCircle2 className="w-3.5 h-3.5" />
          <span>4. HEALTH SCORE</span>
        </div>
      </div>

      {/* Source Selector Tabs */}
      <div className="flex justify-center">
        <div className="inline-flex rounded-xl border border-[#232936] bg-[#10131A] p-1.5 shadow-xl">
          <button
            type="button"
            onClick={() => setSource("zip")}
            className={`flex items-center gap-2.5 rounded-lg px-5 py-2.5 text-xs font-semibold transition-all ${
              source === "zip"
                ? "bg-[#151922] text-[#F4F7FB] border border-[#232936]"
                : "text-[#9AA4B2] hover:text-[#F4F7FB]"
            }`}
          >
            <FileArchive className="w-4 h-4 text-[#7C8CFF]" />
            <span>ZIP Project Archive</span>
          </button>
          <button
            type="button"
            onClick={() => setSource("github")}
            className={`flex items-center gap-2.5 rounded-lg px-5 py-2.5 text-xs font-semibold transition-all ${
              source === "github"
                ? "bg-[#151922] text-[#F4F7FB] border border-[#232936]"
                : "text-[#9AA4B2] hover:text-[#F4F7FB]"
            }`}
          >
            <GitBranch className="w-4 h-4 text-[#7C8CFF]" />
            <span>GitHub Repository</span>
          </button>
        </div>
      </div>

      {/* Main Import Surface */}
      <div className="cm-card p-8 border-[#232936] bg-[#10131A] relative shadow-xl">
        {source === "github" ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleGithubImport();
            }}
            className="space-y-6"
          >
            <div className="space-y-2">
              <label className="text-xs font-mono font-semibold text-[#7C8CFF] uppercase tracking-wider block">
                GITHUB REPOSITORY URL
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  disabled={importing}
                  placeholder="https://github.com/owner/repository or owner/repo"
                  className="flex-1 rounded-xl border border-[#232936] bg-[#090B10] px-4 py-3 text-sm text-[#F4F7FB] font-mono placeholder:text-[#687386] focus:border-[#7C8CFF] focus:outline-none"
                />
                <button
                  type="submit"
                  disabled={!repoUrl.trim() || importing}
                  className="cm-btn-primary px-6 py-3 text-xs shrink-0 disabled:opacity-50"
                >
                  {importing ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Importing...</span>
                    </>
                  ) : (
                    <>
                      <span>Import & Review</span>
                      <ArrowRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Quick Sample Repository Chips */}
            <div className="space-y-2 pt-2 border-t border-[#232936]">
              <span className="text-[10px] font-mono text-[#687386] uppercase tracking-wider block">
                TRY SAMPLE REPOSITORIES
              </span>
              <div className="flex flex-wrap gap-2">
                {sampleRepos.map((sr, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => {
                      setRepoUrl(sr.url);
                      handleGithubImport(sr.url);
                    }}
                    className="px-3 py-1.5 rounded-lg bg-[#090B10] border border-[#232936] text-xs font-mono text-[#9AA4B2] hover:text-[#F4F7FB] hover:border-[#7C8CFF]/50 transition-all flex items-center gap-1.5"
                  >
                    <GitBranch className="w-3 h-3 text-[#7C8CFF]" />
                    <span>{sr.label}</span>
                  </button>
                ))}
              </div>
            </div>

            <ErrorBanner message={error} onDismiss={() => setError(null)} />
          </form>
        ) : (
          <div className="space-y-6">
            <div
              onDragOver={(e) => {
                e.preventDefault();
                if (!uploading) setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => !uploading && inputRef.current?.click()}
              className={`flex flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed p-12 text-center transition-all ${
                uploading
                  ? "cursor-not-allowed border-[#232936] bg-[#090B10]/50 opacity-60"
                  : dragOver
                  ? "cursor-pointer border-[#7C8CFF] bg-[#7C8CFF]/10"
                  : "cursor-pointer border-[#232936] bg-[#090B10] hover:border-[#7C8CFF]/60 hover:bg-[#151922]"
              }`}
            >
              <input
                ref={inputRef}
                type="file"
                accept=".zip"
                className="hidden"
                onChange={(e) => handleFile(e.target.files?.[0])}
              />
              <div className="w-14 h-14 rounded-2xl bg-[#7C8CFF]/15 border border-[#7C8CFF]/30 flex items-center justify-center text-[#7C8CFF]">
                <UploadCloud className="w-7 h-7" />
              </div>

              <div className="space-y-1">
                <p className="text-base font-bold text-[#F4F7FB]">
                  {uploading ? "Uploading Project Archive..." : "Drop your project .ZIP archive here"}
                </p>
                <p className="text-xs text-[#9AA4B2]">
                  Or click anywhere to browse local files
                </p>
              </div>

              <div className="flex items-center gap-2 text-[11px] font-mono text-[#687386]">
                <FileArchive className="w-3.5 h-3.5" />
                <span>ZIP archives up to 300MB, 5,000 analyzable files</span>
              </div>
            </div>

            {uploading && (
              <div className="space-y-2 font-mono text-xs p-4 rounded-xl bg-[#090B10] border border-[#232936]">
                <div className="flex items-center justify-between text-[#9AA4B2]">
                  <span className="truncate flex items-center gap-2">
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-[#7C8CFF]" />
                    <span>{fileName || "Project Archive"}</span>
                  </span>
                  <span className="text-[#7C8CFF] font-bold">{progress}%</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-[#151922]">
                  <div
                    className="h-full bg-gradient-to-r from-[#7C8CFF] to-[#36D399] transition-all duration-150"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            )}

            {warning && !error && (
              <div className="flex items-center gap-2 p-3.5 rounded-xl border border-[#F4C95D]/30 bg-[#F4C95D]/10 text-xs text-[#F4C95D]">
                <AlertTriangle className="w-4 h-4 shrink-0" />
                <span>{warning}</span>
              </div>
            )}

            {/* Quick Demo Trigger Button */}
            <div className="pt-2 border-t border-[#232936] flex items-center justify-between text-xs font-mono">
              <span className="text-[#687386]">Want to see a live demo project first?</span>
              <button
                type="button"
                onClick={handleSampleDemo}
                disabled={uploading}
                className="cm-btn-secondary py-1.5 px-3 text-xs text-[#7C8CFF] border-[#7C8CFF]/30 hover:border-[#7C8CFF]"
              >
                <Play className="w-3 h-3 text-[#36D399]" />
                <span>Launch Sample Demo Review</span>
              </button>
            </div>

            <ErrorBanner message={error} onDismiss={() => setError(null)} />
          </div>
        )}
      </div>
    </div>
  );
}
