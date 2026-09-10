
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any


# Core Recommendation Engine


def generate_recommendations(
    scores: dict[str, Any],
    aggregates: dict[str, Any],
    issues: dict[str, Any],
    ml_prediction: dict[str, Any] | None = None,
) -> dict[str, Any]:
    
    overall_rhi = float(scores.get("overall_rhi", 0.0))
    rhi_label = scores.get("label", "Stable")
    code_quality = float(scores.get("code_quality_score", 100.0))
    maintainability = float(scores.get("maintainability_score", 100.0))
    change_risk = float(scores.get("change_risk_score", 100.0))
    dev_score = float(scores.get("development_score", 50.0))

    doc_coverage = float(aggregates.get("documentation_coverage", 0.0))
    churn_conc = float(aggregates.get("churn_concentration", 0.0))
    contributors = int(aggregates.get("contributors", 0))
    commit_count = int(aggregates.get("commit_count", 0))

    security_issues = issues.get("security_issues", [])
    complexity_issues = issues.get("complexity_issues", [])
    maintainability_issues = issues.get("maintainability_issues", [])
    hotspots = issues.get("hotspots", [])
    undocumented_count = int(issues.get("total_undocumented_count", 0))

    recs: list[dict[str, Any]] = []
    rec_counter = 1

    
    # 1. Security Vulnerabilities (P0 - CRITICAL)
    
    if security_issues:
        high_sec = [s for s in security_issues if s.get("severity") == "HIGH"]
        first_sec = security_issues[0]
        recs.append({
            "id": f"REC-{rec_counter:02d}",
            "category": "Security",
            "priority": "CRITICAL" if high_sec else "HIGH",
            "title": f"Remediate {len(security_issues)} Detected Security Anti-Pattern(s)",
            "action": (
                f"Immediately review `{first_sec.get('filepath')}:{first_sec.get('lineno')}` "
                f"({first_sec.get('title')}). Replace dynamic execution (eval/exec) or unsafe "
                "subprocesses with parameterized alternatives."
            ),
            "rationale": "Static security flaws create severe supply chain and runtime execution risks.",
        })
        rec_counter += 1

    
    # 2. Defect Hotspots & Complexity Outliers (P1 - HIGH)
    
    critical_complex = [c for c in complexity_issues if c.get("severity") == "CRITICAL"]
    if critical_complex:
        worst = critical_complex[0]
        recs.append({
            "id": f"REC-{rec_counter:02d}",
            "category": "Code Quality",
            "priority": "HIGH",
            "title": f"Refactor Monolithic Function `{worst.get('function_name')}` (CC: {worst.get('complexity')})",
            "action": (
                f"In `{worst.get('filepath')}:{worst.get('lineno')}`, function `{worst.get('function_name')}` "
                f"exceeds McCabe's Very High Risk threshold (CC > 50). Decompose nested branches and loops into smaller subroutines."
            ),
            "rationale": "Functions with CC > 50 have exponentially higher defect escape rates and cannot be tested exhaustively.",
        })
        rec_counter += 1

    if hotspots:
        top_hotspot = hotspots[0]
        recs.append({
            "id": f"REC-{rec_counter:02d}",
            "category": "Refactoring & Architecture",
            "priority": "HIGH" if top_hotspot.get("max_cc", 0) > 20 else "MEDIUM",
            "title": f"Decouple Top Churn Hotspot `{top_hotspot['filepath']}`",
            "action": (
                f"`{top_hotspot['filepath']}` accumulated {top_hotspot['churn']} churn lines with Max CC of {top_hotspot['max_cc']}. "
                "Expand unit test coverage on this module before applying further modifications."
            ),
            "rationale": "Files combining high churn with high cyclomatic complexity represent the primary source of regressions (Tornhill Hotspot model).",
        })
        rec_counter += 1


    # 3. Maintainability & Technical Debt (P1 - HIGH / P2 - MEDIUM)

    if maintainability < 65.0 or maintainability_issues:
        worst_mi = maintainability_issues[0] if maintainability_issues else None
        target = f"`{worst_mi['filepath']}` (MI: {worst_mi['mi']})" if worst_mi else "flagged files"
        recs.append({
            "id": f"REC-{rec_counter:02d}",
            "category": "Maintainability",
            "priority": "HIGH" if maintainability < 40.0 else "MEDIUM",
            "title": "Mitigate Structural Maintainability Debt",
            "action": (
                f"Refactor low Maintainability Index modules starting with {target}. "
                "Reduce Halstead volume and file length by extracting modular utility packages."
            ),
            "rationale": f"Maintainability Index is currently {maintainability}/100. Lower scores increase developer onboarding friction and bug turnaround time.",
        })
        rec_counter += 1


    # 4. Documentation Deficit

    if doc_coverage < 50.0:
        recs.append({
            "id": f"REC-{rec_counter:02d}",
            "category": "Documentation",
            "priority": "MEDIUM" if doc_coverage < 30.0 else "LOW",
            "title": f"Increase API Documentation Coverage ({round(doc_coverage, 1)}% current)",
            "action": (
                f"Add docstrings to public interfaces and classes ({undocumented_count} un-documented items detected). "
                "Enforce docstring compliance during CI using ruff or flake8-docstrings."
            ),
            "rationale": "Clear documentation prevents misconfiguration and accelerates team contribution velocity.",
        })
        rec_counter += 1


    # 5. Churn Concentration & Bus Factor

    if churn_conc > 0.45:
        recs.append({
            "id": f"REC-{rec_counter:02d}",
            "category": "Process & Change Risk",
            "priority": "MEDIUM",
            "title": f"Decouple Churn-Concentrated Modules ({round(churn_conc * 100, 1)}% in Top 3 Files)",
            "action": (
                "Over 45% of historical code churn touches only 3 files. "
                "Consider architectural decoupling (e.g. plugin or strategy patterns) to minimize merge conflict frequency."
            ),
            "rationale": "Highly concentrated change volume increases regression propagation across releases.",
        })
        rec_counter += 1

    if contributors <= 2 and commit_count > 50:
        recs.append({
            "id": f"REC-{rec_counter:02d}",
            "category": "Team Health",
            "priority": "LOW",
            "title": "Address Bus Factor / Contributor Concentration",
            "action": (
                "Repository history shows 2 or fewer primary contributors. "
                "Institute mandatory peer reviews and document Architecture Decision Records (ADRs)."
            ),
            "rationale": "Centralized repository knowledge represents an organizational risk if core maintainers transition.",
        })
        rec_counter += 1


    # 6. ML-Informed Consensus & Executive Summary
    ml_label = ml_prediction.get("ml_label") if ml_prediction else rhi_label
    confidence = ml_prediction.get("confidence", {}) if ml_prediction else {}

    if ml_prediction and ml_label != rhi_label:
        # Borderline / Divergent analysis
        top_prob = confidence.get(ml_label, 0.0) * 100
        sec_prob = confidence.get(rhi_label, 0.0) * 100
        consensus_text = (
            f"The repository is categorized as '{rhi_label}' by deterministic RHI scoring ({overall_rhi}/100), "
            f"while the Machine Learning classifier identifies strong '{ml_label}' characteristics "
            f"({round(top_prob, 1)}% vs {round(sec_prob, 1)}% probability). "
            f"This indicates a borderline repository with strong upside potential."
        )
    else:
        consensus_text = (
            f"Both the deterministic RHI evaluation ({overall_rhi}/100) and the Machine Learning classifier "
            f"unanimously categorize the repository as '{rhi_label}'."
        )

    exec_summary = (
        f"{consensus_text} "
        f"Static analysis reveals {len(issues.get('complexity_issues', []))} complexity flags, "
        f"{len(hotspots)} defect hotspots, and {undocumented_count} un-documented items. "
        f"Addressing the {len(recs)} prioritized recommendations below will directly optimize codebase longevity."
    )


    # 7. Quick Wins

    quick_wins = []
    if critical_complex:
        quick_wins.append(
            f"Split `{critical_complex[0]['function_name']}` in `{critical_complex[0]['filepath']}` into 2-3 helper functions (CC: {critical_complex[0]['complexity']})."
        )
    elif hotspots:
        quick_wins.append(
            f"Add regression tests for top hotspot `{hotspots[0]['filepath']}` before next commit."
        )

    if issues.get("top_undocumented"):
        first_undoc = issues["top_undocumented"][0]
        quick_wins.append(
            f"Document public API `{first_undoc['name']}` in `{first_undoc['filepath']}`."
        )

    if security_issues:
        quick_wins.insert(0, f"Eliminate security alert `{security_issues[0]['rule_id']}` in `{security_issues[0]['filepath']}`.")

    return {
        "executive_summary": exec_summary,
        "recommendations": recs,
        "quick_wins": quick_wins[:3],
        "total_recommendations": len(recs),
        "consensus": {
            "rhi_label": rhi_label,
            "ml_label": ml_label,
            "overall_rhi": overall_rhi,
            "confidence": confidence,
        },
    }


