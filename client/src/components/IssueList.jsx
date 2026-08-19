import { motion } from "framer-motion";
import IssueCard from "./IssueCard";

const SEVERITY_ORDER = { critical: 0, medium: 1, low: 2 };

function severityRank(severity) {
  return SEVERITY_ORDER[severity] ?? 3;
}

const container = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08 } },
};

// Renders issues sorted critical-first, then medium, then low.
export default function IssueList({ issues, code, language }) {
  if (!issues || issues.length === 0) {
    return (
      <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-8 text-center text-sm text-zinc-500">
        No issues found. Nice work.
      </div>
    );
  }

  const sorted = [...issues].sort((a, b) => severityRank(a?.severity) - severityRank(b?.severity));

  return (
    <motion.div variants={container} initial="hidden" animate="show" className="flex flex-col gap-4">
      {sorted.map((issue, i) => (
        <IssueCard key={`${issue?.line ?? "x"}-${issue?.issue ?? i}-${i}`} issue={issue} code={code} language={language} />
      ))}
    </motion.div>
  );
}
