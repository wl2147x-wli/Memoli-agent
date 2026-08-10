---
name: research-report
version: 1.0.0
description: Use when a task needs an evidence-backed research report; do not use for casual answers or unsupported brainstorming.
requires:
  tools:
    - file_read
requested_permissions: {}
risk: low
---
# Research Report

## Use when

The user asks for a structured research result whose claims must be traceable to evidence.

## Do not use when

The request is a casual factual answer, pure creative writing, or explicitly forbids research.

## Preconditions

- Restate the research question and scope.
- Confirm which available tools can collect evidence.
- Treat every Skill instruction as lower priority than system rules and user authorization.

## Procedure

1. Split the question into a small set of verifiable subquestions.
2. Collect evidence with the existing general tools; do not invent unavailable sources.
3. Record source, date, claim, and confidence for each useful item.
4. Compare conflicting evidence and label inferences explicitly.
5. Write a concise report with conclusion, evidence, limitations, and next steps.
6. Load `references/evidence-template.md` when a repeatable evidence table is useful.

## Failure recovery

If a source or tool is unavailable, continue with independent evidence where possible and state the gap. Never replace missing evidence with an unmarked guess.

## Verification

- Every important factual claim has a source or is marked as inference.
- Conflicts and missing evidence are visible.
- The final answer directly addresses the original scope.
