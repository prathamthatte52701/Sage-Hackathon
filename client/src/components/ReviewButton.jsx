import { motion } from "framer-motion";

// Submit button. Disabled while loading, when code is empty, or over the char limit.
export default function ReviewButton({ onClick, loading, disabled }) {
  const isDisabled = loading || disabled;

  return (
    <motion.button
      type="button"
      onClick={onClick}
      disabled={isDisabled}
      whileHover={!isDisabled ? { scale: 1.02 } : {}}
      whileTap={!isDisabled ? { scale: 0.98 } : {}}
      className={`flex items-center justify-center gap-2 rounded-lg px-6 py-2.5 text-sm font-medium transition-colors ${
        isDisabled
          ? "cursor-not-allowed bg-zinc-800 text-zinc-500"
          : "bg-indigo-600 text-white shadow-lg shadow-indigo-600/25 hover:bg-indigo-500"
      }`}
    >
      {loading && (
        <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
      )}
      {loading ? "Reviewing..." : "Review Code"}
    </motion.button>
  );
}
