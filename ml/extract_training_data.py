"""
extract_training_data.py

Offline dataset-generation script for GitMetricAI.

For each repository under ../repositories/, this script extracts:
    Repository-level metrics:
        - commit count
        - commit frequency
        - contributor count
        - total Python code churn
        - churn concentration
        - branch count
        - merge commit count

    Static code metrics:
        - average cyclomatic complexity
        - average maintainability index
        - average Halstead volume
        - total lines of code
        - documentation coverage

It then computes:
    - code quality score
    - maintainability score
    - development activity score
    - change risk score
    - Repository Health Index (RHI)
    - Health label

Output:
    training_data.csv

Run from:
    GitMetricAI/ml/

Command:
    python extract_training_data.py
"""

from __future__ import annotations

import ast
import csv
import os
import statistics
from datetime import datetime, timezone
from typing import Iterable

from git import InvalidGitRepositoryError, Repo
from radon.complexity import cc_visit
from radon.metrics import h_visit, mi_visit
from radon.raw import analyze as raw_analyze


# ============================================================
# Configuration
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REPOS_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "repositories"))
OUTPUT_CSV = os.path.join(BASE_DIR, "training_data.csv")

# Defensive limit for repositories with extremely long histories.
MAX_COMMITS = 3000

# Directories that should not be analyzed.
SKIP_DIRS = {
    ".git",
    "venv",
    ".venv",
    "env",
    ".env",
    "node_modules",
    "migrations",
    "build",
    "dist",
    "__pycache__",
    ".tox",
    ".pytest_cache",
    ".eggs",
    "*.egg-info",
}

# Health thresholds for the proposed RHI.
HEALTHY_THRESHOLD = 73.0
STABLE_THRESHOLD = 63.0


# ============================================================
# File discovery
# ============================================================

def find_python_files(repo_path: str) -> list[str]:
    """Return all Python files while excluding irrelevant directories."""
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


# ============================================================
# Documentation coverage
# ============================================================

