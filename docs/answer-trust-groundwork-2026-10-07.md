# Phase 4.5A — Answer Trust & Verified Objective Groundwork

Date: 2026-10-07  
Disposition: **IMPLEMENTED, TESTED; operational verified-question slice remains pending**  
Scope: groundwork only. No Phase 4.5B/5 work, model calls, production data writes, commits, or pushes.

Follow-up: Phase 4.5A.1 has subsequently activated the migration on the real local development database after a verified backup. See [activation and compatibility report](answer-trust-activation-2026-10-07.md). The schema/data statements below describe the earlier groundwork snapshot, not the current schema revision.

## 1. What this phase establishes

The system now has a separate, auditable answer-review lifecycle. Existing answer fields and AI consistency results are not accepted as proof of human or authoritative-reference verification. A currently valid verification requires an append-only verification event bound to the exact answer-bearing item version.

The candidate/verification workflow is local and explicit:

- `scripts/manage_answer_verification.py candidates --subject math2|408 --limit N` lists questions for review, including question ID, subject, node, origin, type, stem, current answer, current trust/grading state, blocking reasons, and the current answer hash.
- `scripts/manage_answer_verification.py apply manifest.json` validates a review manifest in dry-run mode. `--apply` appends verification or revocation events and commits only after explicit local invocation.
- Reference verification requires a structured citation (`kind`, `identifier`, `title`, `locator`, optional SHA-256). Supplying metadata is still a reviewer assertion; the tool does not fetch or authenticate a source.
- `scripts/audit_answer_trust_slice.py` inventories the provisional two-math/two-408 slice using aggregate/status output only. It does not emit question or answer text and refuses to audit a database until the new migration is installed.

The workflow makes a clear distinction between:

1. being usable for practice;
2. having a supported comparison/grading method;
3. having a trusted answer;
4. being allowed to produce verified objective evidence.

AI-generated consistency remains an AI-derived lower-trust signal; it does not create a `human_verified` or `verified_reference` event and cannot produce `verified_objective` evidence.

## 2. Trust and evidence rules implemented

`answer_version_sha256` binds verification to the canonical JSON of question type, stem, options, mapped knowledge-point ID, and correct answer. A content change to any of those fields makes the event stale for the current question. Legacy reviewer fields without a matching current event fail closed.

The new objective-evidence path requires all relevant gates together: current answer verification, trusted question content/source, a supported deterministic final-answer grading method, and an eligible real/trusted question. Process-review, self-report, AI-consistent, and AI-generated answer paths remain distinct and cannot be silently upgraded into verified objective evidence.

Verification and revocation are append-only events. Revocation preserves the original event and the previous projection. If there is no valid prior verification to restore, the deterministic grader is disabled and the question returns to self-assessed grading. Idempotency keys prevent accidental duplicate application; a conflicting replay fails.

This is an operator-audited workflow, not a user-authentication system. `verifier` records who the operator says performed the review; it does not authenticate that identity. Likewise, a reference citation is recorded, not cryptographically proven authoritative.

No graduation thresholds were changed, no existing attempt was rewritten, and no historical AI-consistency result was backfilled as verified. Evidence behavior was regression-tested for independent correct, assisted/solution-viewed, wrong, unknown, and AI-review cases.

## 3. Data and slice audit

### Local development database snapshot

The intended development database was inspected in a read-only transaction before and after the code work. Both checks reported the same baseline:

| Entity | Count |
|---|---:|
| Questions | 518 |
| Question attempts | 28 |
| Learning events | 29 |
| Knowledge states | 284 |
| Daily plans | 10 |
| Practice items | 87 |
| Practice requests | 0 |
| Answer-consistency runs | 696 |
| Source attestations | 180 |
| Mastery-policy rows | 284 |

