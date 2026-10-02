"""Loading reproduction plans and run observations from disk."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from .models import Claim, Gap, Observation, Requirement, RequirementKind, Tolerances


class PlanError(ValueError):
    """Raised when a plan or run file cannot be interpreted."""


def read_structured(path: Path) -> Any:
    """Read JSON or YAML from ``path``."""

    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise PlanError(
                "PyYAML is required for YAML files, install with: pip install 'repro-verdict[yaml]'"
            ) from exc
        return yaml.safe_load(text)
    if suffix == ".json":
        return json.loads(text)
    raise PlanError(f"unsupported file type '{path.name}': expected .json, .yaml or .yml")


def as_float(value: Any) -> float | None:
    """Coerce ``value`` to ``float``, treating ``None`` and ``""`` as missing."""

    if value is None:
        return None
    if isinstance(value, bool):
        raise PlanError(f"expected a number, got a boolean: {value!r}")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text == "":
        return None
    try:
        return float(text)
    except ValueError as exc:
        raise PlanError(f"expected a number, got {value!r}") from exc


def as_datetime(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp, accepting a trailing ``Z``."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise PlanError(f"expected an ISO-8601 timestamp, got {value!r}") from exc


@dataclass
class Plan:
    """A reproduction plan: what the paper claims, and what counts as success."""

    claims: list[Claim] = field(default_factory=list)
    tolerances: Tolerances = field(default_factory=Tolerances)
    title: str = ""
    paper: str = ""
    target_grade: str = ""
    notes: list[str] = field(default_factory=list)
    judge_notes: list[str] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    frozen_at: datetime | None = None
    environment: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


def parse_requirements(raw: Any, path: str = "requirements") -> list[Requirement]:
    """Parse a nested requirement forest."""

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PlanError(f"'{path}' must be a list")

    nodes: list[Requirement] = []
    for position, entry in enumerate(raw):
        if not isinstance(entry, dict) or "id" not in entry:
            raise PlanError(f"each requirement needs at least an 'id': got {entry!r} in {path}")
        kind = str(entry.get("kind") or RequirementKind.result.value).lower()
        try:
            requirement_kind = RequirementKind(kind)
        except ValueError as exc:
            allowed = ", ".join(k.value for k in RequirementKind)
            raise PlanError(f"unknown requirement kind {kind!r} (use one of: {allowed})") from exc

        attested = entry.get("attested")
        if attested is not None and not isinstance(attested, bool):
            raise PlanError(f"'attested' must be true or false: got {attested!r} in {path}[{position}]")

        nodes.append(
            Requirement(
                id=str(entry["id"]),
                text=str(entry.get("text") or ""),
                kind=requirement_kind,
                weight=as_float(entry.get("weight")) or 1.0,
                children=tuple(
                    parse_requirements(entry.get("children"), path=f"{path}[{position}].children")
                ),
                claim_ids=tuple(str(c) for c in (entry.get("claim_ids") or [])),
                attested=attested,
                evidence=str(entry.get("evidence") or ""),
            )
        )
    return nodes


def parse_gaps(raw: Any) -> list[Gap]:
    """Parse gaps; a bare string is accepted and given a generated id."""

    if raw is None:
        return []
    if not isinstance(raw, list):
        raise PlanError("'gaps' must be a list")

    gaps: list[Gap] = []
    for position, entry in enumerate(raw):
        if isinstance(entry, str):
            gaps.append(Gap(id=f"gap-{position + 1}", text=entry))
            continue
        if not isinstance(entry, dict):
            raise PlanError(f"each gap must be text or a mapping: got {entry!r}")
        gaps.append(
            Gap(
                id=str(entry.get("id") or f"gap-{position + 1}"),
                text=str(entry.get("text") or ""),
                affects=tuple(str(a) for a in (entry.get("affects") or [])),
                default=str(entry.get("default") or ""),
                resolved_by=str(entry.get("resolved_by") or ""),
            )
        )
    return gaps


def parse_plan(data: dict[str, Any]) -> Plan:
    """Turn a decoded plan document into a :class:`Plan`."""

    if not isinstance(data, dict):
        raise PlanError("plan must be a mapping at the top level")

    raw_claims = data.get("claims") or []
    if not isinstance(raw_claims, list):
        raise PlanError("'claims' must be a list")

    claims: list[Claim] = []
    for entry in raw_claims:
        if not isinstance(entry, dict) or "key" not in entry:
            raise PlanError(f"each claim needs at least a 'key': got {entry!r}")
        claims.append(
            Claim(
                key=str(entry["key"]),
                claimed=as_float(entry.get("claimed")),
                group=str(entry.get("group") or ""),
                unit=str(entry.get("unit") or ""),
                note=str(entry.get("note") or ""),
            )
        )

    raw_tol = data.get("tolerances") or {}
    if not isinstance(raw_tol, dict):
        raise PlanError("'tolerances' must be a mapping such as {A: 0.001, B: 0.05}")
    tolerances = Tolerances(
        a=as_float(raw_tol.get("A", raw_tol.get("a", 0.001))) or 0.0,
        b=as_float(raw_tol.get("B", raw_tol.get("b", 0.05))) or 0.0,
    )

    environment = data.get("environment") or {}
    if not isinstance(environment, dict):
        raise PlanError("'environment' must be a mapping")

    return Plan(
        claims=claims,
        tolerances=tolerances,
        title=str(data.get("title") or ""),
        paper=str(data.get("paper") or ""),
        target_grade=str(data.get("target_grade") or ""),
        notes=[str(n) for n in (data.get("notes") or [])],
        judge_notes=[str(n) for n in (data.get("judge_notes") or [])],
        gaps=parse_gaps(data.get("gaps")),
        requirements=parse_requirements(data.get("requirements")),
        frozen_at=as_datetime(data.get("frozen_at")),
        environment=environment,
        raw=data,
    )


def load_plan(path: str | Path) -> Plan:
    """Read and parse a plan file."""

    return parse_plan(read_structured(Path(path)))


def parse_observations(data: Any, source: str = "", run_id: str = "") -> list[Observation]:
    """Parse one run document into observations.

    A metric inherits the document level ``run_id`` unless it sets its own.
    """

    metrics = data.get("metrics") if isinstance(data, dict) else data
    if metrics is None:
        metrics = []
    if not isinstance(metrics, list):
        raise PlanError(f"run document must contain a 'metrics' list: {source or '<memory>'}")

    if isinstance(data, dict):
        run_id = str(data.get("run_id") or run_id)

    observations: list[Observation] = []
    for entry in metrics:
        if not isinstance(entry, dict) or "key" not in entry:
            raise PlanError(f"each metric needs at least a 'key': got {entry!r} in {source or '<memory>'}")
        observations.append(
            Observation(
                key=str(entry["key"]),
                observed=as_float(entry.get("observed", entry.get("value"))),
                group=str(entry.get("group") or ""),
                unit=str(entry.get("unit") or ""),
                source=str(entry.get("source") or source),
                produced_at=as_datetime(entry.get("produced_at")),
                run_id=str(entry.get("run_id") or run_id),
            )
        )
    return observations


def load_observations(paths: Sequence[str | Path]) -> list[Observation]:
    """Load observations from run files, or from every ``*.json`` in a directory."""

    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            files.extend(sorted(p for p in path.rglob("*.json") if p.is_file()))
        elif path.is_file():
            files.append(path)
        else:
            raise PlanError(f"run path does not exist: {path}")

    observations: list[Observation] = []
    for path in files:
        observations.extend(parse_observations(read_structured(path), source=path.name))
    return observations