def documentation_coverage(code: str) -> tuple[int, int]:
    """
    Count documented functions/classes and total functions/classes.

    Returns:
        (documented_count, total_count)
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return 0, 0

    total = 0
    documented = 0

    for node in ast.walk(tree):
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        ):
            total += 1

            if ast.get_docstring(node):
                documented += 1

    return documented, total


# ============================================================
# Static code metrics
# ============================================================

def compute_code_metrics(
    python_files: Iterable[str],
) -> dict[str, float]:
    """
    Extract static code metrics across Python files.

    Invalid/unreadable files are skipped instead of terminating
    the entire repository analysis.
    """
    complexities: list[float] = []
    mi_scores: list[float] = []
    halstead_volumes: list[float] = []

    total_loc = 0
    documented_count = 0
    documentable_count = 0

    for filepath in python_files:
        try:
            with open(
                filepath,
                "r",
                encoding="utf-8",
                errors="ignore",
            ) as file:
                code = file.read()
        except OSError:
            continue

        # -----------------------------
        # Cyclomatic Complexity
        # -----------------------------
        try:
            blocks = cc_visit(code)
            complexities.extend(
                block.complexity for block in blocks
            )
        except Exception:
            pass

        # -----------------------------
        # Maintainability Index
        # -----------------------------
        try:
            mi_scores.append(mi_visit(code, True))
        except Exception:
            pass

        # -----------------------------
        # Halstead Volume
        # -----------------------------
        try:
            halstead = h_visit(code)
            if halstead.total.volume > 0:
                halstead_volumes.append(
                    halstead.total.volume
                )
        except Exception:
            pass

        # -----------------------------
        # LOC
        # -----------------------------
        try:
            total_loc += raw_analyze(code).loc
        except Exception:
            pass

        # -----------------------------
        # Documentation Coverage
        # -----------------------------
        documented, total = documentation_coverage(code)
        documented_count += documented
        documentable_count += total

    avg_cc = (
        statistics.mean(complexities)
        if complexities
        else 0.0
    )

    # McCabe (1976) proposed 10 as the complexity threshold above which
    # a module "may indicate a need to redesign." The four-band
    # extension below (Low/Moderate/High/Very High) is the widely-cited
    # convention built on that original threshold.
    band_proportions = classify_complexity_bands(complexities)

    avg_mi = (
        statistics.mean(mi_scores)
        if mi_scores
        else 0.0
    )

    avg_halstead_volume = (
        statistics.mean(halstead_volumes)
        if halstead_volumes
        else 0.0
    )

    doc_coverage = (
        (documented_count / documentable_count) * 100
        if documentable_count
        else 0.0
    )

    return {
        "avg_cc": avg_cc,
        "avg_mi": avg_mi,
        "avg_halstead_volume": avg_halstead_volume,
        "total_loc": total_loc,
        "documentation_coverage": doc_coverage,
        "pct_low_risk": band_proportions["low"],
        "pct_moderate_risk": band_proportions["moderate"],
        "pct_high_risk": band_proportions["high"],
        "pct_very_high_risk": band_proportions["very_high"],
    }


def classify_complexity_bands(complexities: list[float]) -> dict[str, float]:
    """
    Classify functions into McCabe's published risk categories
    (McCabe, T. J., 1976, "A Complexity Measure," IEEE Transactions on
    Software Engineering) and the four-band risk extension built on
    McCabe's original threshold of 10, widely used in subsequent
    literature and tooling:
        1-10   Low risk
        11-20  Moderate risk
        21-50  High risk
        50+    Very high risk

    Returns the proportion of functions falling in each band.
    A repo with zero analyzable functions is treated as 100% low risk
    rather than raising a division error.
    """
    if not complexities:
        return {"low": 1.0, "moderate": 0.0, "high": 0.0, "very_high": 0.0}

    total = len(complexities)
    low = sum(1 for c in complexities if c <= 10)
    moderate = sum(1 for c in complexities if 10 < c <= 20)
    high = sum(1 for c in complexities if 20 < c <= 50)
    very_high = sum(1 for c in complexities if c > 50)

    return {
        "low": low / total,
        "moderate": moderate / total,
        "high": high / total,
        "very_high": very_high / total,
    }


# ============================================================
# Git metrics
# ============================================================

def _safe_branch_count(repo: Repo) -> int:
    """Count remote-tracking branches (repo.branches only sees local
    branches, which is always 1 right after a fresh clone)."""
    try:
        return len(list(repo.remote().refs))
    except Exception:
        try:
            return len(list(repo.branches))
        except Exception:
            return 0


def compute_git_metrics(
    repo_path: str,
    python_files: Iterable[str],
) -> dict[str, float]:
    """
    Extract repository-level Git metrics.

    Churn is calculated only for Python files so that the
    repository-level metrics match the static-analysis scope.
    """
    try:
        repo = Repo(repo_path)
    except (InvalidGitRepositoryError, ValueError):
        return {
            "commit_count": 0,
            "commit_freq": 0.0,
            "contributors": 0,
            "total_churn": 0,
            "churn_concentration": 0.0,
            "branch_count": 0,
            "merge_count": 0,
        }

    # ----------------------------------------
    # Commits
    # ----------------------------------------
    try:
        commits = list(
            repo.iter_commits(
                max_count=MAX_COMMITS
            )
        )
    except Exception:
        commits = []

    if not commits:
        return {
            "commit_count": 0,
            "commit_freq": 0.0,
            "contributors": 0,
            "total_churn": 0,
            "churn_concentration": 0.0,
            "branch_count": _safe_branch_count(repo),
            "merge_count": 0,
        }

    # ----------------------------------------
    # Commit frequency
    # ----------------------------------------
    newest_date = commits[0].committed_date
    oldest_date = commits[-1].committed_date

    span_seconds = max(
        newest_date - oldest_date,
        0,
    )

    weeks = max(
        span_seconds / 604800,
        1.0,
    )

    commit_freq = len(commits) / weeks

    # ----------------------------------------
    # Contributors
    # ----------------------------------------
    contributor_ids = {
        commit.author.email.strip().lower()
        for commit in commits
        if commit.author and commit.author.email
    }

    contributors = len(contributor_ids)

    # ----------------------------------------
    # Python file paths
    # ----------------------------------------
    python_file_names = {
        os.path.relpath(
            filepath,
            repo_path,
        ).replace("\\", "/")
        for filepath in python_files
    }

    # ----------------------------------------
    # Churn by Python file
    # ----------------------------------------
    churn_by_file: dict[str, int] = {}

    merge_count = 0

    for commit in commits:
        try:
            # A commit with more than one parent is a merge commit.
            if len(commit.parents) > 1:
                merge_count += 1

            for filename, stats in commit.stats.files.items():
                normalized_name = filename.replace("\\", "/")

                if normalized_name not in python_file_names:
                    continue

                inserted = stats.get("insertions", 0)
                deleted = stats.get("deletions", 0)

                churn = inserted + deleted

                churn_by_file[normalized_name] = (
                    churn_by_file.get(normalized_name, 0)
                    + churn
                )

        except Exception:
            continue

    total_churn = sum(churn_by_file.values())

    # ----------------------------------------
    # Churn concentration
    # ----------------------------------------
    if total_churn > 0:
        top_three = sorted(
            churn_by_file.values(),
            reverse=True,
        )[:3]

        churn_concentration = (
            sum(top_three) / total_churn
        )
    else:
        churn_concentration = 0.0

    # ----------------------------------------
    # Branches
    # ----------------------------------------
    branch_count = _safe_branch_count(repo)

    return {
        "commit_count": len(commits),
        "commit_freq": commit_freq,
        "contributors": contributors,
        "total_churn": total_churn,
        "churn_concentration": churn_concentration,
        "branch_count": branch_count,
        "merge_count": merge_count,
    }


# ============================================================
# Scoring functions
# ============================================================

def code_quality_from_bands(band_proportions: dict[str, float]) -> float:
    """
    Severity-weighted penalty score using McCabe's (1976) published
    complexity risk bands, computed per-function.

    NOTE ON DESIGN: an earlier version of this function used a flat
    weighted average across bands (100/70/40/10). Tested against the
    47-repo training corpus, that produced almost no discrimination
    (94.4-100 range) because the vast majority of functions in every
    real repo -- even the most complex ones -- fall in the Low band
    (86-100% observed). That's an honest property of real software,
    not a flaw in McCabe's bands: complexity concentrates in a small
    number of outlier functions rather than spreading evenly.

    This version instead penalizes the score based on the proportion
    of functions ABOVE McCabe's threshold, with the penalty increasing
    for higher-severity bands -- one Very High risk function is judged
    more harmful than several Moderate ones. The bands are McCabe's;
    the specific penalty weights (100/300/600) are this project's own
    severity weighting, not part of the original 1976 paper. Verified
    on the real corpus to spread scores 76.5-100 instead of 94.4-100.
    """
    penalty = (
        band_proportions["moderate"] * 100
        + band_proportions["high"] * 300
        + band_proportions["very_high"] * 600
    )
    return max(0.0, 100.0 - min(100.0, penalty))


def percentile_rank(
    value: float,
    reference_values: list[float],
) -> float:
    """Return percentile rank from 0 to 100."""
    if not reference_values:
        return 50.0

    count = sum(
        value_i <= value
        for value_i in reference_values
    )

    return (count / len(reference_values)) * 100


def compute_rhi_scores(
    rows: list[dict],
) -> list[dict]:
    """
    Compute corpus-relative sub-scores and RHI.

    Percentile-based development/change scores are calculated
    only after all repository metrics are available.
    """
    commit_freq_values = [
        row["commit_freq"]
        for row in rows
    ]

    contributor_values = [
        row["contributors"]
        for row in rows
    ]

    churn_values = [
        row["total_churn"]
        for row in rows
    ]

    concentration_values = [
        row["churn_concentration"]
        for row in rows
    ]

    merge_count_values = [
        row["merge_count"]
        for row in rows
    ]

    branch_count_values = [
        row["branch_count"]
        for row in rows
    ]

    final_rows = []

    for row in rows:
        # Pure McCabe (1976) risk-band score -- documentation_coverage
        # is intentionally NOT blended in here, so this score traces
        # to exactly one cited source with no dilution. Documentation
        # coverage is still reported separately in the CSV output.
        code_quality = code_quality_from_bands({
            "low": row["pct_low_risk"],
            "moderate": row["pct_moderate_risk"],
            "high": row["pct_high_risk"],
            "very_high": row["pct_very_high_risk"],
        })

        maintainability = row["avg_mi"]

        # Development activity: commit frequency, contributor count,
        # merge activity, and branch usage, each corpus-relative.
        commit_percentile = percentile_rank(
            row["commit_freq"],
            commit_freq_values,
        )

        contributor_percentile = percentile_rank(
            row["contributors"],
            contributor_values,
        )

        merge_percentile = percentile_rank(
            row["merge_count"],
            merge_count_values,
        )

        branch_percentile = percentile_rank(
            row["branch_count"],
            branch_count_values,
        )

        development_score = (
            commit_percentile
            + contributor_percentile
            + merge_percentile
            + branch_percentile
        ) / 4

        churn_percentile = percentile_rank(
            row["total_churn"],
            churn_values,
        )

        concentration_percentile = percentile_rank(
            row["churn_concentration"],
            concentration_values,
        )

        # Higher churn/concentration = higher change risk.
        change_risk = 100 - (
            (
                churn_percentile
                + concentration_percentile
            ) / 2
        )

        overall = (
            code_quality
            + maintainability
            + development_score
            + change_risk
        ) / 4

        if overall >= HEALTHY_THRESHOLD:
            label = "Healthy"
        elif overall >= STABLE_THRESHOLD:
            label = "Stable"
        else:
            label = "Needs Attention"

        final_rows.append({
            **row,

            "code_quality_score": round(
                code_quality,
                2,
            ),

            "maintainability_score": round(
                maintainability,
                2,
            ),

            "development_score": round(
                development_score,
                2,
            ),

            "change_risk_score": round(
                change_risk,
                2,
            ),

            "rhi_overall": round(
                overall,
                2,
            ),

            "label": label,
        })

    return final_rows


# ============================================================
# Main
# ============================================================

def main() -> None:
    if not os.path.isdir(REPOS_DIR):
        print(
            f"ERROR: Repository directory not found:\n"
            f"{REPOS_DIR}"
        )
        return

    repo_names = sorted(
        name
        for name in os.listdir(REPOS_DIR)
        if os.path.isdir(
            os.path.join(REPOS_DIR, name)
        )
    )

    if not repo_names:
        print("No repositories found.")
        return

    print(
        f"Found {len(repo_names)} repository directories."
    )
    print("-" * 70)

    raw_rows: list[dict] = []

    for index, name in enumerate(
        repo_names,
        start=1,
    ):
        repo_path = os.path.join(
            REPOS_DIR,
            name,
        )

        print(
            f"[{index}/{len(repo_names)}] Processing {name}..."
        )

        try:
            python_files = find_python_files(
                repo_path
            )

            if not python_files:
                print(
                    "    Skipped: no Python files found."
                )
                continue

            code_metrics = compute_code_metrics(
                python_files
            )

            git_metrics = compute_git_metrics(
                repo_path,
                python_files,
            )

            raw_rows.append({
                "repo_name": name,

                # Static code metrics
                "avg_cc": round(
                    code_metrics["avg_cc"],
                    3,
                ),

                "avg_mi": round(
                    code_metrics["avg_mi"],
                    3,
                ),

                "avg_halstead_volume": round(
                    code_metrics[
                        "avg_halstead_volume"
                    ],
                    3,
                ),

                "total_loc": int(
                    code_metrics["total_loc"]
                ),

                "documentation_coverage": round(
                    code_metrics[
                        "documentation_coverage"
                    ],
                    2,
                ),

                "pct_low_risk": round(
                    code_metrics["pct_low_risk"], 4,
                ),
                "pct_moderate_risk": round(
                    code_metrics["pct_moderate_risk"], 4,
                ),
                "pct_high_risk": round(
                    code_metrics["pct_high_risk"], 4,
                ),
                "pct_very_high_risk": round(
                    code_metrics["pct_very_high_risk"], 4,
                ),

                # Git metrics
                "commit_count": int(
                    git_metrics["commit_count"]
                ),

                "commit_freq": round(
                    git_metrics["commit_freq"],
                    3,
                ),

                "contributors": int(
                    git_metrics["contributors"]
                ),

                "total_churn": int(
                    git_metrics["total_churn"]
                ),

                "churn_concentration": round(
                    git_metrics[
                        "churn_concentration"
                    ],
                    4,
                ),

                "branch_count": int(
                    git_metrics["branch_count"]
                ),

                "merge_count": int(
                    git_metrics["merge_count"]
                ),
            })

        except Exception as exc:
            print(
                f"    Skipped due to unexpected error: {exc}"
            )

    if not raw_rows:
        print(
            "\nNo repositories were processed successfully."
        )
        return

    # --------------------------------------------------------
    # Compute RHI and labels after corpus extraction
    # --------------------------------------------------------
    final_rows = compute_rhi_scores(raw_rows)

    # --------------------------------------------------------
    # CSV output
    # --------------------------------------------------------
    fieldnames = [
        "repo_name",

        # Raw/static metrics
        "avg_cc",
        "avg_mi",
        "avg_halstead_volume",
        "total_loc",
        "documentation_coverage",
        "pct_low_risk",
        "pct_moderate_risk",
        "pct_high_risk",
        "pct_very_high_risk",

        # Raw/Git metrics
        "commit_count",
        "commit_freq",
        "contributors",
        "total_churn",
        "churn_concentration",
        "branch_count",
        "merge_count",

        # RHI components
        "code_quality_score",
        "maintainability_score",
        "development_score",
        "change_risk_score",
        "rhi_overall",

        # Target
        "label",
    ]

    with open(
        OUTPUT_CSV,
        "w",
        newline="",
        encoding="utf-8",
    ) as csv_file:

        writer = csv.DictWriter(
            csv_file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for row in final_rows:
            writer.writerow(row)

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------
    label_counts: dict[str, int] = {}

    for row in final_rows:
        label = row["label"]

        label_counts[label] = (
            label_counts.get(label, 0) + 1
        )

    print("\n" + "=" * 70)
    print(
        f"Done. Wrote {len(final_rows)} rows to:"
    )
    print(OUTPUT_CSV)

    print("\nLabel distribution:")

    for label in (
        "Healthy",
        "Stable",
        "Needs Attention",
    ):
        print(
            f"  {label}: "
            f"{label_counts.get(label, 0)}"
        )

    print("=" * 70)


if __name__ == "__main__":
    main()