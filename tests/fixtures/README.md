# R13 fixture foundation — PARTIAL

All builders accept a caller-owned Session and never commit, delete or invoke a provider. UUID5 namespaces distinguish tests; NOW is fixed. Question inserts go through the original before_flush version hook. Never UPDATE version pointers or synthesize formal verification. Tests that require verified public questions must use existing domain review services and assert eligibility; the generic builder does NOT supply that certification.

NaiwaFactory supports tree/question/personal question/plan/item/attempt/chat/message. create_test_user is explicitly a synthetic installation actor, not a persisted account: no User entity exists in the current domain. No permission claims follow from it.

pg63047.rollback_factory validates live database identity and revision before yielding savepoint factories, then rolls back the outer transaction. It performs no migration/initdb/cleanup. It is serial on one connection; actual race tests need separate connections and domain locks. DailyPlan.study_date is globally unique and namespaces do not isolate same-day plans. Do not run these on the same DB concurrently without explicit isolation/serialization.

Not yet implemented/verified: formal review and unsupported/untrusted scenario builders, personal generation batch/service persistence, planner requests, event/mastery fixture scenarios, original 44-case fixture adoption and real PG readback. Live 63047 TCP access is blocked in this execution environment. These files are not proof that P0/P1 are complete.

Offline contract command: python -m pytest --confcutdir=tests/fixtures/contract_checks tests/fixtures/contract_checks
The local conftest denies Engine.connect; excluding the parent migration fixture is limited to this pure contract subtree and never used to claim PG acceptance.
