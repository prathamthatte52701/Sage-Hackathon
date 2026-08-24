"""Authoritative security finding accessors.

`security_findings` is the V1 source of truth for user-facing security
behavior. Legacy `findings` is read only for old project documents that do not
yet have the authoritative field.
"""


def authoritative_security_findings(project: dict | None) -> list[dict]:
    if not isinstance(project, dict):
        return []
    if isinstance(project.get("security_findings"), list):
        return project["security_findings"]
    if isinstance(project.get("findings"), list):
        return project["findings"]
    return []
