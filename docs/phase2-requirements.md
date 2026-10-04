# AI Project Control Center — Phase 2 Requirements

> Workspace/Storage 위치와 기존 데이터 호환성은 [Workspace/Storage 요구사항](control-center-workspace-storage-requirements.md)을 우선 적용한다. Workflow/DAG/Output Contract/Publish 기능은 유지한다.

## 1. Phase 2 Goal

Phase 2의 목표는 Phase 1에서 구축한 단일 Codex 실행 구조를 확장하여,
여러 AI 작업을 하나의 Workflow로 정의하고 병렬/순차 실행하며,
각 Task의 결과 Artifact를 다음 Task에 명시적으로 전달하는 것이다.

핵심 목표:

> 사용자가 한 화면에서 여러 Task를 정의하고 Dependency를 설정하면,
> Control Center가 여러 Codex Thread/Turn을 자동 실행하고
> 결과 Artifact를 연결해 최종 결과물까지 생성해야 한다.

Phase 2에서는 Control Center가 Workflow와 Task 상태를 관리한다.
Codex 자체의 native subagent 기능은 선택적 확장으로 남기며,
핵심 Workflow 실행은 Control Center Managed 방식으로 구현한다.

---

## 2. Preconditions

Phase 2는 Phase 1의 다음 기능이 정상 동작하는 것을 전제로 한다.

- Category / Work
- Source / Context
- Request / Run
- Codex Gateway
- ChatGPT 계정 기반 Codex 인증
- Model / Reasoning 선택
- Thread / Turn 실행
- Streaming Event
- Steer
- Cancel
- Resume
- Artifact 등록
- Artifact Preview
- Context Manifest
- Run History

기존 Phase 1의 단일 Request / Run 기능은 Phase 2 이후에도 그대로 사용할 수 있어야 한다.

---

## 3. Core Architecture

기본 구조:

```text
Web UI
  ↓
Workflow Service
  ↓
DAG Scheduler
  ↓
Task Runner
  ↓
기존 Run Service / Codex Gateway
  ↓
openai-codex Python SDK
  ↓
Codex App Server
```

Phase 2에서 새로운 AI Runtime을 만들지 않는다.

Task 실행은 가능한 한 Phase 1의 기존 Run / Codex Gateway 구조를 재사용한다.

---

## 4. Managed Workflow Mode

Phase 2의 기본 실행 방식은 Control Center Managed Workflow이다.

예:

```text
           ┌→ Task B ─┐
Task A ────┤           ├→ Task D
           └→ Task C ─┘
```

Control Center가 직접 다음을 관리한다.

- Task Dependency
- READY / BLOCKED 상태
- 병렬 실행
- Task별 Model / Reasoning
- Context
- Artifact Input / Output
- 실패 처리
- Retry
- Branch
- Workflow 완료 여부

Codex 자체 subagent orchestration에 핵심 상태 관리를 의존하지 않는다.

---

## 5. Workflow Definition

Workflow Definition은 반복 사용할 수 있는 작업 구조이다.

최소 필드:

- Workflow Definition ID
- Work ID 또는 Category
- Name
- Description
- Enabled
- Created At
- Updated At

Workflow Definition은 여러 Task Definition을 가진다.

예:

```text
사업제안서 작성

A. 초안 작성
B. 시장성 검토
C. 기술 검토
D. 최종 통합
```

---

## 6. Task Definition

Task Definition은 Workflow 내부의 하나의 작업 단위이다.

최소 필드:

- Task Definition ID
- Workflow Definition ID
- Name
- Instruction
- Runtime
- Model
- Reasoning
- Context Rule
- Input Rule
- Output Rule
- Workspace Mode
- Order / Display Order

Task는 영구 Persona 기반 Agent가 아니다.

Worker는 실행 시점의 다음 조합으로 본다.

```text
Task
+ Runtime
+ Model
+ Reasoning
+ Context
+ Permission
```

---

## 7. Workflow Run

Workflow Definition을 실행하면 새로운 Workflow Run을 생성한다.

최소 필드:

- Workflow Run ID
- Workflow Definition ID
- Work ID
- Status
- Started At
- Completed At
- Error
- Created At

기본 상태:

- CREATED
- RUNNING
- COMPLETED
- FAILED
- CANCELLED
- PARTIAL

과거 Workflow Run은 새로운 실행으로 덮어쓰지 않는다.

---

## 8. Task Run

