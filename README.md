# repro-verdict

**Auditable acceptance checking for paper reproduction.**

Reproducing a paper usually ends with a vague feeling: *"the numbers are roughly
right."* repro-verdict turns that feeling into two separate, checkable things:

1. **A deterministic grade** — did the reproduced numbers match the claims, inside
   tolerances you chose *before* running anything?
2. **A reviewer panel score** — is the reproduction trustworthy: faithful, well
   evidenced, and rerunnable by someone else?

The grade is pure arithmetic, so it is auditable. The panel is an LLM judgement, so
it is clearly labelled as judgement. They never get mixed together.

[中文说明见 README.zh-CN.md](README.zh-CN.md)

---

## Why two layers

Most "did I reproduce it?" scripts answer one question and silently pretend it is
the other. A script that reports `RMSE 284.40 vs 284.83` tells you nothing about
whether the run is trustworthy, and an LLM that says *"looks close enough"* tells
you nothing you can audit.

So repro-verdict splits them:

| Layer | Question | Method |
| --- | --- | --- |
| Grade | Did the numbers land? | Arithmetic over claims vs observations |
| Panel | Should you believe the run? | Three reviewer personas returning structured JSON |

## Grades

Grades are ordered `A > B > C > F`, and the overall grade is the **worst** of all
metrics, so a single failure is never hidden behind a pile of successes.

| Grade | Meaning |
| --- | --- |
| `A` | Observation matches the claim inside the strict relative tolerance |
| `B` | Matches inside the relaxed relative tolerance |
| `C` | Nothing was claimed, but a number was produced: the pipeline runs |
| `F` | Missing observation, or outside the relaxed tolerance |

Tolerances default to `A <= 0.1%` and `B <= 5%` and are declared in the plan, which
means **the acceptance bar is written down before the run**, not negotiated after
seeing the result.

