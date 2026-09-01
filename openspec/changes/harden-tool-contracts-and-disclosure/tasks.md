## 1. Tool input contracts

- [x] 1.1 Add the declared `jsonschema` runtime dependency and central Draft 2020-12 schema/argument validation with structured failures.
- [x] 1.2 Align `memory_recall` and `memory_manage` public schemas with the fields their implementations actually consume.
- [x] 1.3 Make `code_run` schema and registration reflect container, trusted-host, and disabled runner capabilities.

## 2. Session-scoped progressive disclosure

- [x] 2.1 Add the epoch-scoped disclosure model and additive SQLite/InMemory Context State persistence contract.
- [x] 2.2 Change Tool Search to persist full canonical schemas per Session/epoch and remove Registry-global disclosure state.
- [x] 2.3 Merge persisted disclosures into ContextCompiler effective tools/hash while preserving the frozen base prefix and safety revocation behavior.
- [x] 2.4 Pass epoch and visible tool authorization through ToolExecutionContext and enforce it at Registry execution.

## 3. Verification and documentation

- [x] 3.1 Add memory schema, strict validation, runner capability, disclosure recovery, multi-Session isolation, and undisclosed-execution regression tests.
- [x] 3.2 Run targeted tests, full pytest, Ruff, Pyright, and `openspec validate --all --strict`.
- [x] 3.3 Sync affected tool/context architecture documentation and confirm the change tasks and artifacts are complete.

Verification note: full Pytest passed (569 passed, 6 skipped); changed files pass Ruff and
targeted Pyright; strict OpenSpec validation passes all 19 items. Full Ruff was also run and
retains one pre-existing import-order finding in unmodified `main.py`. Full-repository Pyright
was run with the `memoli` Conda interpreter and still reports nine pre-existing errors in
`benchmarks/feature_eval.py`, legacy trajectory-protocol narrowing in `reasoner.py`, and
`tests/test_hybrid_fusion.py`; none is introduced on a changed line in this change.
