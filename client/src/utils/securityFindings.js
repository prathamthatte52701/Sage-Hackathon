export function getSecurityFindings(project) {
  if (!project) return [];
  if (Array.isArray(project.security_findings)) return project.security_findings;
  if (Array.isArray(project.findings)) return project.findings;
  return [];
}
