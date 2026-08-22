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
import Card3DTilt from "./Card3DTilt";
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
  const busy = uploading || importing;

  const sampleRepos = [
    { label: "Sage-Hackathon", url: "prathamthatte52701/Sage-Hackathon" },
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

  // Instant Sample Demo Runner using client fetch or sample upload
  async function handleSampleDemo() {
    setImporting(true);
    setSource("github");
    setRepoUrl("prathamthatte52701/Sage-Hackathon");
    setError(null);
    try {
      const data = await importFromGithub("prathamthatte52701/Sage-Hackathon", sessionId);
      onUploaded?.(data);
    } catch (err) {
      setError(err.message || "Sample demo import failed.");
    } finally {
      setImporting(false);
    }
  }

  function onDrop(e) {
    e.preventDefault();
    setDragOver(false);
    if (busy) return;
    handleFile(e.dataTransfer.files?.[0]);
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6 select-none py-2 sm:py-4">
      {/* Control Center Header */}
      <div className="text-center space-y-3">
        <div className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-[#7C8CFF]/10 border border-[#7C8CFF]/30 text-[#7C8CFF] text-xs font-mono font-semibold shadow-lg shadow-[#7C8CFF]/10">
          <Cpu className="w-3.5 h-3.5" />
          <span>CODEBASE INGESTION</span>
        </div>

        <h2 className="text-2xl sm:text-3xl font-extrabold text-[#F4F7FB] tracking-tight">
          Import & Analyze Repository
        </h2>
        <p className="text-xs text-[#9AA4B2] max-w-xl mx-auto leading-relaxed">
          Drop a project ZIP archive or input a GitHub repository URL to launch real-time AST rule scanning & grounded AI review.
        </p>
      </div>

      {/* Visual Ingestion Pipeline Flow */}
      <div className="p-3 rounded-xl bg-[#090B10] border border-[#232936] grid grid-cols-1 sm:grid-cols-4 gap-3 text-xs font-mono text-[#9AA4B2] shadow-inner">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-[#36D399]" />
          <span className="text-[#F4F7FB] font-semibold">1. Ingest</span>
        </div>
        <div className="flex items-center gap-2 text-[#7C8CFF]">
          <Zap className="w-3.5 h-3.5" />
          <span>2. AST Scan</span>
        </div>
        <div className="flex items-center gap-2 text-[#F4C95D]">
          <Layers className="w-3.5 h-3.5" />
          <span>3. Evidence Review</span>
        </div>
        <div className="flex items-center gap-2 text-[#36D399]">
          <CheckCircle2 className="w-3.5 h-3.5" />
          <span>4. Score</span>
        </div>
      </div>

      {/* Source Selector Tabs */}
      <div className="flex justify-center">
        <div className="inline-flex max-w-full rounded-xl border border-[#232936] bg-[#10131A] p-1.5 shadow-xl overflow-x-auto">
          <button
            type="button"
            onClick={() => !busy && setSource("zip")}
            disabled={busy}
            className={`flex items-center gap-2.5 rounded-lg px-5 py-2.5 text-xs font-semibold transition-all ${
              source === "zip"
                ? "bg-[#151922] text-[#F4F7FB] border border-[#232936] shadow-md shadow-[#7C8CFF]/10"
                : "text-[#9AA4B2] hover:text-[#F4F7FB]"
            }`}
          >
            <FileArchive className="w-4 h-4 text-[#7C8CFF]" />
            <span>ZIP Project Archive</span>
          </button>
          <button
            type="button"
            onClick={() => !busy && setSource("github")}
            disabled={busy}
            className={`flex items-center gap-2.5 rounded-lg px-5 py-2.5 text-xs font-semibold transition-all ${
              source === "github"
                ? "bg-[#151922] text-[#F4F7FB] border border-[#232936] shadow-md shadow-[#7C8CFF]/10"
                : "text-[#9AA4B2] hover:text-[#F4F7FB]"
            }`}
          >
            <GitBranch className="w-4 h-4 text-[#7C8CFF]" />
            <span>GitHub Repository</span>
          </button>
        </div>
      </div>

      {/* 3D Glassmorphic Import Container */}
      <Card3DTilt className="cm-card p-4 sm:p-6 lg:p-8 border-[#232936] bg-[#10131A] relative shadow-2xl">
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
                  className="flex-1 rounded-xl border border-[#232936] bg-[#090B10] px-4 py-3 text-sm text-[#F4F7FB] font-mono placeholder:text-[#687386] focus:border-[#7C8CFF] focus:outline-none shadow-inner"
                />
                <button
                  type="submit"
                  disabled={!repoUrl.trim() || importing}
                  className="cm-btn-primary px-6 py-3 text-xs shrink-0 disabled:opacity-50 shadow-lg shadow-[#7C8CFF]/20"
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
                    disabled={importing}
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
                if (!busy) setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={onDrop}
              onClick={() => !busy && inputRef.current?.click()}
              className={`flex flex-col items-center justify-center gap-4 rounded-xl border-2 border-dashed p-8 sm:p-10 lg:p-12 text-center transition-all ${
                busy
                  ? "cursor-not-allowed border-[#232936] bg-[#090B10]/50 opacity-60"
                  : dragOver
                  ? "cursor-pointer border-[#7C8CFF] bg-[#7C8CFF]/15 scale-[1.01]"
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
              <div className="relative">
                <div className="w-16 h-16 rounded-2xl bg-[#7C8CFF]/15 border border-[#7C8CFF]/30 flex items-center justify-center text-[#7C8CFF] shadow-lg shadow-[#7C8CFF]/20">
                  <UploadCloud className="w-8 h-8" />
                </div>
                <span className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-[#36D399]" />
              </div>

              <div className="space-y-1">
                <p className="text-base font-bold text-[#F4F7FB]">
                  {uploading
                    ? "Uploading project archive..."
                    : importing
                    ? "Importing GitHub repository..."
                    : "Drop your project .ZIP archive here"}
                </p>
                <p className="text-xs text-[#9AA4B2]">
                  {busy ? "This can take a moment for larger repositories." : "Or click anywhere to browse local files"}
                </p>
              </div>

              <div className="flex items-center gap-2 text-[11px] font-mono text-[#687386]">
                <FileArchive className="w-3.5 h-3.5" />
                <span>ZIP archives up to 300MB, 2,000 files</span>
              </div>
            </div>

            {busy && (
              <div className="space-y-2 font-mono text-xs p-4 rounded-xl bg-[#090B10] border border-[#232936]">
                <div className="flex items-center justify-between text-[#9AA4B2]">
                  <span className="truncate flex items-center gap-2">
                    <Loader2 className="w-3.5 h-3.5 animate-spin text-[#7C8CFF]" />
                    <span>{uploading ? fileName || "Project Archive" : repoUrl || "Sample repository"}</span>
                  </span>
                  <span className="text-[#7C8CFF] font-bold">{uploading ? `${progress}%` : "Importing"}</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-[#151922]">
                  <div
                    className={`h-full bg-gradient-to-r from-[#7C8CFF] to-[#36D399] transition-all duration-150 ${
                      importing ? "w-1/2 animate-pulse" : ""
                    }`}
                    style={uploading ? { width: `${progress}%` } : undefined}
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
                disabled={busy}
                className="cm-btn-secondary py-1.5 px-3 text-xs text-[#7C8CFF] border-[#7C8CFF]/30 hover:border-[#7C8CFF]"
              >
                <Play className="w-3 h-3 text-[#36D399]" />
                <span>{importing ? "Importing sample..." : "Launch Sample Demo Review"}</span>
              </button>
            </div>

            <ErrorBanner message={error} onDismiss={() => setError(null)} />
          </div>
        )}
      </Card3DTilt>
    </div>
  );
}
