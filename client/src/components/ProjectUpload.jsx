import { useRef, useState } from "react";
import { motion } from "framer-motion";
import ErrorBanner from "./ErrorBanner";
import { uploadProject, importFromGithub } from "../api/client";

const MAX_SIZE = 300 * 1024 * 1024;

// Drag-and-drop (or click-to-browse) ZIP uploader for project-level review,
// plus a GitHub URL import that feeds the same onUploaded callback (both
// paths return the identical project representation shape from the backend).
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
    <div className="flex flex-col gap-3">
      <div className="inline-flex w-fit rounded-lg border border-zinc-800 bg-zinc-900/60 p-1">
        <button
          type="button"
          onClick={() => setSource("zip")}
          className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
            source === "zip" ? "bg-indigo-600 text-white" : "text-zinc-400 hover:text-zinc-200"
          }`}
        >
          ZIP
        </button>
        <button
          type="button"
          onClick={() => setSource("github")}
          className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
            source === "github" ? "bg-indigo-600 text-white" : "text-zinc-400 hover:text-zinc-200"
          }`}
        >
          GitHub
        </button>
      </div>

      {source === "github" ? (
        <form onSubmit={handleGithubImport} className="flex flex-col gap-2">
          <div className="flex gap-2">
            <input
              type="text"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              disabled={importing}
              placeholder="owner/repo or https://github.com/owner/repo"
              className="flex-1 rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-indigo-500/50 focus:outline-none disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!repoUrl.trim() || importing}
              className="shrink-0 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {importing ? "Importing..." : "Import"}
            </button>
          </div>
          <p className="text-xs text-zinc-600">Public repositories only — no login required.</p>
          <ErrorBanner message={error} onDismiss={() => setError(null)} />
        </form>
      ) : (
      <>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!uploading) setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => !uploading && inputRef.current?.click()}
        className={`flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-6 py-12 text-center transition-colors ${
          uploading
            ? "cursor-not-allowed border-zinc-800 bg-zinc-900/40"
            : dragOver
              ? "cursor-pointer border-indigo-500 bg-indigo-500/5"
              : "cursor-pointer border-zinc-700 bg-zinc-900/40 hover:border-zinc-600"
        }`}
      >
        <input
          ref={inputRef}
          type="file"
          accept=".zip"
          className="hidden"
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
        <p className="text-sm text-zinc-300">
          {uploading ? "Uploading..." : "Drag & drop a .zip project here, or click to browse"}
        </p>
        <p className="text-xs text-zinc-600">ZIP archives only, up to 300MB</p>
      </div>

      {uploading && (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between text-xs text-zinc-500">
            <span className="truncate">{fileName}</span>
            <span>{progress}%</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
            <motion.div
              className="h-full rounded-full bg-indigo-500"
              animate={{ width: `${progress}%` }}
              transition={{ duration: 0.15 }}
            />
          </div>
        </div>
      )}

      {warning && !error && (
        <p className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-300">
          {warning}
        </p>
      )}

      <ErrorBanner message={error} onDismiss={() => setError(null)} />
      </>
      )}
    </div>
  );
}
