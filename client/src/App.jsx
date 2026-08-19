import { useState } from "react";
import { motion } from "framer-motion";
import CodeEditor, { MAX_CHARS } from "./components/CodeEditor";
import ReviewButton from "./components/ReviewButton";
import IssueList from "./components/IssueList";
import ErrorBanner from "./components/ErrorBanner";
import HistoryPanel from "./components/HistoryPanel";
import ProjectUpload from "./components/ProjectUpload";
import useSessionId from "./hooks/useSessionId";
import { reviewCode } from "./api/client";

export default function App() {
  const sessionId = useSessionId();
  const [code, setCode] = useState("");
  const [language, setLanguage] = useState("javascript");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [mode, setMode] = useState("paste"); // "paste" | "upload"
  const [projectData, setProjectData] = useState(null);

  const trimmed = code.trim();
  const overLimit = code.length > MAX_CHARS;
  const canSubmit = trimmed.length > 0 && !overLimit;

  async function handleReview() {
    if (!canSubmit || loading) return;
    setLoading(true);
    setError(null);
    try {
      const data = await reviewCode(code, language, sessionId);
      setResult(data);
    } catch (err) {
      setError(err.message || "Review failed. Please try again.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-[#0a0a0f]">
      <div
        className="pointer-events-none fixed inset-x-0 top-0 h-[420px] opacity-40"
        style={{
          background:
            "radial-gradient(60% 100% at 50% 0%, rgba(99,102,241,0.25) 0%, rgba(10,10,15,0) 70%)",
        }}
      />

      <div className="relative mx-auto max-w-4xl px-6 py-12">
        <header className="mb-10 flex items-start justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-indigo-400">
              SW-06
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-50">
              AI Code Reviewer &amp; Debug Assistant
            </h1>
            <p className="mt-2 text-sm text-zinc-500">
              Paste your code, pick a language, and get an instant AI-powered review.
            </p>
          </div>
          <button
            onClick={() => setHistoryOpen(true)}
            className="rounded-lg border border-zinc-800 bg-zinc-900/40 px-3 py-1.5 text-xs text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
          >
            History
          </button>
        </header>

        <HistoryPanel
          sessionId={sessionId}
          open={historyOpen}
          onClose={() => setHistoryOpen(false)}
        />

        <ErrorBanner message={error} onDismiss={() => setError(null)} />

        <div className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6 backdrop-blur-sm">
          <div className="mb-5 inline-flex rounded-lg border border-zinc-800 bg-zinc-900/60 p-1">
            <button
              type="button"
              onClick={() => setMode("paste")}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                mode === "paste"
                  ? "bg-indigo-600 text-white shadow shadow-indigo-600/25"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              Paste Code
            </button>
            <button
              type="button"
              onClick={() => setMode("upload")}
              className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                mode === "upload"
                  ? "bg-indigo-600 text-white shadow shadow-indigo-600/25"
                  : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              Upload Project
            </button>
          </div>

          {mode === "paste" ? (
            <>
              <CodeEditor
                code={code}
                onCodeChange={setCode}
                language={language}
                onLanguageChange={setLanguage}
              />

              <div className="mt-5 flex items-center justify-between">
                <p className="text-xs text-zinc-600">
                  {overLimit
                    ? "Code exceeds the 3,000 character limit."
                    : trimmed.length === 0
                      ? "Paste some code to get started."
                      : " "}
                </p>
                <ReviewButton onClick={handleReview} loading={loading} disabled={!canSubmit} />
              </div>
            </>
          ) : (
            <ProjectUpload sessionId={sessionId} onUploaded={setProjectData} />
          )}
        </div>

        {mode === "upload" && projectData && (
          <motion.section
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
            className="mt-8 rounded-2xl border border-zinc-800 bg-zinc-900/40 p-6 backdrop-blur-sm"
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-medium text-zinc-100">
                {projectData.project?.project?.name || "Project"}
              </h2>
              <span className="text-xs text-zinc-500">
                {projectData.project?.files?.length ?? 0} file
                {(projectData.project?.files?.length ?? 0) === 1 ? "" : "s"}
              </span>
            </div>

            <div className="mb-5 flex flex-wrap gap-2 text-xs">
              {projectData.project?.project?.projectType && (
                <span className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2.5 py-1 text-indigo-300">
                  {projectData.project.project.projectType}
                </span>
              )}
              {(projectData.project?.project?.languages ?? []).map((lang) => (
                <span
                  key={lang}
                  className="rounded-full border border-zinc-800 bg-zinc-900/60 px-2.5 py-1 text-zinc-400"
                >
                  {lang}
                </span>
              ))}
              {(projectData.project?.project?.frameworks ?? []).map((fw) => (
                <span
                  key={fw}
                  className="rounded-full border border-zinc-800 bg-zinc-900/60 px-2.5 py-1 text-zinc-400"
                >
                  {fw}
                </span>
              ))}
            </div>

            {projectData.warnings?.length > 0 && (
              <div className="mb-4 flex flex-col gap-1.5">
                {projectData.warnings.map((w, i) => (
                  <p
                    key={i}
                    className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-300"
                  >
                    {w}
                  </p>
                ))}
              </div>
            )}

            <div className="max-h-72 overflow-y-auto rounded-lg border border-zinc-800">
              {(projectData.project?.files ?? []).map((f, i) => (
                <div
                  key={f.path ?? i}
                  className="flex items-center justify-between gap-3 border-b border-zinc-800 px-4 py-2 text-xs last:border-b-0"
                >
                  <span className="truncate font-mono text-zinc-300">{f.path}</span>
                  <span className="flex shrink-0 gap-3 text-zinc-500">
                    <span>{f.language}</span>
                    <span>{f.size?.toLocaleString?.() ?? f.size} B</span>
                  </span>
                </div>
              ))}
            </div>
          </motion.section>
        )}

        {mode === "paste" && result && (
          <motion.section
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
            className="mt-8"
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-medium text-zinc-100">Review Results</h2>
              <span className="text-xs text-zinc-500">
                {result.issues?.length ?? 0} issue{(result.issues?.length ?? 0) === 1 ? "" : "s"} found
              </span>
            </div>

            {result.summary && (
              <p className="mb-5 rounded-lg border border-zinc-800 bg-zinc-900/60 px-4 py-3 text-sm text-zinc-300">
                {result.summary}
              </p>
            )}

            <IssueList issues={result.issues} code={code} language={language} />
          </motion.section>
        )}
      </div>
    </div>
  );
}
