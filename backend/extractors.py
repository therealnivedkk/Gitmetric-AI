from __future__ import annotations

import ast
import os
import statistics
from typing import Iterable

from git import InvalidGitRepositoryError, Repo
from radon.complexity import cc_visit
from radon.metrics import h_visit,mi_visit
from radon.raw import analyze as raw_analyze

MAX_COMMITS = 3000

SKIP_DIRS = {
    ".git","venv",".venv","env",".env","node_modules","migrations","build",
    "dist","__pycache__",".tox",".pytest_cache",".eggs",
}

# File discovery
 
def find_python_files(repo_path: str) -> list[str]:
    python_files: list[str] = []
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [
            d for d in dirs
            if d not in SKIP_DIRS and not d.endswith(".egg-info")
        ]
        for filename in files:
            if filename.endswith(".py"):
                python_files.append(os.path.join(root, filename))
    return python_files
 
 
# Per-file static analysis
 
def _documentation_detail(tree: ast.AST) -> tuple[int, int, list[dict]]:
    """Returns (documented_count, documentable_count, undocumented_items)."""
    documented = 0
    documentable = 0
    undocumented: list[dict] = []
 
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            documentable += 1
            if ast.get_docstring(node):
                documented += 1
            else:
                undocumented.append({
                    "name": node.name,
                    "type": "class" if isinstance(node, ast.ClassDef) else "function",
                    "lineno": node.lineno,
                })
 
    return documented, documentable, undocumented
 
 
