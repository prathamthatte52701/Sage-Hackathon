import { AnimatePresence, motion } from "framer-motion";

// Dismissible inline banner for API errors. `message` must always be a plain
// string - callers are responsible for turning raw error objects into text
// before they ever reach this component.
export default function ErrorBanner({ message, onDismiss }) {
  return (
    <AnimatePresence>
      {message && (
        <motion.div
          initial={{ opacity: 0, y: -8, height: 0 }}
          animate={{ opacity: 1, y: 0, height: "auto" }}
          exit={{ opacity: 0, y: -8, height: 0 }}
          transition={{ duration: 0.2 }}
          className="overflow-hidden"
        >
          <div className="mb-4 flex items-start justify-between gap-3 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
            <span className="flex-1">{String(message || "Something went wrong.")}</span>
            {onDismiss && (
              <button
                type="button"
                onClick={onDismiss}
                aria-label="Dismiss error"
                className="shrink-0 rounded text-red-300/70 transition hover:text-red-200"
              >
                ✕
              </button>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
