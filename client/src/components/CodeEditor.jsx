import Editor from "@monaco-editor/react";

export const MAX_CHARS = 3000;

export const LANGUAGES = [
  { value: "javascript", label: "JavaScript" },
  { value: "typescript", label: "TypeScript" },
  { value: "python", label: "Python" },
  { value: "java", label: "Java" },
  { value: "cpp", label: "C++" },
];

// Monaco editor wrapper with a language dropdown above it and a live
// char counter below. Controlled component - parent owns code/language state.
export default function CodeEditor({ code, onCodeChange, language, onLanguageChange }) {
  const count = code.length;
  const overLimit = count > MAX_CHARS;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <label htmlFor="language-select" className="text-sm font-medium text-zinc-400">
          Language
        </label>
        <select
          id="language-select"
          value={language}
          onChange={(e) => onLanguageChange(e.target.value)}
          className="rounded-md border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-200 outline-none transition focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
        >
          {LANGUAGES.map((l) => (
            <option key={l.value} value={l.value}>
              {l.label}
            </option>
          ))}
        </select>
      </div>

      <div className="overflow-hidden rounded-lg border border-zinc-800 shadow-lg shadow-black/20">
        <Editor
          height="360px"
          language={language}
          value={code}
          onChange={(value) => onCodeChange(value ?? "")}
          theme="vs-dark"
          options={{
            fontSize: 14,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            padding: { top: 12 },
            automaticLayout: true,
          }}
        />
      </div>

      <div className="flex justify-end">
        <span className={`font-mono text-xs ${overLimit ? "text-red-400" : "text-zinc-500"}`}>
          {count.toLocaleString()} / {MAX_CHARS.toLocaleString()}
        </span>
      </div>
    </div>
  );
}
