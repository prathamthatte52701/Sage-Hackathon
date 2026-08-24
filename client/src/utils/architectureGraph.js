import { getSecurityFindings } from "./securityFindings";

const PYTHON_SOURCE_RE = /\.(py|pyi)$/i;
const DOC_OR_FIXTURE_RE = /(^|\/)(readme[^/]*|expected_result[^/]*|coverage|docs?|generated|cache|__pycache__)(\/|$)/i;
const EXCLUDED_SUFFIX_RE = /\.(md|json|png|jpe?g|gif|svg|lock|log|pyc)$/i;

const ROUTE_RE = /\b(?:app|router|api|bp|blueprint)\s*\.\s*(get|post|put|patch|delete)\s*[(]\s*["']([^"']+)/gi;
const IMPORT_RE = /^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*))/gm;
const DEF_RE = /^\s*(?:async\s+def|def)\s+([A-Za-z_]\w*)\s*[(]/gm;
const CLASS_RE = /^\s*class\s+([A-Za-z_]\w*)\s*[(.:]/gm;
const SERVICE_NAME_RE = /(^|\/)(services?|managers?|controllers?|processors?|workers?|tasks?|domain|core)(\/|_)|(_service|_manager|_controller|_worker)\.py$/i;
const ENTRY_NAME_RE = /(^|\/)(app|main|server|asgi|wsgi|cli)\.py$/i;
const DATA_NAME_RE = /(^|\/)(db|database|models?|repositories?|storage|dao)(\/|_)|(_repo|_repository|_dao|_store)\.py$/i;
const DATA_CODE_RE = /\b(sqlite3|sqlalchemy|pymongo|psycopg|execute\s*[(]|cursor\s*[(]|requests\.|httpx\.|urllib\.|open\s*[(]|Path\s*[(]|read_text\s*[(]|write_text\s*[(]|send_file|boto3|redis|queue)\b/i;

const SEVERITY_RANK = { critical: 4, high: 3, medium: 2, low: 1 };

function normalizePath(path = "") {
  return String(path).replace(/\\/g, "/");
}

function basename(path = "") {
  return normalizePath(path).split("/").pop() || "";
}

export function isArchitectureSourceFile(file) {
  const path = normalizePath(file?.path || file?.filename || file?.name || "");
  if (!path || DOC_OR_FIXTURE_RE.test(path)) return false;
  if (!PYTHON_SOURCE_RE.test(path)) return false;
  if (EXCLUDED_SUFFIX_RE.test(path) && !PYTHON_SOURCE_RE.test(path)) return false;
  return true;
}

function collectRegex(re, content, group = 1) {
  const out = [];
  re.lastIndex = 0;
  let match;
  while ((match = re.exec(content))) {
    out.push(match[group]);
  }
  return out;
}

function moduleNameForPath(path) {
  const normalized = normalizePath(path).replace(/\.(py|pyi)$/i, "");
  const parts = normalized.split("/").filter(Boolean);
  return parts.join(".");
}

function importTargets(file, moduleToPath) {
  const content = file.content || "";
  const targets = new Set();
  IMPORT_RE.lastIndex = 0;
  let match;
  while ((match = IMPORT_RE.exec(content))) {
    const imported = (match[1] || match[2] || "").split(".").filter(Boolean);
    for (let length = imported.length; length > 0; length -= 1) {
      const candidate = imported.slice(0, length).join(".");
      if (moduleToPath.has(candidate)) {
        targets.add(moduleToPath.get(candidate));
        break;
      }
    }
  }
  return [...targets].filter((target) => target !== file.path);
}

function highestSeverity(findings) {
  return findings.reduce((best, finding) => {
    const severity = finding.severity || "low";
    return (SEVERITY_RANK[severity] || 0) > (SEVERITY_RANK[best] || 0) ? severity : best;
  }, "");
}

function findingsForPath(findings, path) {
  return findings.filter((finding) => (finding.file || finding.path) === path);
}

function classifyFile(file) {
  const path = normalizePath(file.path || file.filename || file.name || "");
  const content = file.content || "";
  const routes = collectRegex(ROUTE_RE, content, 2);
  const functions = collectRegex(DEF_RE, content);
  const classes = collectRegex(CLASS_RE, content);
  const lowerPath = path.toLowerCase();

  if (routes.length || ENTRY_NAME_RE.test(lowerPath)) return "entry";
  if (DATA_NAME_RE.test(lowerPath) || DATA_CODE_RE.test(content)) return "data";
  if (SERVICE_NAME_RE.test(lowerPath) || functions.length || classes.length) return "service";
  return "module";
}

export function buildArchitectureGraph(project) {
  const files = (project?.files || [])
    .filter(isArchitectureSourceFile)
    .map((file) => ({ ...file, path: normalizePath(file.path || file.filename || file.name || "") }));
  const findings = getSecurityFindings(project);
  const moduleToPath = new Map(files.map((file) => [moduleNameForPath(file.path), file.path]));

  const nodes = files.map((file) => {
    const nodeFindings = findingsForPath(findings, file.path);
    const content = file.content || "";
    return {
      id: file.path,
      file,
      path: file.path,
      label: basename(file.path),
      kind: classifyFile(file),
      findings: nodeFindings,
      findingCount: nodeFindings.length,
      highestSeverity: highestSeverity(nodeFindings),
      routes: collectRegex(ROUTE_RE, content, 2),
      functions: collectRegex(DEF_RE, content),
      classes: collectRegex(CLASS_RE, content),
    };
  });

  const nodeByPath = new Map(nodes.map((node) => [node.path, node]));
  const edges = [];
  for (const file of files) {
    for (const target of importTargets(file, moduleToPath)) {
      if (nodeByPath.has(target)) {
        edges.push({ from: file.path, to: target, label: "imports" });
      }
    }
  }

  return {
    nodes,
    edges,
    layers: [
      { key: "entry", title: "ENTRY POINTS & HANDLERS", nodes: nodes.filter((node) => node.kind === "entry") },
      { key: "service", title: "BUSINESS LOGIC & SERVICES", nodes: nodes.filter((node) => node.kind === "service") },
      { key: "data", title: "DATA ACCESS & SINKS", nodes: nodes.filter((node) => node.kind === "data") },
      { key: "module", title: "PYTHON MODULES", nodes: nodes.filter((node) => node.kind === "module") },
    ],
  };
}
