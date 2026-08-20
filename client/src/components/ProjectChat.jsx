import { useState } from "react";
import { motion } from "framer-motion";
import { chatAboutProject } from "../api/client";

// Stage 1 (keyword-retrieval) codebase chat. Every answer is grounded in
// cited_files returned by the backend - never rendered as fact without them.
export default function ProjectChat({ projectId }) {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]); // {question, answer, citedFiles, error}[]
  const [loading, setLoading] = useState(false);

  async function handleAsk(e) {
    e.preventDefault();
    const q = question.trim();
    if (!q || loading) return;
    setQuestion("");
    setLoading(true);
    try {
      const data = await chatAboutProject(projectId, q);
      setMessages((m) => [...m, { question: q, answer: data.answer, citedFiles: data.cited_files || [] }]);
    } catch (err) {
      setMessages((m) => [...m, { question: q, error: err.message || "Could not answer that question." }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Ask about this codebase</p>

      {messages.length > 0 && (
        <div className="flex flex-col gap-3">
          {messages.map((m, i) => (
            <motion.div
              key={i}
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex flex-col gap-1.5"
            >
              <p className="text-sm font-medium text-zinc-200">{m.question}</p>
              {m.error ? (
                <p className="text-sm text-red-300">{m.error}</p>
              ) : (
                <>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-400">{m.answer}</p>
                  {m.citedFiles.length > 0 && (
                    <div className="flex flex-wrap gap-1.5">
                      {m.citedFiles.map((f) => (
                        <span
                          key={f}
                          className="rounded-full border border-zinc-700 px-2 py-0.5 font-mono text-[11px] text-zinc-500"
                        >
                          {f}
                        </span>
                      ))}
                    </div>
                  )}
                </>
              )}
            </motion.div>
          ))}
        </div>
      )}

      <form onSubmit={handleAsk} className="flex gap-2">
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          disabled={loading}
          placeholder="e.g. where is authentication implemented?"
          className="flex-1 rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2 text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-indigo-500/50 focus:outline-none disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!question.trim() || loading}
          className="shrink-0 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? "..." : "Ask"}
        </button>
      </form>
    </div>
  );
}
