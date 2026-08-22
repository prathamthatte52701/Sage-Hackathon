import React, { useRef, useEffect } from "react";
import Editor from "@monaco-editor/react";
import { FileCode, Hash, Eye } from "lucide-react";

export default function CodeViewer({
  fileContent,
  filePath,
  highlightLine,
  language = "javascript",
  height = "600px",
}) {
  const editorRef = useRef(null);
  const decorationsRef = useRef([]);

  function detectLanguage(path) {
    if (!path) return "javascript";
    const ext = path.split(".").pop().toLowerCase();
    switch (ext) {
      case "py":
        return "python";
      case "js":
      case "jsx":
        return "javascript";
      case "ts":
      case "tsx":
        return "typescript";
      case "java":
        return "java";
      case "cpp":
      case "c":
      case "h":
      case "hpp":
        return "cpp";
      case "json":
        return "json";
      case "html":
        return "html";
      case "css":
        return "css";
      default:
        return "javascript";
    }
  }

  function handleEditorDidMount(editor, monaco) {
    editorRef.current = editor;
    if (highlightLine && highlightLine > 0) {
      scrollToAndHighlightLine(editor, monaco, highlightLine);
    }
  }

  useEffect(() => {
    if (editorRef.current && highlightLine && highlightLine > 0) {
      // Access monaco instance from global or window if available
      const editor = editorRef.current;
      editor.revealLineInCenter(highlightLine);
    }
  }, [highlightLine, fileContent]);

  function scrollToAndHighlightLine(editor, monaco, lineNum) {
    editor.revealLineInCenter(lineNum);
    decorationsRef.current = editor.deltaDecorations(decorationsRef.current, [
      {
        range: new monaco.Range(lineNum, 1, lineNum, 1),
        options: {
          isWholeLine: true,
          className: "cm-code-highlight-line",
          glyphMarginClassName: "myGlyphMarginClass",
        },
      },
    ]);
  }

  const lang = detectLanguage(filePath || "");

  return (
    <div className="cm-card border-[#232936] bg-[#10131A] overflow-hidden flex flex-col h-full">
      {/* File Bar Header */}
      <div className="h-10 px-4 bg-[#090B10] border-b border-[#232936] flex items-center justify-between font-mono text-xs text-[#9AA4B2]">
        <div className="flex items-center gap-2 truncate">
          <FileCode className="w-4 h-4 text-[#7C8CFF] shrink-0" />
          <span className="text-[#F4F7FB] font-semibold truncate">{filePath || "No file selected"}</span>
        </div>
        {highlightLine && (
          <span className="text-[11px] font-semibold text-[#FF5D73] bg-[#FF5D73]/10 px-2 py-0.5 rounded border border-[#FF5D73]/20 flex items-center gap-1">
            <Hash className="w-3 h-3" /> Line {highlightLine}
          </span>
        )}
      </div>

      {/* Editor Surface */}
      <div className="flex-1 bg-[#090B10] relative">
        {fileContent ? (
          <Editor
            height={height}
            language={lang}
            value={fileContent}
            onMount={handleEditorDidMount}
            theme="vs-dark"
            options={{
              readOnly: true,
              fontSize: 13,
              fontFamily: "'JetBrains Mono', monospace",
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              automaticLayout: true,
              lineNumbers: "on",
              padding: { top: 12 },
              renderLineHighlight: "all",
            }}
          />
        ) : (
          <div className="h-[400px] flex flex-col items-center justify-center text-xs text-[#687386] space-y-2">
            <Eye className="w-6 h-6 text-[#232936]" />
            <span>Select a finding or file to view source code</span>
          </div>
        )}
      </div>
    </div>
  );
}
