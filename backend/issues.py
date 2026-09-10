
from __future__ import annotations

import ast
import os
import re
import sys
from typing import Any

# Security Check Rules (AST + Regex)

SECRET_REGEX = re.compile(
    r'(?i)(password|secret|api_key|access_token|private_key)\s*=\s*[\'"][^\'"]{8,}[\'"]'
)

class SecurityVisitor(ast.NodeVisitor):
    """AST visitor to find common security anti-patterns in Python files."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.issues: list[dict[str, Any]] = []

    def visit_Call(self, node: ast.Call):
        func_name = ""
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        # 1. eval() or exec()
        if func_name in ("eval", "exec"):
            self.issues.append({
                "filepath": self.filepath,
                "lineno": node.lineno,
                "rule_id": "SEC-001",
                "severity": "HIGH",
                "title": f"Dangerous dynamic execution via `{func_name}()`",
                "description": f"Use of `{func_name}()` can allow arbitrary code execution if user-controlled input reaches it.",
            })

        # 2. subprocess with shell=True
        if func_name in ("Popen", "call", "check_call", "check_output", "run"):
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    self.issues.append({
                        "filepath": self.filepath,
                        "lineno": node.lineno,
                        "rule_id": "SEC-002",
                        "severity": "HIGH",
                        "title": "Subprocess execution with `shell=True`",
                        "description": "Spawning subprocesses with `shell=True` exposes the application to command injection vulnerabilities.",
                    })

        # 3. pickle.loads or pickle.load
        if func_name in ("loads", "load"):
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                if node.func.value.id == "pickle":
                    self.issues.append({
                        "filepath": self.filepath,
                        "lineno": node.lineno,
                        "rule_id": "SEC-003",
                        "severity": "MEDIUM",
                        "title": "Insecure deserialization via `pickle`",
                        "description": "Pickle deserialization of untrusted data can lead to remote code execution. Prefer JSON or safe serialization.",
                    })

        # 4. tempfile.mktemp
        if func_name == "mktemp":
            self.issues.append({
                "filepath": self.filepath,
                "lineno": node.lineno,
                "rule_id": "SEC-004",
                "severity": "MEDIUM",
                "title": "Insecure temporary file creation (`tempfile.mktemp`)",
                "description": "Use of `tempfile.mktemp()` is deprecated and vulnerable to symlink race conditions. Use `NamedTemporaryFile` instead.",
            })

        self.generic_visit(node)


def scan_file_security(full_path: str, rel_path: str) -> list[dict[str, Any]]:
    """Runs regex and AST security inspections on a single python file."""
    issues: list[dict[str, Any]] = []

    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return issues

    # Regex scan for hardcoded secrets
    for line_idx, line in enumerate(content.splitlines(), start=1):
        if SECRET_REGEX.search(line):
            # Avoid flagging test fixture dummy strings
            if not any(dummy in line.lower() for dummy in ("dummy", "example", "test", "fake", "placeholder")):
                issues.append({
                    "filepath": rel_path,
                    "lineno": line_idx,
                    "rule_id": "SEC-005",
                    "severity": "MEDIUM",
                    "title": "Potential hardcoded credential or secret",
                    "description": "Detected hardcoded assignment that looks like a password or API token.",
                })

    # AST scan
    try:
        tree = ast.parse(content)
        visitor = SecurityVisitor(rel_path)
        visitor.visit(tree)
        issues.extend(visitor.issues)
    except SyntaxError:
        pass

    return issues


# Main Issue Detection Orchestrator

def detect_issues(extracted_data: dict[str, Any], repo_path: str | None = None) -> dict[str, Any]:
    """
    Consumes the output of extractors.analyze_repository() and computes:
      - complexity_issues: per-function McCabe CC flags (>10, >20, >50)
      - maintainability_issues: files with MI < 65
      - undocumented_issues: functions/classes missing docstrings
      - hotspots: top churn + complexity files
      - security_issues: AST/regex security flags
      - summary: aggregated issue counts by severity
    """
    files = extracted_data.get("files", [])
    base_repo_path = repo_path or extracted_data.get("repo_path", "")

    complexity_issues: list[dict[str, Any]] = []
    maintainability_issues: list[dict[str, Any]] = []
    undocumented_issues: list[dict[str, Any]] = []
    hotspot_candidates: list[dict[str, Any]] = []
    security_issues: list[dict[str, Any]] = []

    # 1. Process per-file metrics
    for f in files:
        filepath = f.get("filepath", "")
        churn = f.get("churn", 0)
        mi = f.get("mi")
        loc = f.get("loc", 0)
        functions = f.get("functions", [])
        undocumented = f.get("undocumented", [])

        # Check Maintainability Index (MI)
        if mi is not None:
            if mi < 40.0:
                maintainability_issues.append({
                    "filepath": filepath,
                    "mi": round(mi, 2),
                    "loc": loc,
                    "severity": "CRITICAL",
                    "title": f"Critically low maintainability index ({round(mi, 1)})",
                    "description": "File has very high structural complexity and will be difficult to modify safely.",
                })
            elif mi < 65.0:
                maintainability_issues.append({
                    "filepath": filepath,
                    "mi": round(mi, 2),
                    "loc": loc,
                    "severity": "WARNING",
                    "title": f"Low maintainability index ({round(mi, 1)})",
                    "description": "File is approaching high maintenance debt; consider decomposing large routines.",
                })

        # Check Per-function Cyclomatic Complexity
        file_complexities = []
        for fn in functions:
            cc = fn.get("complexity", 1)
            fn_name = fn.get("name", "unknown")
            lineno = fn.get("lineno", 0)
            file_complexities.append(cc)

            if cc > 50:
                complexity_issues.append({
                    "filepath": filepath,
                    "function_name": fn_name,
                    "lineno": lineno,
                    "complexity": cc,
                    "severity": "CRITICAL",
                    "title": f"Extremely complex function `{fn_name}` (CC: {cc})",
                    "description": "Exceeds McCabe very high risk limit (50+). Hard to test exhaustively and prone to defects.",
                })
            elif cc > 20:
                complexity_issues.append({
                    "filepath": filepath,
                    "function_name": fn_name,
                    "lineno": lineno,
                    "complexity": cc,
                    "severity": "HIGH",
                    "title": f"High complexity function `{fn_name}` (CC: {cc})",
                    "description": "Exceeds McCabe high risk threshold (20+). Refactoring into smaller helper routines recommended.",
                })
            elif cc > 10:
                complexity_issues.append({
                    "filepath": filepath,
                    "function_name": fn_name,
                    "lineno": lineno,
                    "complexity": cc,
                    "severity": "WARNING",
                    "title": f"Moderate complexity function `{fn_name}` (CC: {cc})",
                    "description": "Exceeds McCabe base threshold of 10.",
                })

        # Calculate Churn + Complexity Hotspot Candidate
        avg_file_cc = (sum(file_complexities) / len(file_complexities)) if file_complexities else 1.0
        max_file_cc = max(file_complexities) if file_complexities else 1
        
        # Hotspot score formula: combines churn volume with complexity intensity
        if churn > 0:
            raw_hotspot_score = round(churn * avg_file_cc, 1)
            hotspot_candidates.append({
                "filepath": filepath,
                "churn": churn,
                "avg_cc": round(avg_file_cc, 2),
                "max_cc": max_file_cc,
                "loc": loc,
                "hotspot_score": raw_hotspot_score,
            })

        # Undocumented items
        for item in undocumented:
            undocumented_issues.append({
                "filepath": filepath,
                "name": item.get("name"),
                "type": item.get("type"),
                "lineno": item.get("lineno"),
            })

        # Security check
        if base_repo_path and os.path.isdir(base_repo_path):
            full_path = os.path.join(base_repo_path, filepath)
            if os.path.isfile(full_path):
                file_sec = scan_file_security(full_path, filepath)
                security_issues.extend(file_sec)

    # Sort hotspots descending by score and pick top 10
    hotspot_candidates.sort(key=lambda x: x["hotspot_score"], reverse=True)
    top_hotspots = hotspot_candidates[:10]

    # Assign risk rank to hotspots
    for idx, h in enumerate(top_hotspots, start=1):
        h["rank"] = idx

    # Compute high-level issue counts
    counts = {
        "critical": sum(1 for i in complexity_issues if i["severity"] == "CRITICAL")
        + sum(1 for i in maintainability_issues if i["severity"] == "CRITICAL")
        + sum(1 for i in security_issues if i["severity"] == "HIGH"),
        "high": sum(1 for i in complexity_issues if i["severity"] == "HIGH")
        + sum(1 for i in security_issues if i["severity"] == "MEDIUM"),
        "warning": sum(1 for i in complexity_issues if i["severity"] == "WARNING")
        + sum(1 for i in maintainability_issues if i["severity"] == "WARNING"),
        "total_undocumented": len(undocumented_issues),
        "total_hotspots": len(top_hotspots),
    }

    return {
        "summary": counts,
        "complexity_issues": complexity_issues,
        "maintainability_issues": maintainability_issues,
        "hotspots": top_hotspots,
        "security_issues": security_issues,
        "top_undocumented": undocumented_issues[:15],  # Cap preview to top 15
        "total_undocumented_count": len(undocumented_issues),
    }


if __name__ == "__main__":
    import json
    try:
        from extractors import analyze_repository
    except ImportError:
        from backend.extractors import analyze_repository

    target = sys.argv[1] if len(sys.argv) > 1 else "../repositories/tqdm"
    print(f"Running Issue Detection on: {target}...")

    extracted = analyze_repository(target)
    issues = detect_issues(extracted, target)

    print("\n--- ISSUE DETECTION SUMMARY ---")
    print(json.dumps(issues["summary"], indent=2))

    print("\n--- TOP 3 HOTSPOTS (High Churn + High Complexity) ---")
    print(json.dumps(issues["hotspots"][:3], indent=2))

    if issues["security_issues"]:
        print(f"\n--- SECURITY ISSUES ({len(issues['security_issues'])}) ---")
        print(json.dumps(issues["security_issues"][:3], indent=2))
    else:
        print("\n--- SECURITY ISSUES: None detected! ---")