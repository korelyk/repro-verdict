"""Loading reproduction plans and run observations from disk."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .models import Claim, Observation, Tolerances


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


@dataclass
class Plan:
    """A reproduction plan: what the paper claims, and what counts as success."""

    claims: list[Claim] = field(default_factory=list)
    tolerances: Tolerances = field(default_factory=Tolerances)
    title: str = ""
    paper: str = ""
    target_grade: str = ""
    notes: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


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
        gaps=[str(g) for g in (data.get("gaps") or [])],
        environment=environment,
        raw=data,
    )


def load_plan(path: str | Path) -> Plan:
    """Read and parse a plan file."""

    return parse_plan(read_structured(Path(path)))


def parse_observations(data: Any, source: str = "") -> list[Observation]:
    """Parse one run document into observations."""

    metrics = data.get("metrics") if isinstance(data, dict) else data
    if metrics is None:
        metrics = []
    if not isinstance(metrics, list):
        raise PlanError(f"run document must contain a 'metrics' list: {source or '<memory>'}")

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
