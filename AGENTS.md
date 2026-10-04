# AI Control Center Agent Instructions

## Project purpose

AI Control Center is a local Agent Control Plane.

The system manages:

- Work / Workspace
- Request / Run
- Workflow / Task
- Artifact / Material
- Thread / Context
- Schedule / Queue
- Review / Approval
- Runtime / Gateway

The Control Center owns orchestration, state, workflow, context,
artifacts, permissions, scheduling, and execution intent.

Agent runtimes perform actual execution.

Do not treat this repository as only a UI around Codex.

---

# 1. Mandatory requirement classification

For every non-trivial request, BEFORE modifying code,
you MUST classify the request into all affected system layers.

Possible layers:

1. Frontend / UX
2. Backend / API
3. Data / Database
4. Workflow / Orchestration
5. Context / Materials / Artifacts
6. Gateway / Runtime Adapter
7. SDK / Agent Runtime
8. Filesystem / Git / Infrastructure
9. Permission / Security
10. Observability / Operations

Only include layers actually affected by the request.

A request may affect one layer or multiple layers.

Do NOT assume that a user request is a Frontend request
just because it is described through UI behavior.

The user's intended final behavior determines the affected layers.

---

# 2. Mandatory requirement documents

After classifying the affected layers,
you MUST read every requirement document mapped to those layers
BEFORE implementation.

Required mapping:

## Frontend / UX
MUST read:

`docs/requirements/frontend.md`

## Backend / API
MUST read:

`docs/requirements/backend.md`

## Data / Database
MUST read:

`docs/requirements/data.md`

## Workflow / Orchestration
MUST read:

`docs/requirements/workflow.md`

## Context / Materials / Artifacts
MUST read:

`docs/requirements/context-artifact.md`

## Gateway / Runtime Adapter
MUST read:

`docs/requirements/runtime-sdk.md`

## SDK / Agent Runtime
MUST read:

`docs/requirements/runtime-sdk.md`

## Filesystem / Git / Infrastructure
MUST read:

`docs/requirements/infrastructure-filesystem.md`

## Permission / Security
MUST read:

`docs/requirements/permission-security.md`

## Observability / Operations
MUST read:

`docs/requirements/observability.md`

For significant cross-layer features or architectural changes,
you MUST also read:

`docs/architecture.md`

Do NOT skip a mapped requirement document because you believe
you already understand the subsystem.

Do NOT begin implementation before the required documents
for every affected layer have been read.

If a required document does not exist,
do not silently invent its requirements.
Identify the missing requirement document and use the current
implementation and architecture only to diagnose the gap.

---

# 3. Mandatory cross-layer requirement definition

If a request affects more than one layer,
you MUST define what each affected layer must provide
before modifying code.

Keep this concise.

Example user request:

"Allow a Work to use an external local folder."

Required interpretation:

Frontend
- allow the user to select and inspect the external root
- show the real configured capability/state

Backend
- register, validate, resolve, and expose the root

Data
- persist the root and its scope

Workflow / Run
- snapshot the selected scope for execution

Gateway
- translate the Run scope into Runtime configuration

SDK / Runtime
- actually receive and use the requested filesystem scope

Filesystem
- make the path genuinely accessible to the Agent process

Permission
- enforce or accurately represent the real access boundary

E2E
- start a real Run
- read a known file
- verify the returned content

A cross-layer feature MUST NOT be implemented as a single-layer
feature when other layers are required for the intended behavior.

---

# 4. Frontend requirements

For requests involving Frontend / UX,
the implementation MUST identify:

- the user action
- the information the user needs
- the backend action caused by the UI
- the real state that must be displayed
- failure and unavailable states when relevant

Frontend state MUST represent actual system state.

Do NOT:

- create controls for capabilities that do not exist
- simulate successful backend/runtime behavior
- treat UI state as proof of runtime capability
- solve a backend/runtime defect with Frontend-only changes

A successful UI interaction is sufficient only for a genuinely
Frontend-only requirement.

---

# 5. Backend requirements

For requests involving Backend / API,
the implementation MUST consider:

- request/response contract
- validation
- service/domain behavior
- persistence when required
- errors
- connection to downstream layers

Do NOT treat an API response as the final success condition
when the requested feature requires further execution.

Example:

HTTP 200 from `POST /run`

does NOT prove success if the requested execution configuration
never reaches the Runtime.

---

# 6. Data requirements

When persistent state is required,
determine:

- which entity owns the state
- whether it is mutable configuration
- whether it must become an immutable Run snapshot
- revision/version behavior
- lineage where outputs or artifacts are produced

Reuse existing ownership and entities where appropriate.

Do NOT introduce duplicate state merely because it is convenient
for a new UI or API.

---

# 7. Workflow requirements

For Workflow-related changes,
distinguish between:

- Workflow Definition
- Workflow Revision
- Workflow Run
- Task
- Task Attempt
- Dependency
- Input
- Output

`depends_on` controls when a Task may execute.

Input/output rules control what data is transferred.

Do NOT assume that a dependency automatically transfers
the predecessor's result.

For cross-task data transfer, verify the actual path:

Task A
→ actual output / Artifact
→ resolver
→ Task B input
→ Task B actual Run

---

# 8. Context / Material / Artifact requirements

Material or Artifact registration is NOT the same thing
as Runtime Context injection.

A selected Material or Artifact does not automatically mean
its entire content should be injected into the model Context.