Current schema revision is `e42c7a10b9f3`. The answer-verification-event table does not yet exist in this database. The migration was deliberately **not** applied to the local development database. Policy snapshot SHA-256 was unchanged before/after: `c18ed340601b260f8ea1cc2a08b20a2379d9940d70da1bca9fd88a6437cff28c`.

Existing answer fields at baseline: `ai_generated=160`, `unknown=358`; reliability: `ai_generated_consistent=160`, `ai_disagreement=3`, `unknown=355`. The older eligibility projection counted 160 practice-eligible questions, including AI-consistent paths; this count is not a count of verified answers. Current human/reference verification events were 0, verified-reference answers were 0, and verified-objective questions were 0. There were 0 human review stamps before this phase.

The previous eligibility/capability distribution was:

| Capability | Count | Interpretation |
|---|---:|---|
| `ai_consistent_objective` | 160 | Previously labeled AI-consistent; must not be presented as human/reference verified |
| `process_review_not_objective_evidence` | 94 | Suitable for process/self review, not deterministic objective evidence |
| `self_report_only` | 242 | No objective grading basis |

The corresponding prior grading capability counts were `final_answer_limited=160`, `process_review_only=94`, and `unsupported=242`. The 28 historical question attempts and 29 learning events were left unchanged; no attempt or mastery record was retroactively upgraded.

### Provisional Golden Learning Slice

| Subject | Node | Active questions | Prior practice-eligible comparator | Current verified objective |
|---|---|---:|---:|---:|
| 数学二 | `math.exam.fd2f9e3739d9` — 反常积分 | 7 | 3 | 0 |
| 数学二 | `math.exam.f37948c82a05` — 曲线凹凸与拐点 | 12 | 2 | 0 |
| 408 | `cs408.ds.topic.1efaf3d00b50` — 二叉树基础 | 4 | 2 | 0 |
| 408 | `cs408.os.topic.cb972030e503` — 文件基本概念 | 10 | 1 | 0 |

These are inventory candidates, **not yet a verified Golden Slice**. At these four nodes there is no current verified answer event and no verified-objective question. Existing source/answer records are insufficient to claim the new trust contract. Missing verified questions are a valid audit outcome; no synthetic or AI-generated production question was promoted to verified.

An additional policy audit found a coverage mismatch that must be resolved before claiming graduation-ready slices: all four provisional nodes require three `external_exam` confirmations, at least three real questions, a node-specific skill tag, and evidence across at least two days. Their current online `Question` inventory does not satisfy the `external_exam` quota. Across all 284 policies, 196 require `{external_exam: 3}`, 66 require `{external_exam: 1}`, 17 require `{external_exam: 2}`, and only 5 policies specify online types such as single-choice/fill-blank/calculation. Those five are math policies; the read-only inventory did not identify corresponding active questions. No policy was weakened to make the slice appear complete.

**Decision:** the slice is not ready for verified graduation acceptance. First select source-verifiable questions and align the intended question representation with each node’s existing graduation policy. The policy’s `external_exam` meaning must not be silently treated as an online question type.

## 4. Migration and operational boundary

Migration `f45a9b7e2c10_answer_verification_audit.py` adds the immutable answer-verification event table, current-event pointer, answer provenance constraint update, and a PostgreSQL trigger that rejects update/delete of audit events. Downgrade refuses to discard verification data.

The migration and ORM path were exercised through isolated integration/migration tests. The real `kaoyan` development schema remains at `e42c7a10b9f3`; therefore the new candidate and slice audit CLIs intentionally stop with a clear schema-revision message until the operator applies the migration in the intended local environment. No real development database migration or row write occurred in this phase.

The CLI is local-only tooling and currently has no authenticated web/API review endpoint. Production writes are explicitly disabled. No web search, model, vision, RAG, or judge call was made.

## 5. Reproducibility record