Workflow Run 내부의 각 Task 실행은 별도의 Task Run으로 기록한다.

최소 필드:

- Task Run ID
- Workflow Run ID
- Task Definition ID
- Run ID
- Attempt Number
- Parent Task Run ID
- Status
- Started At
- Completed At
- Error

Task Run은 Phase 1의 Run과 연결된다.

예:

```text
TaskRun
  ↓
Run
  ↓
Codex Thread / Turn
```

---

## 9. Task State

최소 상태:

- BLOCKED
- READY
- QUEUED
- RUNNING
- COMPLETED
- FAILED
- CANCELLED
- SKIPPED

예:

```text
초기

A = READY
B = BLOCKED
C = BLOCKED
D = BLOCKED
```

A 완료 후:

```text
A = COMPLETED
B = READY
C = READY
D = BLOCKED
```

B/C 완료 후:

```text
D = READY
```

상태 전이는 Backend만 수행한다.

AI Worker가 Task 상태를 직접 변경하지 않는다.

---

## 10. Task Dependency

Task 간 Dependency는 명시적으로 저장한다.

예:

```text
B depends_on A
C depends_on A
D depends_on B, C
```

Dependency Graph는 Cycle을 허용하지 않는다.

Workflow 저장 또는 실행 전에 DAG 유효성을 검증한다.

Cycle이 있으면 Workflow 실행을 거부한다.

---

## 11. DAG Scheduler

DAG Scheduler는 일반 Python 로직으로 구현한다.

AI에게 Dependency 판단을 맡기지 않는다.

기본 책임:

1. BLOCKED Task의 Dependency 검사
2. 모든 선행 Task가 완료되면 READY 전환
3. READY Task를 실행 Queue에 등록
4. 병렬 실행 수 제한
5. 실패한 Dependency가 있을 경우 downstream 처리
6. 모든 Task 종료 시 Workflow Run 상태 결정

Phase 2에서는 복잡한 외부 Queue 시스템을 사용하지 않는다.

---

## 12. Parallel Execution

독립된 READY Task는 병렬 실행할 수 있어야 한다.

예:

```text
A 완료
  ↓
B + C 동시 실행
```

Python에서는 Phase 1의 AsyncCodex / async Run 구조를 재사용한다.

`max_parallel_tasks` 설정을 둔다.

예:

```text
max_parallel_tasks = 3
```

필요 이상으로 Codex 실행을 동시에 생성하지 않는다.

---

## 13. Artifact Input / Output

Task 간 전달은 명시적인 Artifact를 사용한다.

안 좋은 방식:

```text
다음 Worker가 폴더를 검색해서 이전 결과를 추측
```

좋은 방식:

```text
Task B Output
→ Artifact #201

Task C Output
→ Artifact #202

Task D Input
→ Artifact #201
→ Artifact #202
```

Task Definition은 Output 규칙을 가질 수 있다.

예:

```text
technical-review.md
```

Task Run 완료 시 실제 생성된 Artifact를 검증하고 등록한다.

---

### 13.1 Task Output Contract

Task는 다음 Task에 전달할 결과물을 명시적으로 정의할 수 있어야 한다.

예:

Task A — Architecture Design

Model:
GPT-6 Astra

Required Output:
- phase2-implementation-plan.md

Task가 완료되었다고 응답하더라도
필수 Output Artifact가 실제로 생성되지 않았다면
정상 완료로 처리하지 않는다.

Backend는 Task 종료 시 다음을 확인한다.

- 필수 Artifact 존재 여부
- 등록 가능 여부
- Artifact를 생성한 Task Run
- 실제 경로 / Location
- 후속 Task에 전달 가능한 상태인지

예:

Astra
↓
phase2-implementation-plan.md
↓
Artifact 등록
↓
Task A COMPLETED

## 14. Artifact Handoff

Downstream Task 실행 시 Input Artifact를 명시적으로 Context에 포함한다.

예:

```text
Task D

Input:
- market-review.md
- technical-review.md
```

Execution Compiler는 실제 Artifact 경로와 metadata를 바탕으로
Task 실행 Context를 구성한다.

Artifact Handoff는 Chat History의 기억에 의존하지 않는다.

---

## 15. Artifact Lineage

Artifact 간 입력/출력 관계를 저장한다.

예:

```text
draft.md
  ├→ market-review.md
  └→ technical-review.md

market-review.md ─┐
technical-review.md ─┤
                  ↓
              final.md
```