Prefer:

Material / Artifact
→ ID / path / metadata
→ runtime-accessible reference
→ retrieve/read only when needed

Avoid injecting large documents or artifacts wholesale
unless the task explicitly requires it.

When Context, Material, or Artifact behavior changes,
verify what the actual Run receives.

Do NOT infer successful Context delivery from UI selection
or database registration.

---

# 9. Mandatory Runtime / SDK verification

Any request involving any of the following:

- filesystem access
- workspace roots
- external roots
- model settings
- web access
- permissions
- Git worktrees
- thread/history
- resume
- fork
- steer
- Runtime capabilities

MUST be verified against the actually installed:

- Gateway
- Runtime Adapter
- SDK
- Agent Runtime

Do NOT infer Runtime capability from:

- desired product behavior
- UI controls
- database fields
- API models
- prompt instructions

Trace the real execution path:

Control Center configuration
→ Run snapshot
→ Gateway
→ Runtime Adapter
→ SDK
→ Agent Runtime
→ observed behavior

Before declaring a Runtime capability supported or unsupported,
you MUST inspect the installed implementation or perform
the smallest direct capability test practical.

If the requested capability is unavailable,
do NOT build UI that implies it works.

If an alternative implementation changes the semantics
of the user's requirement, report that difference before
treating it as the requested feature.

---

# 10. Filesystem / Git / Infrastructure requirements

If a feature depends on filesystem, process, sandbox,
workspace, or Git behavior,
verify actual operating-system-visible behavior.

Examples:

A path stored in the database
does NOT prove the Agent can read it.

A permission value in the UI
does NOT prove the Runtime enforces it.

A Git worktree database record
does NOT prove the worktree exists or is usable.

A prompt telling the model not to read a path
is NOT filesystem permission enforcement.

Use the actual filesystem / Git / process behavior
as the completion condition where the requirement depends on it.

---

# 11. Permission requirements

Always distinguish:

1. intended permission
2. stored permission
3. Runtime permission
4. actually enforced permission

These are not automatically equivalent.

Prompt instructions, UI labels, search filters,
or `.gitignore` rules are NOT security boundaries.

If strong access control is required,
verify the actual Runtime / Sandbox / OS enforcement boundary.

If the current Runtime cannot provide that guarantee,
represent the real guarantee accurately.

Do NOT present stronger permission guarantees than
the system actually enforces.

---

# 12. Observability requirements

When execution state matters,
the system should expose enough real state to determine:

- what was requested
- what was executed
- whether execution succeeded or failed
- where a failure occurred when practical

Do not replace actual execution state with UI assumptions.

Keep raw/debug information secondary unless it is required
to diagnose the current problem.

---

# 13. Mandatory completion rule

A feature is complete only when ALL affected layers
required by the user's intended behavior are connected.

For a multi-layer feature, the expected path may be:

User action
→ Frontend
→ API
→ Data / Domain
→ Workflow / Run snapshot
→ Gateway
→ Runtime Adapter
→ SDK
→ Agent Runtime
→ actual observable behavior

Not every feature requires every layer.

However, every layer identified as required MUST function
as part of the same End-to-End path.

Do NOT mark a feature complete merely because:

- the UI exists
- the API succeeds
- a database record exists
- configuration is persisted
- an Artifact exists
- a Workflow is published
- individual components work independently

Completion is determined by the user's intended final behavior.

---

# 14. Mandatory End-to-End verification

Prefer one representative End-to-End verification
over many disconnected tests.

For normal changes:

1. reproduce or identify the intended user flow
2. execute that flow through all affected layers
3. verify the actual final behavior
4. stop when the requirement has been demonstrated

Example:

User selects external folder
→ backend stores it
→ Run snapshots it
→ Gateway resolves it
→ Runtime receives it
→ Agent reads a known file
→ returned content proves actual access

This is preferable to many tests that never exercise
the complete requested behavior.

Additional checks should be added only where needed for:

- migrations
- destructive operations
- security boundaries
- permission enforcement
- concurrency-sensitive behavior
- irreversible data changes

Use the minimum sufficient verification.

---

# 15. Scope discipline

Implement all layers required by the user's actual goal,
but do not expand into unrelated work.

Do NOT:

- modify Backend for a purely visual request
- solve Runtime problems with Frontend-only changes
- add new infrastructure when existing infrastructure is sufficient
- redesign unrelated components
- introduce speculative abstractions unrelated to the current requirement

Fix the root cause across the required layers.

Keep unrelated behavior unchanged.

"Smallest change" does not mean a local patch that leaves
the actual root cause unresolved.

---

# 16. User-facing UI

User-facing UI should use Korean unless otherwise required.

Prefer:

- compact information density
- clear hierarchy
- clear primary actions
- management actions separated from execution actions
- actual state rather than intended/configured state
- advanced/debug information collapsed by default

The UI must expose the real capability and execution state
of the underlying system.

---

# 17. Core development rule

For every non-trivial request, answer these questions
before implementation:

1. What is the user actually trying to accomplish?
2. Which system layers are affected?
3. Which requirement documents are mandatory for those layers?
4. What must each affected layer provide?
5. How do those layers connect?
6. What actual observable result proves the feature works?

Implementation is complete only when that End-to-End result
has been demonstrated.

If the affected layers have not been classified,
their mapped requirement documents have not been read,
or the End-to-End completion condition has not been identified,
implementation MUST NOT begin.