The grade only answers *did the numbers land*. It is deliberately paired with a
second number — see [Requirement coverage](#requirement-coverage).

## Install

```bash
pip install repro-verdict            # core, no dependencies
pip install "repro-verdict[yaml]"    # + PyYAML, for .yaml plans
pip install "repro-verdict[llm]"     # + openai, for the reviewer panel
```

From a checkout, without installing:

```bash
export PYTHONPATH=src
python -m repro_verdict.cli --help
```

## Quickstart

```bash
repro-verdict init repro-plan.yaml
repro-verdict check --plan repro-plan.yaml --runs runs/ --out REPRO_REPORT.md
```

With the reviewer panel (any OpenAI-compatible endpoint works):

```bash
export REPRO_VERDICT_API_KEY=...
export OPENAI_BASE_URL=http://127.0.0.1:8080/v1

repro-verdict check --plan repro-plan.yaml --runs runs/ \
  --llm --model your-model-name --out REPRO_REPORT.md
```

Check whether the reviewer panel is even stable before trusting its verdicts:

```bash
repro-verdict selfcheck --plan repro-plan.yaml --runs runs/ --repeat 3 --temperature 0.7
```

Exit code is `0` when the target grade is met, `1` when it is not, `2` on a broken
plan or run file — so it drops straight into CI.

## The plan file

The plan is the contract. It fixes the claims, the tolerances and the target grade
before any run happens.

```yaml
paper: "10.3390/math12010103"
title: "GSA-KELM-KF: A Hybrid Model for Short-Term Traffic Flow Forecasting"
target_grade: B

tolerances:
  A: 0.001   # 0.1% relative error
  B: 0.05    # 5% relative error

claims:
  - { key: rmse, group: A1, claimed: 284.83, unit: vehs/h }
  - { key: rmse, group: A2, claimed: 193.58, unit: vehs/h }
  - { key: rmse, group: A4, claimed: 221.36, unit: vehs/h }
  - { key: rmse, group: A8, claimed: 162.84, unit: vehs/h }

environment:
  gpu: "2x RTX 4090 24GB"
  python: "3.10.12"
  data: "PeMS sections A1/A2/A4/A8, 5-minute flow"

gaps:
  - "GSA iteration count is not stated in the paper."

notes:
  - "KELM (gamma, sigma) chosen by grid search: (0.01, 2.0)."
```

`environment`, `gaps` and `notes` are not decoration: they are handed to the
reviewer panel, so it judges with your constraints and your declared unknowns in
view instead of guessing them.

## The run files

Any JSON document with a `metrics` list (a bare list also works) is accepted, so
existing experiment logs need no rewriting:

```json
{
  "run_id": "20261001-kelm-grid",
  "metrics": [
    { "key": "rmse", "group": "A1", "observed": 284.40, "unit": "vehs/h" }
  ]
}
```

Pass several files, or a directory and every `*.json` inside it is read.

## Ordering consistency

Numbers can be individually close while the *story* flips. When several groups
share a metric key — road sections, datasets, model sizes — repro-verdict also
reports the Spearman rank correlation between claimed and observed values:

```
| metric | groups              | n | Spearman rho | ordering consistent |
| rmse   | A1, A2, A4, A8      | 4 | 1            | yes                 |
```

A high per-metric agreement combined with a negative rho is exactly the situation
where "the numbers look fine" hides a broken conclusion.

## Requirement coverage

A flat list of numbers cannot express the part of a reproduction that isn't a
number: *was the method implemented at all?* Papers claim four RMSE values, but
the work behind them is "the search was implemented", "the filter runs as
described", "the ablation was produced".

So a plan may declare a **requirement tree**. Every leaf earns weight, is worth
partial credit, and lands on one rung of a ladder:

| kind | asks | how it is judged |
| --- | --- | --- |
| `development` | the code exists | attested by the reproducer, audited by the panel |
| `execution` | it was actually run | attested by the reproducer, audited by the panel |
| `result` | the numbers match | **graded arithmetically**, exactly like a claim |

```yaml
frozen_at: "2026-10-01T00:00:00Z"

requirements:
  - id: method
    text: "GSA-KELM-KF implemented as the paper describes it"
    children:
      - { id: kelm,     text: "KELM kernel + hyperparameter search", kind: development, attested: true }
      - { id: gsa,      text: "GSA gravitational search",           kind: development, attested: false }
      - { id: kalman,   text: "Kalman leg and eta fusion",          kind: development, attested: false }
      - { id: ablation, text: "ablation table produced",            kind: execution,   attested: false,
          weight: 1.5 }
      - id: kelm_numbers
        text: "KELM baseline reproduces Table 1 / Table 2"
        kind: result
        weight: 2.0
        claim_ids: [rmse_kelm@A1, rmse_kelm@A2, rmse_kelm@A4, rmse_kelm@A8]
```

The report then carries a **coverage score** next to the grade:

```
Overall grade: B (same magnitude / ordering) — A: 2, B: 7, C: 0, F: 0
Requirement coverage: 46.2% (2/5 leaves earned)
```

And when the two disagree, it says so out loud instead of quietly picking one:

```
Gate warnings — the numeric grade and the tree disagree
- numeric grade is B, but requirement 'kalman' (development) is unsatisfied
```

The grade is deliberately **not** rewritten by the tree. Silently folding
"not implemented" into the grade would make the grade unauditable; surfacing the
contradiction is the honest move.

## Provenance gate

"Produced by this reproduction" should be a rule, not a promise. Set `frozen_at`
in the plan and give observations a `produced_at`; anything older than the freeze
is refused, so a leftover JSON from last month cannot pass as this run's result.

```json
{ "key": "rmse", "group": "A1", "observed": 284.40, "produced_at": "2026-10-01T12:04:00Z" }
```

## Gaps that carry weight

Gaps used to be prose. They can now name the claims they affect and how they were
resolved, which lets a declared, documented hole stop being scored as a silent
failure:

```yaml
gaps:
  - id: no-kf-leg
    text: "This run has no Kalman leg, so it is GSA-KELM, not GSA-KELM-KF."
    affects: [rmse_gsa@A8]
    resolved_by: "treat the A8 figure as an order-of-magnitude check only"
```

A gap only downgrades `F` to `C` when it both names the claim **and** states a
resolution. A gap with no resolution changes nothing, and an observation that is
missing outright stays missing.

## The reviewer panel

Three roles, each returning a structured form that is combined into a 0-10 score:

| Reviewer | Asks |
| --- | --- |
| Fidelity | Is the implementation faithful, are hyperparameters covered, are undocumented choices disclosed? |
| Evidence | Do the numbers, baselines, ablations and seed spread actually support the claim? |
| Reproducibility | Could a stranger rerun this: scripts, environment, seeds, data? |

Each reviewer needs a `Verdict` and a `Confidence`, and the run never aborts when one
reviewer fails — the failure is recorded on that reviewer so the rest of the report
still renders.

Findings must name where they live and how bad they are, so a review is actionable
rather than a mood:

```
| location                  | severity | issue                                        |
| Requirement tree / kalman | high     | only the GSA-KELM leg is implemented ...     |
| Reproducer notes / kelm.py| medium   | gamma/sigma came from grid search, not ...   |
```

The panel section always states its own validity, because a half-failed panel must
never look like an agreeing one:

```
Panel validity: 3/3 reviewers returned a parseable score
```

If no reviewer returns a usable result, `check --llm` exits `2`.

## Auditing the panel

The requirement coverage is arithmetic and auditable. The panel is judgement, and
until it is measured it is only vibes. `selfcheck` runs the panel repeatedly on
identical input and reports score dispersion and decision agreement:

```bash
repro-verdict selfcheck --plan repro-plan.yaml --runs runs/ --repeat 5 --temperature 0.7
```

```
reviewer          valid   mean    stdev   agreement   decision
fidelity          5/5     5.5     0.00    5/5         Partially faithful
evidence          5/5     4.12    0.31    4/5         Unsupported
```

This is a **stability** check, not a validity check: a panel can be consistently
wrong. Validity needs human-labelled expectations, which repetition cannot
substitute for.

## Python API

```python
from repro_verdict import Claim, Observation, Tolerances, compare_claims

verdict = compare_claims(
    [Claim(key="rmse", group="A1", claimed=284.83)],
    [Observation(key="rmse", group="A1", observed=284.40)],
    Tolerances(a=0.001, b=0.05),
)

print(verdict.grade)              # Grade.B
print(verdict.comparisons[0].rel_err)
```

## Design notes

- **The plan is written first.** Tolerances are declared before the run, which is
  what makes the grade meaningful rather than post-hoc.
- **Deterministic by default.** The reviewer panel is opt-in (`--llm`), so the grade
  never depends on a model being reachable.
- **No hidden state.** A missing observation is reported as missing, never skipped,
  and observations that the plan does not claim are surfaced too.
- **Boring dependencies.** The core has none.

## Credits

The reviewer-panel idea — several personas, each returning a structured JSON review
that is then scored — follows the reviewer loop popularised by
[Agent Laboratory](https://github.com/SamuelSchmidgall/AgentLaboratory) (Schmidgall
et al.) and The AI Scientist. This project re-aims that loop at *reproduction*
rather than paper acceptance, and pairs it with a deterministic grade, which those
systems do not provide.

## License

MIT. See [LICENSE](LICENSE).