최소 관계:

- INPUT
- DERIVED_FROM
- REVISION_OF

Phase 2 UI에서 복잡한 Graph 시각화는 필수가 아니지만,
Backend에서는 Lineage를 추적할 수 있어야 한다.

---

## 16. Context Manifest

각 Task Run은 실제로 사용한 Context를 기록한다.

Context Manifest에는 최소 다음을 포함한다.

- Work Context
- 사용자가 선택한 Context
- Input Artifact
- Source Task
- 파일 Hash
- Run ID

향후 재현성과 Artifact Lineage를 위해 저장한다.

---

### 14.1 Model-to-Model Handoff

서로 다른 Model / Thread 사이의 Task 전달은
이전 Conversation History 공유에 의존하지 않는다.

예:

Task A
Model: GPT-6 Astra

Output:
phase2-implementation-plan.md

        ↓ Task A 완료

Task B
Model: GPT-6 Luna

Input:
phase2-implementation-plan.md

Instruction:
전달받은 구현 설계도를 기준으로 구현한다.

## 17. Workspace Mode

Task는 작업 성격에 따라 Workspace Mode를 선택할 수 있다.

### ARTIFACT_ONLY

문서, 조사, 분석처럼 기존 파일을 읽고
별도의 Artifact를 생성하는 작업.

기본적으로 Task별 output 영역을 분리한다.

### GIT_WORKTREE

같은 Git Repository에서 여러 Coding Task를 병렬 실행할 때 사용한다.

각 Task에 별도의 Git Worktree를 생성해 파일 충돌을 줄인다.

예:

```text
worktrees/
├── workflow17-taskB/
└── workflow17-taskC/
```

Phase 2에서는 복잡한 자동 Merge는 필수 요구사항이 아니다.

---

## 18. Retry

실패한 Task Run을 다시 실행할 수 있어야 한다.

기존 Task Run을 다시 RUNNING 상태로 변경하지 않는다.

예:

```text
Task C
├── Attempt 1 → FAILED
└── Attempt 2 → COMPLETED
```

Retry는 새로운 Task Run과 새로운 Run을 생성한다.

과거 실패 이력은 유지한다.

---

## 19. Branch

Branch는 기존 결과를 보존하면서 다른 방향의 실행을 만드는 기능이다.

예:

```text
proposal-v1.md
├→ 기술 중심 Branch
└→ 사업성 중심 Branch
```

가능한 경우 Codex SDK의 Thread Fork 기능을 활용한다.

Branch 실행은 새로운 Run / Task Run / Artifact를 생성한다.

원본 결과를 덮어쓰지 않는다.

---

## 20. Shared Library

Phase 2에서는 Work 내부 Artifact를 다른 Work에서 재사용할 수 있는 Shared Library를 추가한다.

Artifact Scope:

- WORK
- CATEGORY
- GLOBAL

기본 동작:

```text
Artifact
  ↓
[Library에 등록]
  ↓
Scope 선택
```

Phase 2에서는 사용자가 직접 Publish하는 방식만 구현한다.

자동 Publish, Publish Approval, Governance는 Phase 3로 넘긴다.

---

## 21. Library Context

다른 Work에서 PUBLISHED Artifact를 Context로 선택할 수 있어야 한다.

예:

```text
Context

Work
☑ 현재 architecture.md

Category Library
☑ coding-principles.md

Global Library
☐ writing-style.md
```

모든 Shared Artifact를 자동으로 Context에 넣지 않는다.

사용자가 선택하거나 명시적인 Task Input으로 지정한 자료만 사용한다.

---

## 22. Workflow Template

사용자는 만들어둔 Workflow Definition을 Template으로 재사용할 수 있어야 한다.

예:

```text
사업제안서 Workflow
- 초안
- 시장성 검토
- 기술 검토
- 통합
```

다른 Work에서 Template을 복제하여 사용할 수 있다.

Template 복제 후 Model / Instruction / Context를 수정할 수 있다.

---

## 23. Codex Skills / Agents Relation

Control Center Workflow와 Codex Skill / Custom Agent는 서로 다른 개념으로 유지한다.

```text
Control Center Workflow
= 여러 Task의 실행 Graph

Codex Skill
= 하나의 AI가 특정 작업을 수행하는 방법

Custom Agent
= Codex 내부 Delegated Multi-Agent용 설정
```

