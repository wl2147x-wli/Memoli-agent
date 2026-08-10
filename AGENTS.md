# Memoli-agent development instructions

## OpenSpec is mandatory

`openspec/specs/` is the source of truth for current observable behavior. Before changing
code, tests, configuration contracts, persisted data, tool schemas, or user-visible behavior:

1. Read `openspec/config.yaml` and the affected specs.
2. For a new feature, behavior change, breaking change, or non-trivial refactor, create an
   OpenSpec change with `/opsx:propose <change>` and obtain agreement before implementation.
3. Implement only from an agreed change with `/opsx:apply <change>`.
4. Run the relevant tests and `openspec validate --all --strict`.
5. Sync any affected operational/architecture documentation, then archive the completed
   change with `/opsx:archive <change>` so the canonical specs reflect the shipped behavior.

Small typo-only or comment-only edits that do not change behavior may be made directly.
Bug fixes must update an existing scenario or add a regression scenario when current specs
do not already express the intended behavior.

Do not edit archived changes to describe new work. Do not mark tasks complete without
verification. If code and a canonical spec disagree, stop and resolve the discrepancy as an
explicit OpenSpec change rather than silently treating either side as correct.

## Repository checks

Run, as applicable:

```powershell
python -m pytest -q
python -m ruff check memoli_agent benchmarks tests
python -m pyright
openspec validate --all --strict
```
