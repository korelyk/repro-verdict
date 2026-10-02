"""Rendering the verification result as a Markdown report."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Sequence

from .models import Comparison, Grade, Verdict
from .plan import Plan
from .reviewers import Review


def _fmt(value: float | None, digits: int = 6) -> str:
    if value is None:
        return "-"
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.{digits}g}"


def _rel(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.3f}%"


def environment_card(plan: Plan | None) -> str:
    """Render the machine/data environment as a bullet list."""

    if plan is None or not plan.environment:
        return "_not recorded_"
    lines = []
    for key, value in plan.environment.items():
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value)
        lines.append(f"- **{key}**: {value}")
    return "\n".join(lines)


def metric_table(comparisons: Sequence[Comparison]) -> str:
    header = "| metric | group | claimed | observed | Δ | Δ% | unit | grade | reason |"
    rule = "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    rows = [header, rule]
    for comparison in comparisons:
        claim = comparison.claim
        rows.append(
            "| {key} | {group} | {claimed} | {observed} | {abs_err} | {rel_err} | {unit} | {grade} | {reason} |".format(
                key=claim.key,
                group=claim.group or "-",
                claimed=_fmt(claim.claimed),
                observed=_fmt(comparison.observed),
                abs_err=_fmt(comparison.abs_err),
                rel_err=_rel(comparison.rel_err),
                unit=claim.unit or "-",
                grade=f"**{comparison.grade.value}**",
                reason=comparison.reason,
            )
        )
    return "\n".join(rows)


def trend_table(verdict: Verdict) -> str:
    if not verdict.trends:
        return "_no multi-group metrics to compare_"
    rows = ["| metric | groups | n | Spearman ρ | ordering consistent |", "| --- | --- | --- | --- | --- |"]
    for trend in verdict.trends:
        consistency = "-" if trend.consistent is None else ("yes" if trend.consistent else "**no**")
        rows.append(
            f"| {trend.key} | {', '.join(trend.groups)} | {trend.n} | {_fmt(trend.rho, 3)} | {consistency} |"
        )
    return "\n".join(rows)


def review_sections(reviews: Sequence[Review]) -> str:
    if not reviews:
        return "_review panel not run_"

    chunks: list[str] = []
    for review in reviews:
        heading = f"### {review.title}"
        if review.error:
            chunks.append(f"{heading}\n\n**failed:** `{review.error}`")
            continue

        badges = []
        if review.score is not None:
            badges.append(f"**{review.score:g}/10**")
        if review.decision:
            badges.append(review.decision)
        chunks.append(f"{heading} — {' · '.join(badges) if badges else 'no score'}\n")

        if review.thought:
            chunks.append(f"> {review.thought.strip()}\n")

        weaknesses = review.payload.get("Weaknesses")
        if isinstance(weaknesses, list) and weaknesses:
            chunks.append("**Weaknesses raised**\n")
            chunks.extend(f"- {item}" for item in weaknesses)
            chunks.append("")

        questions = review.payload.get("Questions")
        if isinstance(questions, list) and questions:
            chunks.append("**Open questions**\n")
            chunks.extend(f"- {item}" for item in questions)
            chunks.append("")

        if review.payload:
            body = "\n".join(f"{key}: {value}" for key, value in review.payload.items() if key not in {"Weaknesses", "Questions"})
            chunks.append("<details><summary>full review JSON</summary>\n")
            chunks.append("```\n" + body + "\n```\n")
            chunks.append("</details>")

    return "\n".join(chunks)


def render_report(
    verdict: Verdict,
    *,
    plan: Plan | None = None,
    reviews: Sequence[Review] | None = None,
    generated_at: datetime | None = None,
    target_grade: str | None = None,
) -> str:
    """Render the full acceptance report."""

    stamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    title = (plan.title if plan and plan.title else "Reproduction verdict")
    paper = plan.paper if plan else ""
    target = target_grade or (plan.target_grade if plan else "") or ""

    counts = verdict.grade_counts
    summary = ", ".join(f"{grade}: {counts.get(grade, 0)}" for grade in ("A", "B", "C", "F"))

    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    if paper:
        lines.append(f"`{paper}`")
        lines.append("")
    lines.append(f"**Overall grade: {verdict.grade.value}** ({verdict.grade.label}) — {summary}")
    if target:
        try:
            met = "met" if verdict.grade.rank >= Grade(target.upper()).rank else "**not met**"
        except ValueError:
            met = "unrecognised"
        lines.append(f"Target grade: {target.upper()} — {met}")
    lines.append(f"Generated: {stamp}")
    lines.append("")

    lines.append("## 1. Metric comparison")
    lines.append("")
    lines.append(metric_table(verdict.comparisons))
    lines.append("")

    lines.append("## 2. Ordering consistency")
    lines.append("")
    lines.append(trend_table(verdict))
    lines.append("")

    lines.append("## 3. Gaps")
    lines.append("")
    if verdict.missing:
        lines.append("**Claims with no observation**")
        lines.extend(f"- `{item}`" for item in verdict.missing)
        lines.append("")
    if verdict.unclaimed:
        lines.append("**Observations with no claim in the plan**")
        lines.extend(f"- `{item}`" for item in verdict.unclaimed)
        lines.append("")
    if plan and plan.gaps:
        lines.append("**Declared gaps from the plan**")
        lines.extend(f"- {gap}" for gap in plan.gaps)
        lines.append("")
    if not verdict.missing and not verdict.unclaimed and not (plan and plan.gaps):
        lines.append("_none recorded_")
        lines.append("")

    lines.append("## 4. Reviewer panel")
    lines.append("")
    lines.append(review_sections(list(reviews or [])))
    lines.append("")

    lines.append("## 5. Environment card")
    lines.append("")
    lines.append(environment_card(plan))
    lines.append("")

    if plan and plan.notes:
        lines.append("## 6. Notes")
        lines.append("")
        lines.extend(f"- {note}" for note in plan.notes)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_review_context(verdict: Verdict, plan: Plan | None = None) -> str:
    """Assemble the deterministic findings into a prompt for the reviewer panel."""

    lines: list[str] = []
    if plan:
        lines.append(f"Paper: {plan.paper or 'unnamed'}")
        if plan.title:
            lines.append(f"Title: {plan.title}")
        if plan.target_grade:
            lines.append(f"Declared target grade: {plan.target_grade}")
        lines.append("")

    lines.append(f"Deterministic overall grade: {verdict.grade.value} ({verdict.grade.label})")
    lines.append(f"Tolerances: A <= {verdict.tolerances.a:g} relative, B <= {verdict.tolerances.b:g} relative")
    lines.append("")
    lines.append("Metric comparison:")
    lines.append(metric_table(verdict.comparisons))
    lines.append("")
    lines.append("Ordering consistency across groups:")
    lines.append(trend_table(verdict))
    lines.append("")

    if verdict.missing:
        lines.append("Claims with no observation: " + ", ".join(verdict.missing))
    if verdict.unclaimed:
        lines.append("Observations with no claim: " + ", ".join(verdict.unclaimed))
    if plan and plan.gaps:
        lines.append("")
        lines.append("Gaps declared by the reproducer:")
        lines.extend(f"- {gap}" for gap in plan.gaps)

    lines.append("")
    lines.append("Environment:")
    lines.append(environment_card(plan))

    if plan and plan.notes:
        lines.append("")
        lines.append("Reproducer notes:")
        lines.extend(f"- {note}" for note in plan.notes)

    return "\n".join(lines)
