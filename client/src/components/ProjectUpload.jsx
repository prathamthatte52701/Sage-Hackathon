import { useRef, useState } from "react";
import { motion } from "framer-motion";
import ErrorBanner from "./ErrorBanner";
import { uploadProject } from "../api/client";

const MAX_SIZE = 20 * 1024 * 1024;

// Drag-and-drop (or click-to-browse) ZIP uploader for project-level review.
// Validates client-side (extension + a soft size warning), then uploads with
// a real progress bar driven by axios onUploadProgress. Hands the parsed
// project payload back to the parent via onUploaded - no results rendering here.
export default function ProjectUpload({ sessionId, onUploaded }) {
  const inputRef = useRef(null);
  const [dragOver, setDragOver] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState(null);
  const [warning, setWarning] = useState(null);
  const [fileName, setFileName] = useState(null);

  async function handleFile(file) {
    if (!file) return;
    setError(null);
    setWarning(null);

    if (!file.name.toLowerCase().endsWith(".zip")) {
      setError("Only .zip files are supported. Please select a zipped project archive.");
      return;
    }
    if (file.size > MAX_SIZE) {
      setWarning("This file looks larger than 20MB - the server may reject it.");
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
        <p className="text-xs text-zinc-600">ZIP archives only, up to 20MB</p>
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
    </div>
  );
}