# Final Report Generator

def generate_markdown_report(
    repo_name: str,
    scores: dict[str, Any],
    aggregates: dict[str, Any],
    issues: dict[str, Any],
    recommendations_data: dict[str, Any],
    ml_prediction: dict[str, Any] | None = None,
) -> str:
    """Generates a complete, publication-quality Markdown audit report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rec_list = recommendations_data.get("recommendations", [])
    quick_wins = recommendations_data.get("quick_wins", [])
    hotspots = issues.get("hotspots", [])[:5]

    ml_info = ""
    if ml_prediction:
        ml_label = ml_prediction.get("ml_label", "N/A")
        conf_lines = [f"  - **{k}**: {round(v * 100, 1)}%" for k, v in ml_prediction.get("confidence", {}).items()]
        ml_info = f"""
### Machine Learning Health Prediction
- **Predicted Class**: `{ml_label}`
- **Class Probabilities**:
{chr(10).join(conf_lines)}
"""

    hotspot_rows = []
    for h in hotspots:
        hotspot_rows.append(f"| `{h['filepath']}` | {h['churn']} | {h['avg_cc']} | {h['max_cc']} | {h['hotspot_score']} |")
    hotspot_table = "\n".join(hotspot_rows) if hotspot_rows else "| None | - | - | - | - |"

    rec_cards = []
    for r in rec_list:
        rec_cards.append(f"""#### [{r['priority']}] {r['title']}