- Repository `HEAD`: `b252178fce4e7852caef5332e3e7b10bd294bbc1` on branch `master`.
- Workspace is intentionally dirty (534 Git status entries including this report at closeout); no commit/push was made. `HEAD` alone does not contain this phase’s working-tree changes.
- Schema/data reference: local dev `kaoyan`, Alembic `e42c7a10b9f3`; aggregate counts and policy hash above.
- Dataset version: current local database inventory, not an exported/copyable dataset; no question/answer snapshot was exported.
- Model/provider/config: none used; 0 model calls.
- Prompt version: not applicable.
- Retrieval/rerank/context snapshot: not applicable; this is a deterministic answer-trust phase, not a RAG run.
- Answer-version snapshot contract: SHA-256 over `question_type`, `stem`, `options`, `kp_id`, `correct_answer` as canonical sorted JSON.
- Evaluation method: focused unit/integration/migration regression tests and read-only database inventory; no RAGAS scoring and no human answer-content audit.
- Token usage, model latency, retry, generation truncation: not applicable / 0 calls.
- Human verification completed during this phase: none. The operator workflow is ready, but no actual question was asserted verified.

Key-file SHA-256 values for the closeout working tree:

| File | SHA-256 |
|---|---|
| `backend/services/answer_verification.py` | `5dd0c2da99a7c7a3f6316048c2715325500aa1b1b9397b53554fc22b8701e3e5` |
| `backend/services/question_eligibility.py` | `fbd27a412134e59aea0ea7f804de037a39ce0585d6c650a59c77b400f2746656` |
| `migrations/versions/f45a9b7e2c10_answer_verification_audit.py` | `d8d41a0ee4ac40bf2cf90e5a9cef5ab26dee2c939313cc85066fb99026a5720a` |
| `scripts/manage_answer_verification.py` | `5b5a7397f0dc6e57372be86bbc8b91336c421da8d8b8b97522610122878aaa3d` |
| `scripts/audit_answer_trust_slice.py` | `070e023daeb7e5702535bd1871693a7478c603d4403e4077e006a19223a229b90` |

## 6. Verification performed

All commands below completed successfully against unit tests or isolated integration/test databases. The real development database was only queried in a read-only transaction.

| Check | Result |
|---|---|
| Focused answer trust / grading / evidence / Golden Slice unit tests | 196 passed |
| Verification, pack import, upgrade, revision, submission, trust audit, migration integration tests | 88 passed |
| Learning loop, learning tasks, planner comparison, Phase 4C API contract tests | 110 passed |
| Python compile check for changed trust/migration/CLI modules | passed |
| `git diff --check` on scoped tracked changes | passed; Git emitted a CRLF normalization warning for `backend/api/routes/study.py` |
| Real dev DB before/after inventory | same counts, revision, and policy hash |
| Model/network calls | 0 |

These are focused regressions, not a claim that the entire backend/frontend/E2E suite was rerun in Phase 4.5A.

## 7. Remaining limitations and next safe step

1. The local dev schema has not been migrated. Applying `f45a9b7e2c10` must be an explicit operator action in the intended local environment; after it, rerun the read-only slice audit and inspect generated candidate manifests.
2. No question has been human-reviewed in this phase. A reviewer must inspect the source and answer, then prepare/apply the manifest; code cannot certify that an answer is mathematically correct or that a citation is genuine.
3. The provisional slice has zero verified-objective items and its current graduation policies require `external_exam` evidence that online items do not provide. Do not claim graduation closure until source-verified inventory and representation/policy compatibility are demonstrated.
4. The audit’s `verifier` value is not authenticated; multi-user review permissions, attribution protection, and an authenticated UI are outside this groundwork.
5. The answer hash does not claim to hash the entire question package or explanation; it binds answer-bearing identity/content fields listed above. Question-source/content attestation remains a separate gate.
6. No RAG quality, OCR/vision accuracy, general proof/program grading, or overall learning effectiveness claim is supported by this phase.

**Phase stop:** Phase 4.5A groundwork is implemented and regression-tested. Stop here; do not begin the next phase automatically.
