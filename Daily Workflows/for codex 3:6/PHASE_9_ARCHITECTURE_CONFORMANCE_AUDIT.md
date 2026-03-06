# PHASE 9 --- ARCHITECTURE CONFORMANCE AUDIT

Objective: verify that the current DoorDrill implementation follows the
system structure, boundaries, and data flow defined in `architecture.md`.

Why this phase exists:

- `ARCHITECTURE_CONFORMANCE.md` currently covers a narrow slice of the
  backend contract.
- `architecture.md` defines a much broader system: mobile app, real-time
  voice gateway, conversation engine, grading engine, data layer, REST
  API, and folder structure.
- Before deeper simulation work, Codex should verify whether the current
  implementation still matches that intended architecture or has drifted
  into ad hoc patterns.

Primary source documents:

- `architecture.md`
- `ARCHITECTURE_CONFORMANCE.md`
- `PHASE_GAP_ANALYSIS_20260306.md`
- `MANAGEMENT_GAP_EXECUTION_PLAN.md`
- `for codex 3:6/PHASE_1_SYSTEM_DISCOVERY.md`

Primary code areas to audit:

- `backend/app/api`
- `backend/app/services`
- `backend/app/voice`
- `backend/app/tasks`
- `backend/app/models`
- `mobile/src`
- `dashboard/src`
- `scenarios/`

Codex Instructions:

Read `architecture.md` section by section and map each expected
architectural responsibility to the actual implementation.

Audit these architecture domains:

1. Mobile app structure
2. Real-time voice pipeline and interruption handling
3. Conversation engine and prompt construction
4. Persona and scenario modeling
5. Grading engine and post-session pipeline
6. Data layer and storage boundaries
7. REST API surface and RBAC boundaries
8. Task queue / async execution path
9. Folder structure and module ownership
10. Analytics and manager visibility paths as they relate to the core
    architecture

For each domain, determine:

- implemented as designed
- implemented but structurally different
- partially implemented
- missing
- implemented in the wrong layer

Required outputs:

Create:

`ARCHITECTURE_CONFORMANCE_FULL_AUDIT.md`

Also update if necessary:

`ARCHITECTURE_CONFORMANCE.md`

The full audit must include:

- an architecture conformance matrix by subsystem
- exact file references for each finding
- a "designed vs actual" comparison for every major component
- a list of boundary violations
- a list of duplicated responsibilities
- a list of dead or misleading architecture assumptions in
  `architecture.md`
- a remediation sequence ordered by risk and dependency

Required audit method:

1. Build a subsystem inventory from `architecture.md`.
2. Build an implementation inventory from the repo.
3. Compare expected ownership vs actual ownership.
4. Identify whether each architectural rule is respected.
5. Classify every gap as:
   - doc drift
   - implementation drift
   - missing implementation
   - acceptable evolution
6. Propose the smallest safe remediation for each high-impact gap.

Specific questions Codex must answer:

- Is the voice pipeline still separated cleanly from conversation logic?
- Has conversation orchestration stayed deterministic enough for
  training use?
- Are persona/scenario responsibilities encoded in the right place?
- Does post-session grading remain asynchronous and isolated from live
  conversation latency?
- Do manager analytics read from derived data rather than raw session
  data on hot paths?
- Is RBAC enforced at API and UI entry points, not just implied?
- Does the current folder structure reflect the intended domain
  boundaries, or has logic collapsed into oversized services?
- Which parts of `architecture.md` are now obsolete and should be
  rewritten to match reality?

Acceptance criteria:

- Every major section of `architecture.md` is explicitly addressed.
- Every conclusion is backed by repo file references.
- The audit distinguishes code gaps from documentation gaps.
- The output is actionable enough that a follow-up Codex run can execute
  the remediation sequence directly.

Do not do in this phase:

- do not rewrite large subsystems yet
- do not invent a new architecture without first documenting drift
- do not mark a section compliant based only on endpoint existence
- do not ignore mobile, dashboard, or scenario assets just because the
  existing conformance doc is backend-heavy

Success condition:

At the end of this phase, we should know whether DoorDrill is actually
following the architecture we say it has, where it is stronger than the
original design, and where structural cleanup is required before the
homeowner simulator work expands the system further.