- **Category**: {r['category']}
- **Action**: {r['action']}
- **Rationale**: {r['rationale']}
""")

    report = f"""# GitMetric AI — Repository Health & Risk Audit Report
**Repository**: `{repo_name}`  
**Generated On**: {now}  
**Overall RHI**: **{scores.get('overall_rhi')}/100** (`{scores.get('label')}`)

---

## Executive Summary
{recommendations_data.get('executive_summary')}

{ml_info}

---

## Core Health Sub-Scores
| Dimension | Score | Status |
| :--- | :---: | :--- |
| **Code Quality Score** (McCabe Complexity) | `{scores.get('code_quality_score')}/100` | {'🟢 Healthy' if scores.get('code_quality_score', 0) >= 75 else '🟡 Moderate'} |
| **Maintainability Score** (Radon MI) | `{scores.get('maintainability_score')}/100` | {'🟢 Healthy' if scores.get('maintainability_score', 0) >= 65 else '🔴 Low'} |
| **Development Activity Score** (Process) | `{scores.get('development_score')}/100` | {'🟢 Active' if scores.get('development_score', 0) >= 50 else '🟡 Moderate'} |
| **Change Risk Score** (Churn & Concentration) | `{scores.get('change_risk_score')}/100` | {'🟢 Stable' if scores.get('change_risk_score', 0) >= 50 else '🔴 High Churn'} |

---

## Repository Metrics Overview
- **Total LOC**: {aggregates.get('total_loc', 0):,} lines across {aggregates.get('file_count', 0)} files
- **Documentation Coverage**: {aggregates.get('documentation_coverage', 0)}%
- **Git Commits**: {aggregates.get('commit_count', 0):,} ({aggregates.get('commit_freq', 0)} commits/week)
- **Contributors**: {aggregates.get('contributors', 0)} active authors
- **Total Code Churn**: {aggregates.get('total_churn', 0):,} lines ({round(aggregates.get('churn_concentration', 0) * 100, 1)}% in top 3 files)

---

## Top Defect Hotspots (Churn × Complexity)
| File | Churn (lines) | Avg CC | Max CC | Hotspot Score |
| :--- | :---: | :---: | :---: | :---: |
{hotspot_table}

---

## Quick Wins (Immediate Actions)
{chr(10).join([f"{i}. {w}" for i, w in enumerate(quick_wins, 1)])}

---

## Prioritized Actionable Recommendations
{"".join(rec_cards)}

---
*Generated automatically by GitMetric AI — Autonomous Codebase Health Intelligence.*
"""
    return report


# CLI Test Runner

if __name__ == "__main__":
    try:
        from scoring import score_repository
        from issues import detect_issues
        from ml_predictor import predict
    except ImportError:
        from backend.scoring import score_repository
        from backend.issues import detect_issues
        from backend.ml_predictor import predict

    target = sys.argv[1] if len(sys.argv) > 1 else "../repositories/tqdm"
    print(f"Generating full analysis & recommendations for: {target}...")

    scored = score_repository(target)
    issues = detect_issues(scored, target)
    ml_pred = predict(scored)

    result = generate_recommendations(
        scored["scores"],
        scored["aggregates"],
        issues,
        ml_prediction=ml_pred,
    )

    print("\n--- EXECUTIVE SUMMARY ---")
    print(result["executive_summary"])

    print("\n--- QUICK WINS ---")
    for idx, win in enumerate(result["quick_wins"], 1):
        print(f"  {idx}. {win}")

    print("\n--- PRIORITIZED RECOMMENDATIONS ---")
    for r in result["recommendations"]:
        print(f"[{r['priority']}] {r['title']}")
        print(f"  Action: {r['action']}\n")