Phase 2의 핵심 Managed Workflow는 Codex Skill이나 Custom Agent가 없어도 동작해야 한다.

향후 Workflow Template을 Skill로 Export하거나
Delegated Mode와 연동할 수 있는 확장 지점만 남긴다.

---

## 24. Delegated Multi-Agent Mode

Codex native subagent 기능은 Phase 2의 필수 실행 경로가 아니다.

향후 선택적 실행 모드로 확장 가능하게 한다.

예:

```text
Execution Mode

MANAGED
DELEGATED
```

### MANAGED

Control Center가 Task / Dependency / Artifact를 직접 관리한다.

### DELEGATED

하나의 Codex Thread에 목표를 전달하고
Codex가 내부 subagent를 생성하도록 위임한다.

Phase 2 MVP에서는 MANAGED Mode를 우선 구현한다.

---

## 25. Events

Workflow / Task 상태도 Phase 1의 Event 구조를 확장하여 전달한다.

최소 Event:

- WORKFLOW_STARTED
- WORKFLOW_COMPLETED
- WORKFLOW_FAILED
- TASK_BLOCKED
- TASK_READY
- TASK_STARTED
- TASK_COMPLETED
- TASK_FAILED
- TASK_CANCELLED
- ARTIFACT_HANDOFF
- ARTIFACT_CREATED
- BRANCH_CREATED
- RETRY_CREATED

Frontend가 Codex Raw Protocol을 직접 해석하지 않는다.

---

## 26. Workflow UI

Phase 2에서는 복잡한 Drag & Drop Canvas를 필수로 하지 않는다.

최소 UI:

```text
사업제안서 Workflow

1. 초안 작성
   GPT-6 Astra / High
   READY

2. 시장성 검토
   depends on: 1
   BLOCKED

3. 기술 검토
   depends on: 1
   BLOCKED

4. 최종 통합
   depends on: 2, 3
   BLOCKED

[+ Task]
[Workflow 실행]
```

Task 편집 UI에서는 최소 다음을 설정할 수 있어야 한다.

- Name
- Instruction
- Model
- Reasoning
- Context
- Depends On
- Input Artifact
- Output Rule
- Workspace Mode

---

## 27. Workflow Run UI

Workflow 실행 중 다음을 한 화면에서 확인할 수 있어야 한다.

- Workflow Status
- Task별 Status
- 현재 실행 중 Task
- 병렬 실행 Task
- Task별 Model / Reasoning
- Task별 Run
- 생성 Artifact
- 실패 정보
- Retry
- Branch

예:

```text
✓ 초안 작성

● 시장성 검토
● 기술 검토

🔒 최종 통합
```

---

## 28. Failure Handling

선행 Task가 실패하면 기본적으로 downstream Task는 실행하지 않는다.

예:

```text
B FAILED
D depends_on B, C

→ D BLOCKED
```

사용자는 다음을 선택할 수 있다.

- B Retry
- B Cancel
- Workflow Cancel

Phase 2에서는 복잡한 자동 대체 경로는 구현하지 않는다.

---

## 29. Concurrency Safety

동일 Artifact를 여러 Task가 동시에 덮어쓰지 않도록 한다.

기본 정책:

- Artifact는 Immutable에 가깝게 관리
- 기존 Artifact 수정 대신 새 Artifact 생성
- 병렬 Task는 별도 Output Path 사용
- 코드 수정 병렬화 시 Git Worktree 사용

Control DB는 AI Worker가 직접 수정하지 않는다.

---

## 30. Database Extension

Phase 1 DB에 최소 다음 Entity를 추가한다.

- WorkflowDefinition
- TaskDefinition
- TaskDependency
- WorkflowRun
- TaskRun
- ArtifactRelation
- WorkflowTemplate

기존:

- Category
- Work
- Request
- Run
- Artifact
- Event

는 유지한다.

---

## 31. Out of Scope

Phase 2에서는 다음을 구현하지 않는다.

- Human Approval Gate
- Approval Inbox
- Revision Approval Flow
- 예약 실행
- 반복 Schedule
- Delayed Resume
- Notification
- AI Reviewer 자동 Pipeline
- Publish Governance
- Natural Language Goal → Workflow 자동 생성
- Automatic Model Routing
- Vector DB
- Semantic Search
- Remote Worker
- Distributed Queue
- Team Collaboration
- Complex Workflow Canvas
- 자동 Git Merge

