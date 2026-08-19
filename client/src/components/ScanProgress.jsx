import { motion } from "framer-motion";

// Three real stages, tied to actual network calls - no fake timers, no
// invented sub-steps. `stage` is one of: "reading" | "analyzing" | "scoring" | "done".
const STAGES = [
  { key: "reading", label: "Reading project" },
  { key: "analyzing", label: "Analyzing project" },
  { key: "scoring", label: "Scoring project" },
];

function stageStatus(stageKey, currentStage) {
  const order = ["reading", "analyzing", "scoring", "done"];
  const currentIdx = order.indexOf(currentStage);
  const stageIdx = order.indexOf(stageKey);
  if (stageIdx < currentIdx) return "done";
  if (stageIdx === currentIdx) return "active";
  return "pending";
}

// `errorStage` marks the stage that just failed, so it renders as an error
// mark instead of spinning forever on a request that already rejected.
export default function ScanProgress({ stage, errorStage }) {
  return (
    <div className="flex flex-col gap-4 rounded-xl border border-zinc-800 bg-zinc-900/60 p-6">
      {STAGES.map((s) => {
        const status = s.key === errorStage ? "error" : stageStatus(s.key, stage);
        return (
          <div key={s.key} className="flex items-center gap-3">
            <span className="relative flex h-5 w-5 shrink-0 items-center justify-center">
              {status === "done" && (
                <motion.span
                  initial={{ scale: 0.5, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  className="flex h-5 w-5 items-center justify-center rounded-full bg-indigo-500 text-[10px] font-bold text-white"
                >
                  ✓
                </motion.span>
              )}
              {status === "active" && (
                <motion.span
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="h-4 w-4 animate-spin rounded-full border-2 border-zinc-700 border-t-indigo-400"
                />
              )}
              {status === "error" && (
                <motion.span
                  initial={{ scale: 0.5, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  className="flex h-5 w-5 items-center justify-center rounded-full bg-red-500/80 text-[10px] font-bold text-white"
                >
                  ✕
                </motion.span>
              )}
              {status === "pending" && (
                <span className="h-2.5 w-2.5 rounded-full border-2 border-zinc-700" />
              )}
            </span>
            <span
              className={`text-sm transition-colors ${
                status === "pending"
                  ? "text-zinc-600"
                  : status === "active"
                    ? "text-zinc-200"
                    : "text-zinc-400"
              }`}
            >
              {s.label}
              {status === "active" ? "..." : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}
