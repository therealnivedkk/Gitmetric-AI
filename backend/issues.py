
from __future__ import annotations

import ast
import os
import re
import sys
from typing import Any

# Security Check Rules (Context-Aware AST + Regex)

SECRET_REGEX = re.compile(
    r'(?i)\b(api[_-]?key|access[_-]?token|secret[_-]?key|private[_-]?key|auth[_-]?token|password)\b\s*=\s*[\'"][A-Za-z0-9_\-\.\/+=]{16,}[\'"]'
)

SAFE_SECRET_PATTERNS = re.compile(
    r'(?i)(dummy|test|example|fake|placeholder|none|null|env|os\.getenv|os\.environ|your[_-]|changeme|sample|default)'
)


def _is_test_file(filepath: str) -> bool:
    """Checks if the file is in a test suite or fixture directory."""
    normalized = filepath.replace("\\", "/").lower()
    return bool(
        re.search(r'(^|/)(tests?|testing|unit_tests|fixtures?|conftest\.py)(/|$)', normalized)
        or normalized.endswith("_test.py")
        or normalized.endswith("test_.py")
    )


def _is_literal_or_constant(node: ast.AST) -> bool:
    """Returns True if the AST node represents an invariant static literal or constant."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_literal_or_constant(elt) for elt in node.elts)
    if isinstance(node, ast.Dict):
        return all(_is_literal_or_constant(k) and _is_literal_or_constant(v)
                   for k, v in zip(node.keys, node.values) if k is not None)
    return False


class SecurityVisitor(ast.NodeVisitor):
    """
    Context-aware AST visitor to detect genuine security anti-patterns.
    Analyzes call context, argument types, and surrounding scope to minimize false positives.
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.is_test = _is_test_file(filepath)
        self.issues: list[dict[str, Any]] = []

    def visit_Call(self, node: ast.Call):
        func_name = ""
        module_name = ""

        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
            if isinstance(node.func.value, ast.Name):
                module_name = node.func.value.id

        # 1. Dynamic Code Execution: eval() or exec()
        if func_name in ("eval", "exec") and not module_name:
            if node.args:
                arg0 = node.args[0]
                if not _is_literal_or_constant(arg0):
                    severity = "MEDIUM" if self.is_test else "HIGH"
                    self.issues.append({
                        "filepath": self.filepath,
                        "lineno": node.lineno,
                        "rule_id": "SEC-001",
                        "severity": severity,
                        "title": f"Dynamic code execution via `{func_name}()` with non-constant input",
                        "description": (
                            f"Dynamic `{func_name}()` called with dynamic variable or expression. "
                            "Untrusted inputs reaching this can lead to remote code execution. "
                            "Consider `ast.literal_eval()` or structured dispatch."
                        ),
                    })

        # 2. Subprocess Execution with shell=True
        if func_name in ("Popen", "call", "check_call", "check_output", "run"):
            if module_name in ("subprocess", ""):
                shell_kw = next((kw for kw in node.keywords if kw.arg == "shell"), None)
                if shell_kw and isinstance(shell_kw.value, ast.Constant) and shell_kw.value.value is True:
                    cmd_arg = node.args[0] if node.args else None
                    if not cmd_arg:
                        for kw in node.keywords:
                            if kw.arg in ("args", "command", "cmd"):
                                cmd_arg = kw.value
                                break

                    if cmd_arg and isinstance(cmd_arg, ast.Constant) and isinstance(cmd_arg.value, str):
                        if any(op in cmd_arg.value for op in (";", "&&", "||", "|", "`", "$(")):
                            self.issues.append({
                                "filepath": self.filepath,
                                "lineno": node.lineno,
                                "rule_id": "SEC-002",
                                "severity": "LOW",
                                "title": "Subprocess with `shell=True` using chained commands",
                                "description": "Hardcoded shell command contains pipeline or chaining operators.",
                            })
                    else:
                        severity = "MEDIUM" if self.is_test else "HIGH"
                        self.issues.append({
                            "filepath": self.filepath,
                            "lineno": node.lineno,
                            "rule_id": "SEC-002",
                            "severity": severity,
                            "title": "Unsafe command construction with `shell=True`",
                            "description": (
                                "Subprocess spawned with `shell=True` using a dynamic argument. "
                                "Vulnerable to command injection if argument contains unsanitized input. "
                                "Pass arguments as an argument list with `shell=False`."
                            ),
                        })

        # 3. Insecure Deserialization: pickle.loads / pickle.load
        if func_name in ("loads", "load") and module_name == "pickle":
            if not self.is_test:
                self.issues.append({
                    "filepath": self.filepath,
                    "lineno": node.lineno,
                    "rule_id": "SEC-003",
                    "severity": "MEDIUM",
                    "title": "Insecure deserialization via `pickle`",
                    "description": (
                        "Pickle deserialization of untrusted payloads can lead to arbitrary code execution. "
                        "Prefer JSON, msgpack, or cryptographic HMAC signatures for serialized objects."
                    ),
                })

        # 4. Insecure Temporary File Creation: tempfile.mktemp
        if func_name == "mktemp" and module_name in ("tempfile", ""):
            self.issues.append({
                "filepath": self.filepath,
                "lineno": node.lineno,
                "rule_id": "SEC-004",
                "severity": "MEDIUM",
                "title": "Deprecated insecure temporary file creation (`tempfile.mktemp`)",
                "description": "Use of `tempfile.mktemp()` is susceptible to race condition symlink attacks. Use `tempfile.NamedTemporaryFile()`.",
            })

        self.generic_visit(node)


def scan_file_security(full_path: str, rel_path: str) -> list[dict[str, Any]]:

    issues: list[dict[str, Any]] = []

    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return issues

    is_test = _is_test_file(rel_path)

    # 1. Regex scan for hardcoded credentials (skip tests and safe fixtures)
    if not is_test:
        for line_idx, line in enumerate(content.splitlines(), start=1):
            if SECRET_REGEX.search(line):
                if not SAFE_SECRET_PATTERNS.search(line):
                    issues.append({
                        "filepath": rel_path,
                        "lineno": line_idx,
                        "rule_id": "SEC-005",
                        "severity": "HIGH",
                        "title": "Potential hardcoded credential or secret key",
                        "description": "Detected hardcoded high-entropy secret assignment. Use environment variables or a secrets manager.",
                    })

    # 2. AST Context-Aware Scan
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