import React from "react";
import { Minus, Plus } from "lucide-react";

export default function DiffViewer({ beforeCode, afterCode }) {
  const beforeLines = (beforeCode || "").split("\n");
  const afterLines = (afterCode || "").split("\n");

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 font-mono text-xs">
      {/* Before Panel */}
      <div className="cm-card border-[#232936] bg-[#090B10] overflow-hidden">
        <div className="px-3 py-1.5 bg-[#FF5D73]/10 border-b border-[#232936] text-[#FF5D73] font-semibold flex items-center justify-between text-[11px]">
          <span>BEFORE (VULNERABLE)</span>
          <Minus className="w-3.5 h-3.5" />
        </div>
        <div className="p-3 overflow-x-auto text-[#FF5D73] bg-[#FF5D73]/5 space-y-1">
          {beforeLines.map((line, i) => (
            <div key={i} className="flex gap-2">
              <span className="text-[#687386] select-none w-6 text-right shrink-0">{i + 1}</span>
              <span className="whitespace-pre-wrap">{line}</span>
            </div>
          ))}
        </div>
      </div>

      {/* After Panel */}
      <div className="cm-card border-[#232936] bg-[#090B10] overflow-hidden">
        <div className="px-3 py-1.5 bg-[#36D399]/10 border-b border-[#232936] text-[#36D399] font-semibold flex items-center justify-between text-[11px]">
          <span>AFTER (VALIDATED FIX)</span>
          <Plus className="w-3.5 h-3.5" />
        </div>
        <div className="p-3 overflow-x-auto text-[#36D399] bg-[#36D399]/5 space-y-1">
          {afterLines.map((line, i) => (
            <div key={i} className="flex gap-2">
              <span className="text-[#687386] select-none w-6 text-right shrink-0">{i + 1}</span>
              <span className="whitespace-pre-wrap">{line}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
