"""Role-based review panel for reproduction reports.

The panel idea (several reviewer personas, each returning a structured JSON
form that is then combined into a score) follows the reviewer loop popularised
by Agent Laboratory and The AI Scientist. Here the questions are re-aimed at
*reproduction* rather than paper acceptance:

* how faithful is the implementation to the paper,
* how well does the evidence actually support the paper's claims,
* how reproducible is the pipeline for somebody else.

The panel never decides the grade. Grade comes from the deterministic
comparison; the panel audits trustworthiness.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence


TEMPLATE = """Respond in exactly this format:

THOUGHT:
<THOUGHT>

REVIEW JSON:
```json
<JSON>
```

In <THOUGHT>, reason briefly and concretely about *this* reproduction. Refer to
the specific numbers in front of you. Do not write generic advice.

In <JSON>, return one object with exactly these fields, in this order:
{fields}
"""


@dataclass(frozen=True)
class ReviewerSpec:
    """Definition of a single reviewer role."""

    key: str
    title: str
    persona: str
    dimensions: dict[str, tuple[int, str]]
    decision_label: str
    decision_options: tuple[str, ...]
    weights: dict[str, float] = field(default_factory=dict)

    def scored_fields(self) -> dict[str, float]:
        weights = dict(self.weights)
        for name in self.dimensions:
            weights.setdefault(name, 1.0)
        return {name: weight for name, weight in weights.items() if weight}

    def form(self) -> str:
        lines: list[str] = []
        for name, (scale, guidance) in self.dimensions.items():
            lines.append(f'- "{name}": a rating from 1 to {scale}, where {guidance}')
        lines.append('- "Confidence": a rating from 1 to 5 for how sure you are of this review')
        options = ", ".join(f'"{option}"' for option in self.decision_options)
        lines.append(f'- "{self.decision_label}": exactly one of {options}')
        lines.append(
            '- "Findings": a list of objects, each with the fields "location", "severity" and '
            '"issue". "location" must name the file, module, section or group the finding lives '
            'in; "severity" must be exactly one of "high", "medium" or "low". A finding without '
            "a location is not acceptable."
        )
        lines.append('- "Questions": a list of things you could not verify from the material provided')
        return "\n".join(lines)

    def system_prompt(self) -> str:
        return f"{self.persona}\n\n{TEMPLATE.format(fields=self.form())}"


REVIEWERS: dict[str, ReviewerSpec] = {
    "fidelity": ReviewerSpec(
        key="fidelity",
        title="Fidelity Reviewer",
        persona=(
            "You are a meticulous methods reviewer. Your job is to decide whether an "
            "implementation is faithful to the paper it claims to reproduce, and to name "
            "every undocumented choice that was filled in by guesswork."
        ),
        dimensions={
            "Method Fidelity": (4, "1 means the implementation diverges from the paper, 4 means it matches the described method"),
            "Hyperparameter Coverage": (4, "how completely the paper's hyperparameters, initialisation and stopping rules were identified and applied"),
            "Gap Disclosure": (4, "how explicitly undocumented settings are flagged instead of silently guessed"),
            "Overall": (10, "overall fidelity of this reproduction, 1 to 10"),
        },
        decision_label="Verdict",
        decision_options=("Faithful", "Partially faithful", "Unaligned"),
        weights={"Overall": 2.0},
    ),
    "evidence": ReviewerSpec(
        key="evidence",
        title="Evidence Reviewer",
        persona=(
            "You are a skeptical results reviewer. You care about whether the reproduced "
            "numbers, baselines and ablations actually support the claim the paper makes, "
            "and whether any reported difference is larger than run-to-run noise."
        ),
        dimensions={
            "Numerical Agreement": (4, "how closely the reproduced numbers track the claimed numbers"),
            "Baseline Rigour": (4, "whether the comparison baselines are fair, current and correctly tuned"),
            "Ablation Completeness": (4, "whether each claimed component is isolated well enough to attribute the reported gain"),
            "Statistical Care": (4, "seeds, repeats, dispersion, and whether differences exceed noise"),
            "Overall": (10, "how well the evidence supports the paper's claims, 1 to 10"),
        },
        decision_label="Verdict",
        decision_options=("Supported", "Weakly supported", "Unsupported"),
        weights={"Overall": 2.0, "Numerical Agreement": 1.5},
    ),
    "reproducibility": ReviewerSpec(
        key="reproducibility",
        title="Reproducibility Reviewer",
        persona=(
            "You are an artefact reviewer. You judge whether a competent stranger could "
            "rerun this reproduction tomorrow and land on comparable numbers."
        ),
        dimensions={
            "Script Availability": (4, "whether the scripts that produced every reported number exist and are runnable"),
            "Environment Specification": (4, "whether hardware, library versions and data versions are pinned"),
            "Seed Control": (4, "whether randomness is seeded and seed sensitivity is reported"),
            "Data Availability": (4, "whether the data is obtainable, and what happens if it is not"),
            "Overall": (10, "overall reproducibility of this artefact, 1 to 10"),
        },
        decision_label="Verdict",
        decision_options=("Reproducible", "Partially reproducible", "Not reproducible"),
        weights={"Overall": 2.0},
    ),
}


def get_specs(keys: Sequence[str] | None = None) -> list[ReviewerSpec]:
    """Return reviewer specs, defaulting to the full panel."""

    if not keys:
        return [REVIEWERS[key] for key in ("fidelity", "evidence", "reproducibility")]
    specs: list[ReviewerSpec] = []
    for key in keys:
        normalized = key.strip().lower()
        if normalized not in REVIEWERS:
            raise KeyError(f"unknown reviewer '{key}', available: {', '.join(REVIEWERS)}")
        specs.append(REVIEWERS[normalized])
    return specs


@dataclass
class Review:
    """The outcome of one reviewer call."""

    reviewer: str
    title: str
    score: float | None = None
    decision: str | None = None
    thought: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    raw: str = ""
    error: str | None = None


def parse_review(text: str) -> tuple[str, dict[str, Any]]:
    """Extract the THOUGHT block and the JSON object from a reviewer reply."""

    payload: dict[str, Any] = {}
    for block in re.findall(r"```(?:json)?\s*(.*?)```", text, re.S):
        try:
            candidate = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break

    if not payload:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                candidate = json.loads(text[start : end + 1])
                if isinstance(candidate, dict):
                    payload = candidate
            except json.JSONDecodeError:
                pass

    thought = ""
    marker = re.search(r"THOUGHT:\s*", text)
    if marker:
        tail = text[marker.end() :]
        cut = len(tail)
        for pattern in (r"\n\s*REVIEW JSON:", r"```", r"\n\s*\{"):
            hit = re.search(pattern, tail)
            if hit:
                cut = min(cut, hit.start())
        thought = tail[:cut].strip()

    return thought, payload


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def score_review(spec: ReviewerSpec, payload: dict[str, Any]) -> float | None:
    """Combine the reviewer's ratings into a 0-10 score."""

    weighted_sum = 0.0
    total_weight = 0.0
    for name, weight in spec.scored_fields().items():
        scale = spec.dimensions.get(name, (10, ""))[0]
        value = _number(payload.get(name))
        if value is None:
            continue
        weighted_sum += weight * (value / scale)
        total_weight += weight
    if not total_weight:
        return None
    return round(weighted_sum / total_weight * 10, 2)


