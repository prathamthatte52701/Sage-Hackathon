import React, { useState } from "react";
import { MessageSquareCode, Send, FileCode, ArrowRight, Loader2, Cpu } from "lucide-react";
import { chatAboutProject } from "../api/client";

export default function ProjectChat({ projectId }) {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);

  const sampleQuestions = [
    "Where does user input reach the database?",
    "Show API authentication flow and endpoints",
    "Where are SQL queries executed?",
  ];

  async function handleAsk(qToAsk) {
    const q = (qToAsk || question).trim();
    if (!q || loading || !projectId) return;
    setQuestion("");
    setLoading(true);
    try {
      const data = await chatAboutProject(projectId, q);
      setMessages((m) => [
        ...m,
        { question: q, answer: data.answer, citedFiles: data.cited_files || [] },
      ]);
    } catch (err) {
      setMessages((m) => [
        ...m,
        { question: q, error: err.message || "Could not answer that question." },
      ]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#232936] pb-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-[#7C8CFF]/15 border border-[#7C8CFF]/30 flex items-center justify-center text-[#7C8CFF]">
            <MessageSquareCode className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-lg font-bold text-[#F4F7FB] tracking-tight">
              Codebase Intelligence Assistant
            </h2>
            <p className="text-xs text-[#9AA4B2]">
              Ask questions grounded in indexed codebase evidence and call paths
            </p>
          </div>
        </div>
      </div>

      {!projectId && (
        <div className="cm-card p-8 border-[#232936] bg-[#10131A] text-center space-y-2">
          <p className="text-sm font-semibold text-[#F4F7FB]">Import a repository to start codebase chat.</p>
          <p className="text-xs text-[#9AA4B2]">
            The assistant answers from indexed files, findings, and call paths after analysis completes.
          </p>
        </div>
      )}

      {/* Suggested Questions */}
      {projectId && messages.length === 0 && (
        <div className="space-y-2">
          <span className="text-xs font-mono text-[#687386] uppercase tracking-wider block">
            SUGGESTED INVESTIGATIONS
          </span>
          <div className="flex flex-wrap gap-2">
            {sampleQuestions.map((sq, i) => (
              <button
                key={i}
                onClick={() => handleAsk(sq)}
                className="text-xs font-mono px-3 py-1.5 rounded-lg bg-[#10131A] border border-[#232936] text-[#9AA4B2] hover:text-[#F4F7FB] hover:border-[#7C8CFF]/50 transition-all text-left flex items-center gap-1.5"
              >
                <span>{sq}</span>
                <ArrowRight className="w-3 h-3 text-[#7C8CFF]" />
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Message Feed */}
      <div className="space-y-4">
        {messages.map((m, i) => (
          <div key={i} className="cm-card p-5 border-[#232936] bg-[#10131A] space-y-3">
            <div className="flex items-center gap-2 text-xs font-mono text-[#7C8CFF]">
              <Cpu className="w-4 h-4" />
              <span className="font-semibold">QUESTION:</span>
              <span className="text-[#F4F7FB] font-sans font-medium">{m.question}</span>
            </div>

            {m.error ? (
              <p className="text-xs text-[#FF5D73] font-mono">{m.error}</p>
            ) : (
              <div className="space-y-3 text-xs leading-relaxed text-[#F4F7FB]">
                <p className="whitespace-pre-wrap font-sans">{m.answer}</p>

                {m.citedFiles.length > 0 && (
                  <div className="pt-2 border-t border-[#232936] space-y-1.5">
                    <span className="text-[10px] font-mono text-[#687386] uppercase tracking-wider block">
                      RELEVANT CITED FILES
                    </span>
                    <div className="flex flex-wrap gap-2">
                      {m.citedFiles.map((file) => (
                        <div
                          key={file}
                          className="px-2.5 py-1 rounded bg-[#090B10] border border-[#232936] font-mono text-[11px] text-[#7C8CFF] flex items-center gap-1.5"
                        >
                          <FileCode className="w-3 h-3" />
                          <span>{file}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Input Form */}
      {projectId && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleAsk();
          }}
          className="flex gap-2"
        >
          <input
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            disabled={loading}
            placeholder="Ask where a variable flow, query, or function is defined..."
            className="flex-1 rounded-lg border border-[#232936] bg-[#090B10] px-4 py-3 text-sm text-[#F4F7FB] font-mono placeholder:text-[#687386] focus:border-[#7C8CFF] focus:outline-none disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={!question.trim() || loading}
            className="cm-btn-primary px-5 py-3 text-xs shrink-0 disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <>
                <span>Ask</span>
                <Send className="w-3.5 h-3.5" />
              </>
            )}
          </button>
        </form>
      )}
    </div>
  );
}
