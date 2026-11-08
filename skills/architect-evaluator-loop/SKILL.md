---
name: architect-evaluator-loop
description: Run an iterative Architect-and-Evaluator design loop to produce or review a system design against weighted requirements. Use when designing a non-trivial system, validating a design against an assignment/rubric, or when asked to "design and have it reviewed", "score my architecture", or run a designer/critic loop.
---

# Architect ⇄ Evaluator Loop Skill

A two-role method for producing a defensible design: an **Architect** proposes, an **Evaluator**
scores it against the actual requirements and finds gaps, the Architect revises. Repeat until
coverage is complete. It is how the design in this repo was built (`docs/12-evaluation-validation.md`
is the evaluator output).

## Inputs
- The requirements/brief (or rubric) with any weights.
- The current design (or nothing, for a fresh design).

## Procedure

### 0. Build the traceability matrix FIRST
Extract every requirement, give each an ID, and record where in the design it is satisfied and
what evidence proves it. This is the shared contract both roles work against. (See
`docs/00-requirements-traceability.md`.)

### 1. Architect pass
Produce/revise the design: pick the architectural style, define components and contracts,
make technology choices **with explicit trade-offs (one ADR per real decision)**, and state
assumptions plainly. Favor the simplest design that fully meets the requirements; don't
over-engineer for scale the brief doesn't ask for.

### 2. Evaluator pass (switch hats — be adversarial)
For each weighted criterion:
- Is it **fully** addressed, or only asserted? Demand the mechanism, not a claim.
- Score **design completeness** per criterion and compute the weighted total.
- Log every gap as a concrete finding: `❗ <criterion>: <what's missing> → <required change>`.
- Probe the usual weak spots: security enforced by prompt instead of code; "degrades
  gracefully" with no ladder; recursion/fan-out unbounded; citations unverified; no failure/
  concurrency story; observability that can't actually be inspected; cost/latency ignored.

### 3. Revise
Architect closes each finding. Record what changed in an iteration log.

### 4. Stop condition
Loop until the matrix has no ❌ coverage and the weighted score is at target (or remaining gaps
are explicitly accepted trade-offs with rationale). Typically 2–3 iterations.

## Outputs
1. Requirements traceability matrix.
2. Design docs + diagrams + ADRs.
3. **Scorecard** (criterion × weight × coverage = weighted score) + iteration log + residual
   risks. (`docs/12-evaluation-validation.md`.)

## Rules that keep it honest
- Scores are **design-completeness**, not implementation — say so.
- An intentional sub-max score needs a one-line reason (scope/trade-off).
- The Evaluator must find at least one real gap per early iteration or it isn't trying.
- Every "we handle X" must point to the mechanism (a doc section, a node, an ADR).
