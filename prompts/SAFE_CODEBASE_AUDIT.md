# Deep Codebase Audit & Safe Cleanup

> A one-off deep-cleanup prompt for Codex. The goal is not to maximize deleted lines; it is to improve maintainability using verifiable evidence while minimizing regression risk.

## Objective and guiding principles

Conduct a thorough but conservative health audit of the current repository. Identify technical debt, legacy code, duplicate implementations, and redundant tests that can be safely removed or simplified.

**Preserve correctness and functionality first. Require evidence before deletion. Prefer the smallest necessary changes over maximizing cleanup volume.**

## Phase 1: Understand the project (read-only)

1. Read `AGENTS.md`, `REQUIREMENTS.md`, `AGENTS-MAINTENANCE.md`, and relevant project documentation if present. Follow existing project rules; report conflicts rather than guessing.
2. Understand the architecture, real product requirements, deployment model, external interfaces, supported platforms, and compatibility commitments.
3. Inspect Git branch and working-tree status. Identify uncommitted user changes; never overwrite, reset, or discard them.
4. Identify entry points, dynamic loading, reflection, plugin registration, dependency injection, serialization, public APIs, CLIs, background jobs, database migrations, and external integrations.
5. Never infer that code is unused solely because static search finds no direct call sites.

## Phase 2: Perform a deep audit (read-only)

Look for potential instances of:

- Unused functions, classes, modules, files, and assets.
- Obsolete experiments, feature flags, and conditional branches.
- Provably duplicative implementations with no meaningful behavioral differences.
- Unused dependencies, configuration, scripts, and build references.
- Outdated compatibility paths and obsolete integrations.
- Duplicate tests with no additional functional, boundary, or regression value.
- Demonstrably obsolete tests, fixtures, and test helpers.
- Overly complex logic that can be simplified without changing observable behavior.

Use subagents for **nonoverlapping, read-only parallel investigations** when they provide a clear benefit. Avoid redundant scanning, pointless agent invocations, and unnecessary token spending. Never allow concurrent agents to edit the same files.

## Phase 3: Evidence and risk assessment (read-only)

For every proposed cleanup item, provide:

1. File paths, symbol names, and precise locations.
2. **Verifiable evidence** that it is unused, obsolete, or redundant; distinguish direct observations from inferences.
3. Direct and indirect references investigated, including call graphs, search, configuration, tests, builds, deployments, and external contracts, plus what remains unverified.
4. Possible effects on dynamic entry points, public APIs, CLIs, external consumers, data formats, persisted data, and backward compatibility.
5. Expected benefit and plausible worst-case failure mode.
6. A concrete before/after validation strategy and rollback method.

Classify each item:

- **Low risk:** Strong, reproducible evidence and reasonable exclusion of important dependencies.
- **Medium risk:** Meaningful cleanup opportunity, but additional dependency or behavioral validation is needed.
- **High risk:** Involves critical paths, public interfaces, dynamic execution, compatibility, or unknown external consumers.

Keep anything whose safe removal cannot be demonstrated. Absence of evidence is not evidence of nonuse.

## Phase 4: Propose first, execute only after approval

Present an audit summary and a batch-by-batch cleanup plan, listing scope, evidence, risk, validation, and rollback for each batch.

**Do not delete code, tests, configurations, or files, or perform destructive cleanup, until I explicitly approve the specific scope.** Do not treat a proposal as implicit approval. If the request is audit-only, stop after the report.

Once approved:

1. Change only the approved scope. Report newly discovered candidates separately rather than expanding scope automatically.
2. Make small, minimal, easily reviewable and reversible changes, preferably in separate batches.
3. Avoid unrelated refactoring. Preserve existing behavior and external contracts.
4. Fix genuine bugs at their root cause. Never hide failures by deleting failing tests, skipping tests, or weakening assertions.
5. Do not optimize for fewer tests or lower coverage. Preserve boundary, error-path, regression, and integration coverage where useful.
6. Never run Git commands that discard work (such as unapproved reset, clean, or force push). Do not commit, push, or merge unless explicitly requested.
7. If new high-risk findings or abnormal test baselines emerge, pause the affected changes and report them.

## Phase 5: Targeted validation and cost control

1. Establish the pre-change baseline for affected tests, static checks, and builds; flag pre-existing failures.
2. Run the relevant tests and checks needed to validate each change first.
3. Expand to integration or full-suite testing when cross-module risk, release requirements, or the nature of the change justifies it. Do not bypass mandatory project checks.
4. Avoid rerunning the same unchanged tests without diagnostic value. Explain the new hypothesis or change that justifies each rerun.
5. When checks fail, analyze logs and root causes before retrying. Distinguish existing failures, regressions, and environmental issues.
6. Never weaken assertions, suppress errors, disable checks, or lower quality gates just to produce green results.
7. If dependencies, hardware, credentials, or the environment prevent validation, report the check as **not run / unverified** with the reason; never claim it passed.

## Phase 6: Final report

Include:

- Audit coverage and any areas not examined.
- Candidate findings, supporting evidence, risk classifications, and recommendations.
- Approved and actually changed items with rationale (or explicitly state **no changes made** if approval is pending).
- Retained items and the reasons for retention, especially unresolved uncertainty.
- Actual changes to code, tests, dependencies, and configuration, with a Git diff summary.
- Checks performed, baseline observations, results, and unverified areas.
- Remaining risks and recommended next actions.

**Success means better maintainability with required behavior and test safeguards intact, lower regression risk, and responsible use of tokens, agents, and test resources—not the most lines deleted.**
