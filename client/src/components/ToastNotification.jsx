import React, { useEffect } from "react";
import { AlertCircle, CheckCircle2, Info, X } from "lucide-react";

export default function ToastNotification({ toast, onClose }) {
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => {
      onClose?.();
    }, 5000);
    return () => clearTimeout(timer);
  }, [toast, onClose]);

  if (!toast) return null;

  const { type = "info", message, title } = toast;

  const styles = {
    error: {
      bg: "bg-[#FF5D73]/10 border-[#FF5D73]/30 text-[#FF5D73]",
      icon: AlertCircle,
    },
    success: {
      bg: "bg-[#36D399]/10 border-[#36D399]/30 text-[#36D399]",
      icon: CheckCircle2,
    },
    info: {
      bg: "bg-[#7C8CFF]/10 border-[#7C8CFF]/30 text-[#7C8CFF]",
      icon: Info,
    },
  }[type] || {
    bg: "bg-[#7C8CFF]/10 border-[#7C8CFF]/30 text-[#7C8CFF]",
    icon: Info,
  };

  const Icon = styles.icon;

  return (
    <div className="fixed bottom-6 right-6 z-50 max-w-md w-full animate-in fade-in slide-in-from-bottom-5 duration-200">
      <div className={`p-4 rounded-xl border ${styles.bg} shadow-2xl backdrop-blur-md flex items-start gap-3`}>
        <Icon className="w-5 h-5 shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0 space-y-0.5 text-xs">
          {title && <div className="font-bold font-mono tracking-tight">{title}</div>}
          <div className="font-mono text-[11px] leading-relaxed text-[#F4F7FB] break-words">
            {message}
          </div>
        </div>
        <button
          onClick={onClose}
          className="text-[#687386] hover:text-[#F4F7FB] transition-colors p-1"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