def analyze_file(filepath: str, repo_path: str) -> dict | None:
    """Analyze a single Python file. Returns None if the file can't be
    read or parsed at all -- callers should skip it, not crash."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            code = f.read()
    except OSError:
        return None
 
    rel_path = os.path.relpath(filepath, repo_path).replace("\\", "/")
 
    functions = []
    try:
        for block in cc_visit(code):
            functions.append({
                "name": block.name,
                "complexity": block.complexity,
                "lineno": block.lineno,
            })
    except Exception:
        pass  # malformed file -- still try the other metrics below
 
    try:
        mi = mi_visit(code, True)
    except Exception:
        mi = None
 
    try:
        halstead = h_visit(code)
        halstead_volume = halstead.total.volume if halstead.total.volume > 0 else 0.0
    except Exception:
        halstead_volume = 0.0
 
    try:
        loc = raw_analyze(code).loc
    except Exception:
        loc = 0
 
    try:
        tree = ast.parse(code)
        documented, documentable, undocumented = _documentation_detail(tree)
    except SyntaxError:
        documented, documentable, undocumented = 0, 0, []
 
    return {
        "filepath": rel_path,
        "mi": mi,
        "halstead_volume": halstead_volume,
        "loc": loc,
        "functions": functions,
        "documented_count": documented,
        "documentable_count": documentable,
        "undocumented": undocumented,
    }
 
 
# Git metrics

def _safe_branch_count(repo: Repo) -> int:
    """Count remote-tracking branches."""
    try:
        return len(list(repo.remote().refs))
    except Exception:
        try:
            return len(list(repo.branches))
        except Exception:
            return 0


def compute_git_metrics(repo_path: str, python_files: Iterable[str]) -> dict:
    """
    Repo-level git aggregates plus per-file churn using high-performance
    single-command batch git.log stream instead of individual commit.stats calls.
    """
    empty_result = {
        "commit_count": 0, "commit_freq": 0.0, "contributors": 0,
        "total_churn": 0, "churn_concentration": 0.0,
        "branch_count": 0, "merge_count": 0, "churn_by_file": {},
    }

    try:
        repo = Repo(repo_path)
    except (InvalidGitRepositoryError, ValueError):
        return empty_result

    python_file_names = {
        os.path.relpath(p, repo_path).replace("\\", "/") for p in python_files
    }

    # Execute a single native batch command for up to MAX_COMMITS
    try:
        raw_log = repo.git.log(
            f"-n{MAX_COMMITS}",
            "--numstat",
            "--pretty=format:COMMIT:%H|%ae|%ct|%P",
        )
    except Exception:
        raw_log = ""

    if not raw_log.strip():
        empty_result["branch_count"] = _safe_branch_count(repo)
        return empty_result

    churn_by_file: dict[str, int] = {}
    contributor_ids: set[str] = set()
    timestamps: list[int] = []
    merge_count = 0
    commit_count = 0

    for line in raw_log.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("COMMIT:"):
            commit_count += 1
            parts = line[7:].split("|")
            # Format: Hash | Author_Email | Timestamp | Parents
            if len(parts) >= 3:
                author_email = parts[1].strip().lower()
                if author_email:
                    contributor_ids.add(author_email)
                try:
                    timestamps.append(int(parts[2].strip()))
                except ValueError:
                    pass
                if len(parts) >= 4:
                    parents = parts[3].strip().split()
                    if len(parents) > 1:
                        merge_count += 1
        else:
            # numstat format: insertions \t deletions \t filename
            parts = line.split("\t")
            if len(parts) >= 3:
                ins_str, del_str, filename = parts[0], parts[1], parts[2]
                norm_file = filename.replace("\\", "/")
                if norm_file in python_file_names:
                    try:
                        ins = int(ins_str) if ins_str != "-" else 0
                        dels = int(del_str) if del_str != "-" else 0
                        churn = ins + dels
                        churn_by_file[norm_file] = churn_by_file.get(norm_file, 0) + churn
                    except ValueError:
                        pass

    if not timestamps:
        empty_result["branch_count"] = _safe_branch_count(repo)
        return empty_result

    newest_date = timestamps[0]
    oldest_date = timestamps[-1]
    span_seconds = max(newest_date - oldest_date, 0)
    weeks = max(span_seconds / 604800, 1.0)
    commit_freq = commit_count / weeks

    total_churn = sum(churn_by_file.values())
    if total_churn > 0:
        top_three = sorted(churn_by_file.values(), reverse=True)[:3]
        churn_concentration = sum(top_three) / total_churn
    else:
        churn_concentration = 0.0

    return {
        "commit_count": commit_count,
        "commit_freq": commit_freq,
        "contributors": len(contributor_ids),
        "total_churn": total_churn,
        "churn_concentration": churn_concentration,
        "branch_count": _safe_branch_count(repo),
        "merge_count": merge_count,
        "churn_by_file": churn_by_file,
    }
 
 
# Top-level orchestrator
 
def analyze_repository(repo_path: str) -> dict:
    
    if not os.path.isdir(repo_path):
        raise FileNotFoundError(f"Repository path not found: {repo_path}")
 
    repo_name = os.path.basename(os.path.normpath(repo_path))
    python_files = find_python_files(repo_path)
 
    file_results = []
    for filepath in python_files:
        result = analyze_file(filepath, repo_path)
        if result is not None:
            file_results.append(result)
 
    git_metrics = compute_git_metrics(repo_path, python_files)
    churn_by_file = git_metrics.pop("churn_by_file")
 
    # attach per-file churn onto each file's result
    for f in file_results:
        f["churn"] = churn_by_file.get(f["filepath"], 0)
 
    # ---- repo-level aggregates (mirrors extract_training_data.py) ----
    all_complexities = [fn["complexity"] for f in file_results for fn in f["functions"]]
    all_mi = [f["mi"] for f in file_results if f["mi"] is not None]
    all_halstead = [f["halstead_volume"] for f in file_results if f["halstead_volume"] > 0]
 
    total_documented = sum(f["documented_count"] for f in file_results)
    total_documentable = sum(f["documentable_count"] for f in file_results)
 
    aggregates = {
        "repo_name": repo_name,
        "repo_path": repo_path,
        "avg_cc": statistics.mean(all_complexities) if all_complexities else 0.0,
        "avg_mi": statistics.mean(all_mi) if all_mi else 0.0,
        "avg_halstead_volume": statistics.mean(all_halstead) if all_halstead else 0.0,
        "total_loc": sum(f["loc"] for f in file_results),
        "documentation_coverage": (
            (total_documented / total_documentable) * 100
            if total_documentable else 0.0
        ),
        **git_metrics,
    }
 
    return {
        **aggregates,
        "files": file_results,
    }
 
 
if __name__ == "__main__":
    import sys
    import json
 
    target = sys.argv[1] if len(sys.argv) > 1 else "."
    result = analyze_repository(target)
 
    summary = {k: v for k, v in result.items() if k != "files"}
    summary["file_count"] = len(result["files"])
    print(json.dumps(summary, indent=2))