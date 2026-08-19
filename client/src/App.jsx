import { useState } from "react";
import { motion } from "framer-motion";
import CodeEditor, { MAX_CHARS } from "./components/CodeEditor";
import ReviewButton from "./components/ReviewButton";
import IssueList from "./components/IssueList";
import ErrorBanner from "./components/ErrorBanner";
import HistoryPanel from "./components/HistoryPanel";
import ProjectUpload from "./components/ProjectUpload";
import ScanProgress from "./components/ScanProgress";
import ProjectOverview from "./components/ProjectOverview";
import ProjectFindingsList from "./components/ProjectFindingsList";
import useSessionId from "./hooks/useSessionId";
import { reviewCode, analyzeProject, scoreProject } from "./api/client";

export default function App() {
  const sessionId = useSessionId();
  const [code, setCode] = useState("");
  const [language, setLanguage] = useState("javascript");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [mode, setMode] = useState("paste"); // "paste" | "upload"

  // Upload-mode state machine: "idle" -> "analyzing" -> "results" (or an
  // error at either the analyze or score stage, retryable without re-upload).
  const [projectId, setProjectId] = useState(null);
  const [uploadStage, setUploadStage] = useState("idle"); // "idle" | "analyzing" | "scoring" | "results"
  const [analyzedProject, setAnalyzedProject] = useState(null);
  const [projectScore, setProjectScore] = useState(null);
  const [projectError, setProjectError] = useState(null);
  const [failedStage, setFailedStage] = useState(null); // "analyzing" | "scoring"

  // `from` lets a retry after a score-stage failure skip re-running analyze
  // (already have analyzedProject) - it only re-attempts from where it broke.
  async function runAnalyzeAndScore(id, from = "analyzing") {
    setProjectError(null);
    setFailedStage(null);
    try {
      let analyzed = analyzedProject;
      if (from === "analyzing") {
        setUploadStage("analyzing");
        analyzed = await analyzeProject(id);
        setAnalyzedProject(analyzed);
      }

      setUploadStage("scoring");
      const scored = await scoreProject(id);
      setProjectScore(scored);

      setUploadStage("results");
    } catch (err) {
      setFailedStage(from);
      setProjectError(err.message || "Something went wrong. Please try again.");
    }
  }

  function handleUploaded(data) {
    setProjectId(data?.project_id || null);
    setAnalyzedProject(null);
    setProjectScore(null);
    setProjectError(null);
    setFailedStage(null);
    if (data?.project_id) runAnalyzeAndScore(data.project_id, "analyzing");
  }

  function retryProjectStage() {
    if (projectId) runAnalyzeAndScore(projectId, failedStage || "analyzing");
  }

  function resetUpload() {
    setProjectId(null);
    setUploadStage("idle");
    setAnalyzedProject(null);
    setProjectScore(null);
    setProjectError(null);
    setFailedStage(null);
  }

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
          ) : uploadStage === "idle" ? (
            <ProjectUpload sessionId={sessionId} onUploaded={handleUploaded} />
          ) : (
            <div className="flex flex-col gap-3">
              <ScanProgress
                stage={uploadStage === "results" ? "done" : uploadStage}
                errorStage={failedStage}
              />
              {projectError && (
                <div className="flex items-start justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
                  <span className="flex-1">{projectError}</span>
                  <button
                    type="button"
                    onClick={retryProjectStage}
                    className="shrink-0 rounded border border-red-500/30 px-2 py-1 text-xs text-red-200 transition hover:bg-red-500/10"
                  >
                    Retry {failedStage === "scoring" ? "scoring" : "analysis"}
                  </button>
                </div>
              )}
              {uploadStage === "results" && (
                <button
                  type="button"
                  onClick={resetUpload}
                  className="self-start text-xs font-medium text-indigo-400 transition hover:text-indigo-300"
                >
                  ← Upload a different project
                </button>
              )}
            </div>
          )}
        </div>

        {mode === "upload" && uploadStage === "results" && analyzedProject && projectScore && (
          <motion.section
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3 }}
            className="mt-8 flex flex-col gap-6"
          >
            <ProjectOverview project={analyzedProject} score={projectScore} />
            <ProjectFindingsList
              findings={analyzedProject.findings}
              files={analyzedProject.files}
              language={analyzedProject.project?.languages?.[0]}
              projectId={projectId}
            />
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