이 기능들은 Phase 3 이후로 넘긴다.

---

## 32. Representative Workflow

Work:

```text
AI IP Studio
```

Workflow:

### Task A — Draft

```text
Instruction:
AI IP Studio 사업제안서 초안을 작성한다.

Model:
GPT-6 Astra

Reasoning:
High

Output:
proposal-draft.md
```

### Task B — Market Review

```text
depends_on:
Task A

Input:
proposal-draft.md

Instruction:
시장성과 사업성 관점에서 검토한다.

Output:
market-review.md
```

### Task C — Technical Review

```text
depends_on:
Task A

Input:
proposal-draft.md

Instruction:
기술 구현 가능성과 Architecture를 검토한다.

Output:
technical-review.md
```

Task B와 Task C는 병렬 실행한다.

### Task D — Integration

```text
depends_on:
Task B
Task C

Input:
proposal-draft.md
market-review.md
technical-review.md

Instruction:
세 결과를 바탕으로 하나의 일관된 최종 제안서를 작성한다.

Output:
final-proposal.md
```

전체 흐름:

```text
A
↓
B + C
↓
D
↓
final-proposal.md
```

---

## 33. Acceptance Criteria

Phase 2 완료를 주장하기 전에 최소 다음을 실제 검증한다.

1. Workflow Definition을 생성할 수 있다.
2. 여러 Task Definition을 추가할 수 있다.
3. Task Dependency를 설정할 수 있다.
4. Cycle이 있는 Workflow 실행을 거부한다.
5. Workflow Run을 생성할 수 있다.
6. 각 Task에 Task Run이 생성된다.
7. Dependency 없는 Task가 READY가 된다.
8. Dependency 미완료 Task는 BLOCKED 상태를 유지한다.
9. 독립 Task 두 개 이상을 실제 병렬 실행할 수 있다.
10. `max_parallel_tasks` 제한이 동작한다.
11. 각 Task가 Phase 1 Run / Codex Gateway를 재사용한다.
12. Task별 Model / Reasoning 설정이 실제 실행에 반영된다.
13. Task Output Artifact가 실제 등록된다.
14. downstream Task가 명시된 Artifact를 Input으로 받는다.
15. Artifact Lineage를 조회할 수 있다.
16. 선행 Task 실패 시 downstream Task가 실행되지 않는다.
17. 실패 Task Retry 시 과거 Task Run이 보존된다.
18. Retry 결과가 새로운 Task Run으로 생성된다.
19. Branch가 기존 결과를 보존한다.
20. 가능한 경우 Codex Thread Fork를 이용해 Branch를 생성할 수 있다.
21. 병렬 문서 Task가 서로의 Artifact를 덮어쓰지 않는다.
22. Git Worktree Mode에서 병렬 Coding Task를 격리할 수 있다.
23. Artifact를 WORK / CATEGORY / GLOBAL Scope로 Publish할 수 있다.
24. 다른 Work에서 Published Artifact를 Context로 선택할 수 있다.
25. Workflow Definition을 Template으로 재사용할 수 있다.
26. Workflow / Task 상태가 Web UI에 실시간 표시된다.
27. 대표 A → B/C → D Workflow가 End-to-End로 성공한다.
28. 기존 Phase 1 단일 Request / Run 기능이 정상 동작한다.
29. AI Worker가 control.db를 직접 수정하지 않는다.
30. 최종 docs/architecture.md가 실제 Phase 2 구현과 일치한다.

---

## 34. Phase 2 Completion Definition

Phase 2는 단순히 여러 Codex 실행을 동시에 띄우는 것으로 완료되지 않는다.

다음 전체 흐름이 실제로 안정적으로 동작해야 한다.

```text
Workflow Definition
  ↓
Task Dependency
  ↓
DAG Scheduler
  ↓
Parallel Codex Runs
  ↓
Explicit Artifact Output
  ↓
Artifact Handoff
  ↓
Downstream Task
  ↓
Final Artifact
  ↓
History / Retry / Branch
```

그리고 다음 구조가 실제로 검증되어야 한다.

```text
A
├→ B ─┐
└→ C ─┤
       ↓
       D
```

B와 C가 실제 병렬 실행되고,
D가 B/C의 실제 Artifact를 명시적으로 Input으로 받아 실행되며,
기존 Phase 1 단일 실행 기능에 Regression이 없어야 Phase 2 완료로 본다.