_CLIENT_ERROR = (
    "the review panel needs the llm extra, install with: pip install 'repro-verdict[llm]'"
)


def _client(api_key: str | None = None, base_url: str | None = None):
    """Build an OpenAI-compatible client, or ``None`` when the extra is missing."""

    try:
        from openai import OpenAI
    except ImportError:  # pragma: no cover - depends on environment
        return None

    kwargs: dict[str, Any] = {}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


@dataclass
class PanelSummary:
    """Whether the panel produced anything usable.

    A panel that half-failed must never look like a panel that agreed, so the
    valid/total count is reported next to the scores.
    """

    total: int
    valid: int
    mean_score: float | None
    failed: list[str] = field(default_factory=list)
    decisions: dict[str, str] = field(default_factory=dict)

    @property
    def complete(self) -> bool:
        return self.total > 0 and self.valid == self.total

    def describe(self) -> str:
        return f"{self.valid}/{self.total} reviewers returned a parseable score"


def summarise(reviews: Sequence[Review]) -> PanelSummary:
    """Aggregate a panel run into validity counts and a mean score."""

    scored = [review.score for review in reviews if review.score is not None]
    decisions = {
        review.reviewer: review.decision
        for review in reviews
        if review.decision and not review.error
    }
    return PanelSummary(
        total=len(reviews),
        valid=len(scored),
        mean_score=round(sum(scored) / len(scored), 2) if scored else None,
        failed=[review.reviewer for review in reviews if review.error or review.score is None],
        decisions=decisions,
    )


def run_reviews(
    context: str,
    *,
    model: str,
    specs: Sequence[ReviewerSpec] | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    temperature: float = 0.0,
    timeout: float = 180.0,
    extra_instructions: str = "",
) -> list[Review]:
    """Run every reviewer in the panel over ``context``.

    A failing reviewer never aborts the panel; the failure is recorded on that
    reviewer so the rest of the report still renders.
    """

    client = _client(api_key, base_url)
    results: list[Review] = []
    user_content = context if not extra_instructions else f"{context}\n\n---\n\n{extra_instructions}"
    specs = list(specs or get_specs())

    if client is None:
        return [
            Review(reviewer=spec.key, title=spec.title, error=_CLIENT_ERROR)
            for spec in specs
        ]

    for spec in specs:
        review = Review(reviewer=spec.key, title=spec.title)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": spec.system_prompt()},
                    {"role": "user", "content": user_content},
                ],
                temperature=temperature,
                timeout=timeout,
            )
            review.raw = response.choices[0].message.content or ""
            review.thought, review.payload = parse_review(review.raw)
            review.score = score_review(spec, review.payload)
            decision = review.payload.get(spec.decision_label)
            review.decision = str(decision) if decision is not None else None
        except Exception as exc:  # noqa: BLE001 - reported, not swallowed
            review.error = f"{type(exc).__name__}: {exc}"
        results.append(review)

    return results
