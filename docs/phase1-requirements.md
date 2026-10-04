# AI Project Control Center — Phase 1 Requirements

## 1. Phase 1 Goal

Phase 1의 목표는 로컬 파일과 프로젝트를 관리하면서,
공식 Codex Python SDK / App Server를 통해 하나의 AI 작업을
웹 UI에서 안정적으로 실행하고 결과를 Artifact로 관리하는 것이다.

핵심 목표:

> 사용자는 터미널이나 Codex CLI 명령어를 직접 다루지 않고,
> Work를 선택하고 자연어 작업을 요청한 뒤
> 실행 상태와 결과물을 한 화면에서 관리할 수 있어야 한다.

Phase 1에서는 Multi Worker, Workflow DAG, Approval, Scheduling은 구현하지 않는다.

---

## 2. Core Architecture

기본 구조는 다음과 같다.

```text
Web UI
  ↓ HTTP / SSE
FastAPI Backend
  ↓
Codex Gateway
  ↓
openai-codex Python SDK
  ↓
Codex App Server
  ↓
Codex Runtime
```

Control Center는 Codex 자체를 재구현하지 않는다.

Codex가 제공하는 다음 기능은 SDK / App Server를 우선 사용한다.

- Thread 생성
- Turn 실행
- Streaming Event
- Model 선택
- Reasoning 선택
- 실행 중 추가 Instruction
- Interrupt / Cancel
- Thread Resume
- Model Capability 조회

`codex exec` subprocess 직접 호출은 기본 실행 경로로 사용하지 않는다.
필요한 경우 진단 또는 fallback 용도로만 고려한다.

---

## 3. Authentication

Phase 1의 기본 인증 방식은 ChatGPT 계정 로그인이다.

목표:

```text
Control Center
  ↓
Codex SDK
  ↓
기존 Codex / ChatGPT 로그인 세션
```

요구사항:

- 기존 Codex 로그인 상태가 있으면 재사용
- 로그인되지 않은 경우 ChatGPT 로그인 흐름 제공
- API Key 입력을 기본 요구사항으로 만들지 않음
- API Key 방식은 향후 선택 기능으로 확장 가능하게 설계

UI에서는 최소 다음 상태를 보여준다.

```text
OpenAI Account
Connected / Disconnected
```

---

## 4. Local Workspace

사용자의 데이터는 로컬 파일 시스템에 저장한다.

기본 예시:

```text
data/
├── global/
│   └── library/
│
└── categories/
    └── coding/
        ├── knowledge/
        └── works/
            └── 0001_control-center/
                ├── sources/
                ├── context/
                ├── artifacts/
                ├── decisions/
                └── work.json
```

Phase 1에서 최소 지원:

- Category
- Work
- Source
- Context
- Artifact

---

## 5. Category

Category는 Work를 분류하는 상위 단위이다.

예:

```text
Coding
Research
Job
Presentation# AI Project Control Center — Phase 1 Requirements

## 1. Phase 1 Goal

Phase 1의 목표는 로컬 파일과 프로젝트를 관리하면서,
공식 Codex Python SDK / App Server를 통해 하나의 AI 작업을
웹 UI에서 안정적으로 실행하고 결과를 Artifact로 관리하는 것이다.

핵심 목표:

> 사용자는 터미널이나 Codex CLI 명령어를 직접 다루지 않고,
> Work를 선택하고 자연어 작업을 요청한 뒤
> 실행 상태와 결과물을 한 화면에서 관리할 수 있어야 한다.

Phase 1에서는 Multi Worker, Workflow DAG, Approval, Scheduling은 구현하지 않는다.

---

## 2. Core Architecture

기본 구조는 다음과 같다.

```text
Web UI
  ↓ HTTP / SSE
FastAPI Backend
  ↓
Codex Gateway
  ↓
openai-codex Python SDK
  ↓
Codex App Server
  ↓
Codex Runtime
```

Control Center는 Codex 자체를 재구현하지 않는다.

Codex가 제공하는 다음 기능은 SDK / App Server를 우선 사용한다.

- Thread 생성
- Turn 실행
- Streaming Event
- Model 선택
- Reasoning 선택
- 실행 중 추가 Instruction
- Interrupt / Cancel
- Thread Resume
- Model Capability 조회

`codex exec` subprocess 직접 호출은 기본 실행 경로로 사용하지 않는다.
필요한 경우 진단 또는 fallback 용도로만 고려한다.

---

## 3. Authentication

Phase 1의 기본 인증 방식은 ChatGPT 계정 로그인이다.

목표:

```text
Control Center
  ↓
Codex SDK
  ↓
기존 Codex / ChatGPT 로그인 세션
```

요구사항:

- 기존 Codex 로그인 상태가 있으면 재사용
- 로그인되지 않은 경우 ChatGPT 로그인 흐름 제공
- API Key 입력을 기본 요구사항으로 만들지 않음
- API Key 방식은 향후 선택 기능으로 확장 가능하게 설계

UI에서는 최소 다음 상태를 보여준다.

```text
OpenAI Account
Connected / Disconnected
```

---

## 4. Local Workspace

사용자의 데이터는 로컬 파일 시스템에 저장한다.

기본 예시:

```text
data/
├── global/
│   └── library/
│
└── categories/
    └── coding/
        ├── knowledge/
        └── works/
            └── 0001_control-center/
                ├── sources/
                ├── context/
                ├── artifacts/
                ├── decisions/
                └── work.json
```

Phase 1에서 최소 지원:

- Category
- Work
- Source
- Context
- Artifact

---

## 5. Category

Category는 Work를 분류하는 상위 단위이다.

예:

```text
Coding
Research
Job
Presentation
Stocks
```

최소 기능:

- Category 목록
- Category 생성
- Category 이름 수정
- Category 비활성화
- Category별 Work 조회

실제 데이터 삭제보다 비활성화를 기본으로 한다.

---

## 6. Work

Work는 하나의 장기 프로젝트 또는 문제 단위이다.

예:

```text
AI Project Control Center
AI IP Studio 사업제안서
한국도로공사 지원
```

Work 생성 시 로컬 디렉터리를 함께 생성한다.

예:

```text
0001_ai-project-control-center/
├── sources/
├── context/
├── artifacts/
├── decisions/
└── work.json
```

최소 기능:

- Work 생성
- Work 목록
- Work Detail
- Work 이름 / 설명 수정
- Work Archive
- Work 디렉터리 열람

---

## 7. Source / Context

Work에 사용자가 직접 자료를 추가할 수 있어야 한다.

예:

- Markdown
- Text
- PDF
- Image
- Source Code
- 기타 일반 파일

Phase 1에서는 복잡한 Semantic Search를 구현하지 않는다.

사용자는 AI Request를 실행할 때
어떤 Context를 사용할지 직접 선택할 수 있어야 한다.

예:

```text
Context
☑ phase1-requirements.md
☑ architecture.md
☐ old-notes.md
```

Control Center는 선택된 Context를
Codex 실행에 명시적으로 전달한다.

---

## 8. Request

Request는 사용자가 AI에게 전달하는 하나의 작업 의도이다.

예:

```text
현재 Architecture를 검토하고
비동기 상태 관리에서 문제가 될 부분을 찾아줘.
```

Request와 실제 실행 Run은 분리한다.

```text
Request
  ↓
Run #1
Run #2 (Retry)
Run #3 (Resume / Revision)
```

Phase 1에서는 최소:

- Request 생성
- Request History
- Request Detail
- Request에 사용한 Context 기록

을 지원한다.

---

## 9. Run

Run은 실제 Codex 실행 한 번을 의미한다.

Run은 최소 다음 정보를 가진다.

- Run ID
- Request ID
- Work ID
- Codex Thread ID
- Codex Turn ID
- Model
- Reasoning
- Started At
- Completed At
- Status
- Error
- Context Manifest
- 생성 Artifact

기본 상태:

```text
CREATED
RUNNING
COMPLETED
FAILED
CANCELLED
```

Phase 1에서는 Workflow Task 상태와 섞지 않는다.

---

## 10. Codex Gateway

Backend 내부에 Codex Gateway 계층을 둔다.

역할:

- SDK 초기화
- 인증 상태 확인
- Model 목록 조회
- Thread 생성
- Turn 실행
- Event Streaming
- Steer
- Interrupt
- Resume
- 오류 변환

다른 Service가 Codex SDK 세부 구현을 직접 사용하지 않도록 한다.

예:

```text
RequestService
  ↓
RunService
  ↓
CodexGateway
  ↓
AsyncCodex
```

---

## 11. Model / Reasoning

Model과 Reasoning 옵션은 가능하면 하드코딩하지 않는다.

Codex Runtime에서 제공하는 Model / Capability 정보를 조회하고
UI 선택지에 반영한다.

UI 예:

```text
Model
[GPT-6 Astra ▼]

Reasoning
[High ▼]
```

사용자가 선택하지 않은 경우
합리적인 기본값을 사용할 수 있다.

---

## 12. Execution

사용자가 Request를 실행하면:

```text
Request 생성
  ↓
Run 생성
  ↓
Codex Thread / Turn 생성
  ↓
Streaming Event 수신
  ↓
Artifact 생성
  ↓
Run 완료
```

HTTP 요청 자체가 AI 작업 완료까지 blocking 되어서는 안 된다.

실행 시작 요청은 빠르게 Run ID를 반환해야 한다.

---

## 13. Real-time Event

Codex App Server / SDK가 제공하는 구조화 Event를 활용한다.

Frontend가 Codex의 Raw Protocol을 직접 해석하지 않는다.

구조:

```text
Codex Event
  ↓
Codex Gateway
  ↓
Control Center Event
  ↓
Event Store
  ↓
SSE
  ↓
Web UI
```

Phase 1에서 최소 표준 Event:

- RUN_STARTED
- ACTIVITY
- COMMAND_STARTED
- COMMAND_COMPLETED
- FILE_CHANGED
- WARNING
- RUN_COMPLETED
- RUN_FAILED
- RUN_CANCELLED

숨겨진 Chain-of-Thought를 노출하지 않는다.

사용자에게 유용한 작업 상태만 표시한다.

---

## 14. Steer

실행 중 사용자가 추가 지시를 보낼 수 있어야 한다.

예:

```text
DB 정합성 문제를 우선해서 확인해.
```

Codex Runtime이 현재 Turn Steering을 지원하는 경우
SDK의 해당 기능을 사용한다.

UI 예:

```text
실행 중 추가 지시
[________________________________]
[보내기]
```

---

## 15. Cancel

실행 중 Run을 취소할 수 있어야 한다.

UI:

```text
[실행 취소]
```

Backend는 Codex Runtime의 Interrupt 기능을 사용하고
Run 상태를 `CANCELLED`로 정합성 있게 변경한다.

UI에서 단순히 RUNNING 표시만 제거하는 방식으로 구현하지 않는다.

---

## 16. Resume

과거 Codex Thread를 다시 이어서 실행할 수 있어야 한다.

예:

```text
어제 하던 Architecture 검토 계속하기
```

Phase 1에서는 최소한:

- 기존 Thread ID 저장
- Thread Resume
- 새 Run 생성
- 과거 Run History 유지

를 지원한다.

동일 Run을 다시 부활시키지 않고,
Resume 실행도 새로운 Run Record로 남기는 것을 기본으로 한다.

---

## 17. Artifact

Artifact는 AI 작업으로 생성된 실제 결과물이다.

예:

- Markdown
- Text
- Source Code
- JSON
- Image
- HTML
- 기타 파일

Artifact는 최소 다음 정보를 가진다.

- Artifact ID
- Work ID
- Run ID
- Path
- Name
- Type
- Created At
- Size
- Hash

Phase 1에서는 Artifact Publish / Global Sharing은 구현하지 않는다.

모든 Artifact는 기본적으로 해당 Work에 속한다.

---

## 18. Artifact Detection

가능하면 Codex App Server의 `fileChange` Event와
실제 파일 시스템 상태를 함께 활용한다.

AI가 생성했다고 주장한 파일이 실제 존재하는지 검증한 뒤
Artifact로 등록한다.

단순히 AI 최종 응답의 텍스트만 믿고 Artifact를 등록하지 않는다.

---

## 19. Artifact Preview

Web UI에서 최소 다음 Preview를 제공한다.

- Markdown
- Plain Text
- Source Code
- Image

지원하지 않는 파일은:

- 파일 정보 표시
- 로컬 경로 확인
- 열기 / 다운로드 가능한 방식

을 제공한다.

Phase 1에서는 복잡한 Office 문서 Viewer를 구현하지 않는다.

---

## 20. Context Manifest

각 Run에서 실제로 어떤 Context를 사용했는지 기록한다.

예:

```json
{
  "run_id": "run_001",
  "files": [
    {
      "path": "context/architecture.md",
      "hash": "..."
    },
    {
      "path": "context/phase1-requirements.md",
      "hash": "..."
    }
  ]
}
```

목적:

- 재현성
- 디버깅
- 추후 Artifact Lineage
- 향후 Workflow Handoff

Phase 1에서는 Vector DB를 사용하지 않는다.

---

## 21. Database

Control Plane 상태는 SQLite에 저장한다.

최소 Entity:

- Category
- Work
- Source
- Request
- Run
- Artifact
- Event

향후 확장을 위해 다음 Entity를 추가할 수 있는 구조로 설계한다.

- Workflow
- Task
- Approval
- Schedule

하지만 Phase 1에서는 해당 기능을 구현하지 않는다.

AI Worker는 `control.db`를 직접 수정하지 않는다.

DB 변경은 Backend만 수행한다.

---

## 22. AGENTS.md

Project / Work 수준의 불변 규칙은
Codex의 `AGENTS.md`를 활용할 수 있다.

예:

```text
- control.db를 직접 수정하지 않는다.
- artifacts 영역 외부에 결과 파일을 임의 생성하지 않는다.
- 기존 Artifact를 덮어쓰지 않는다.
- 테스트 실패 상태에서 완료라고 보고하지 않는다.
```

Task별 세부 Instruction을 AGENTS.md에 누적하지 않는다.

AGENTS.md는 프로젝트 운영 규칙에만 사용한다.

---

## 23. Security / Permissions

Phase 1에서는 최소 다음을 보장한다.

- AI Worker의 Control DB 직접 수정 금지
- 허용된 Work / Project Path 중심으로 실행
- Codex Sandbox Capability 활용
- Runtime Permission 요청과 일반 Workflow 상태를 분리
- Shell Command / File Change Event 기록

Runtime이 요청하는 Permission Approval을
향후 UI에서 처리할 수 있도록 확장 지점을 남긴다.

Phase 1에서는 복잡한 Permission Inbox는 필수 요구사항이 아니다.

---

## 24. UI Scope

Phase 1에서는 최소 다음 화면을 제공한다.

### Dashboard

- 최근 Work
- 최근 Run
- 실행 중 Run
- 최근 Artifact

### Category

- Category 목록
- Category 생성

### Work Detail

- Sources
- Context
- Requests
- Runs
- Artifacts

### Request / Run

- 자연어 Instruction
- Model
- Reasoning
- Context 선택
- 실행
- 실시간 상태
- 추가 지시
- Cancel

### Artifact

- 목록
- Detail
- Preview

복잡한 Workflow Canvas는 구현하지 않는다.

---

## 25. Recommended Technology

Phase 1 기본 기술:

```text
Backend
- Python
- FastAPI
- openai-codex Python SDK
- asyncio

Database
- SQLite
- SQLAlchemy
- Alembic

Schema
- Pydantic

Frontend
- HTML / CSS / JavaScript
  또는 현재 프로젝트에 적합한 경량 Frontend

Realtime
- SSE

Local Data
- File System
```

Phase 1에서는 다음 기술을 필요 없이 추가하지 않는다.

- Redis
- Celery
- Kafka
- Kubernetes
- Vector DB
- Distributed Worker

---

## 26. Out of Scope

Phase 1에서는 다음을 구현하지 않는다.

- Multi Worker
- Workflow DAG
- Task Dependency
- Artifact Handoff
- Artifact Lineage Graph
- Shared Library Publish
- Approval Workflow
- Revision Workflow
- Scheduling
- Recurring Workflow
- AI Reviewer Pipeline
- AI Planner
- Automatic Model Routing
- Semantic Search
- Vector DB
- Remote Worker
- Team Collaboration
- Complex Workflow Canvas

이 기능들은 이후 Phase에서 다룬다.

---

## 27. Phase 1 Representative Scenario

사용자는 Category를 생성한다.

```text
Coding
```

Work를 생성한다.

```text
AI Project Control Center
```

Work에 다음 파일을 추가한다.

```text
phase1-requirements.md
architecture.md
```

Request를 입력한다.

```text
현재 Architecture를 검토하고
Phase 1 구현에서 문제가 될 구조를 찾아줘.
```

사용자는:

```text
Model: GPT-6 Astra
Reasoning: High
Context:
- phase1-requirements.md
- architecture.md
```

를 선택하고 실행한다.

Control Center는:

```text
Request 생성
→ Run 생성
→ Codex Thread / Turn 실행
→ Event Streaming
→ Web UI 실시간 표시
```

를 수행한다.

사용자는 실행 중:

```text
DB 정합성 문제를 우선 검토해.
```

라는 추가 지시를 보낼 수 있다.

Codex가 다음 파일을 생성한다.

```text
artifacts/architecture-review.md
```

Control Center는 실제 파일 생성 여부를 확인하고
Artifact로 등록한다.

사용자는 Web에서 결과를 Preview한다.

이후 같은 Thread를 Resume해 추가 작업을 수행할 수 있다.

---

## 28. Acceptance Criteria

Phase 1 완료를 주장하기 전에 최소 다음을 실제 검증한다.

1. ChatGPT 계정 기반 Codex 인증이 동작한다.
2. Runtime에서 사용 가능한 Model 목록을 조회할 수 있다.
3. Category를 생성할 수 있다.
4. Work를 생성할 수 있다.
5. Work 디렉터리가 실제 생성된다.
6. Source / Context 파일을 등록할 수 있다.
7. Request를 생성할 수 있다.
8. Model / Reasoning / Context를 선택할 수 있다.
9. 실행 요청 후 Run ID가 빠르게 반환된다.
10. Codex Turn이 실제 실행된다.
11. 실행 Event가 Web에 실시간으로 표시된다.
12. 실행 중 추가 Instruction이 동작한다.
13. Cancel이 실제 Codex 실행을 중단한다.
14. Run 완료 / 실패 / 취소 상태가 DB와 일치한다.
15. AI가 생성한 파일을 실제 확인 후 Artifact로 등록한다.
16. Markdown / Text / Code / Image Preview가 동작한다.
17. Run에서 사용한 Context Manifest가 저장된다.
18. 과거 Run History를 조회할 수 있다.
19. 기존 Codex Thread를 Resume할 수 있다.
20. Resume 실행은 새 Run History로 저장된다.
21. AI Worker가 `control.db`를 직접 수정하지 않는다.
22. Backend 재시작 후 과거 Work / Run / Artifact가 유지된다.
23. 기존 데이터가 손상되지 않는다.
24. 최종 `docs/architecture.md`가 실제 구현과 일치한다.

---

## 29. Phase 1 Completion Definition

Phase 1은 단순히 Codex를 실행할 수 있다고 완료된 것이 아니다.

다음 전체 흐름이 실제로 안정적으로 동작해야 한다.

```text
Local Work
   ↓
Context 선택
   ↓
Natural Language Request
   ↓
Codex Thread / Turn
   ↓
Realtime Event
   ↓
Steer / Cancel
   ↓
Artifact
   ↓
Preview
   ↓
History / Resume
```

이 흐름이 실제 End-to-End로 동작하고
로컬 Work / Artifact / Run 상태가 일관되게 보존되어야 Phase 1 완료로 본다.

Stocks
```

최소 기능:

- Category 목록
- Category 생성
- Category 이름 수정
- Category 비활성화
- Category별 Work 조회

실제 데이터 삭제보다 비활성화를 기본으로 한다.

---

## 6. Work

Work는 하나의 장기 프로젝트 또는 문제 단위이다.

예:

```text
AI Project Control Center
AI IP Studio 사업제안서
한국도로공사 지원
```

Work 생성 시 로컬 디렉터리를 함께 생성한다.

예:

```text
0001_ai-project-control-center/
├── sources/
├── context/
├── artifacts/
├── decisions/
└── work.json
```

최소 기능:

- Work 생성
- Work 목록
- Work Detail
- Work 이름 / 설명 수정
- Work Archive
- Work 디렉터리 열람

---

## 7. Source / Context

Work에 사용자가 직접 자료를 추가할 수 있어야 한다.

예:

- Markdown
- Text
- PDF
- Image
- Source Code
- 기타 일반 파일

Phase 1에서는 복잡한 Semantic Search를 구현하지 않는다.

사용자는 AI Request를 실행할 때
어떤 Context를 사용할지 직접 선택할 수 있어야 한다.

예:

```text
Context
☑ phase1-requirements.md
☑ architecture.md
☐ old-notes.md
```

Control Center는 선택된 Context를
Codex 실행에 명시적으로 전달한다.

---

## 8. Request

Request는 사용자가 AI에게 전달하는 하나의 작업 의도이다.

예:

```text
현재 Architecture를 검토하고
비동기 상태 관리에서 문제가 될 부분을 찾아줘.
```

Request와 실제 실행 Run은 분리한다.

```text
Request
  ↓
Run #1
Run #2 (Retry)
Run #3 (Resume / Revision)
```

Phase 1에서는 최소:

- Request 생성
- Request History
- Request Detail
- Request에 사용한 Context 기록

을 지원한다.

---

## 9. Run

Run은 실제 Codex 실행 한 번을 의미한다.

Run은 최소 다음 정보를 가진다.

- Run ID
- Request ID
- Work ID
- Codex Thread ID
- Codex Turn ID
- Model
- Reasoning
- Started At
- Completed At
- Status
- Error
- Context Manifest
- 생성 Artifact

기본 상태:

```text
CREATED
RUNNING
COMPLETED
FAILED
CANCELLED
```

Phase 1에서는 Workflow Task 상태와 섞지 않는다.

---

## 10. Codex Gateway

Backend 내부에 Codex Gateway 계층을 둔다.

역할:

- SDK 초기화
- 인증 상태 확인
- Model 목록 조회
- Thread 생성
- Turn 실행
- Event Streaming
- Steer
- Interrupt
- Resume
- 오류 변환

다른 Service가 Codex SDK 세부 구현을 직접 사용하지 않도록 한다.

예:

```text
RequestService
  ↓
RunService
  ↓
CodexGateway
  ↓
AsyncCodex
```

---

## 11. Model / Reasoning

Model과 Reasoning 옵션은 가능하면 하드코딩하지 않는다.

Codex Runtime에서 제공하는 Model / Capability 정보를 조회하고
UI 선택지에 반영한다.

UI 예:

```text
Model
[GPT-6 Astra ▼]

Reasoning
[High ▼]
```

사용자가 선택하지 않은 경우
합리적인 기본값을 사용할 수 있다.

---

## 12. Execution

사용자가 Request를 실행하면:

```text
Request 생성
  ↓
Run 생성
  ↓
Codex Thread / Turn 생성
  ↓
Streaming Event 수신
  ↓
Artifact 생성
  ↓
Run 완료
```

HTTP 요청 자체가 AI 작업 완료까지 blocking 되어서는 안 된다.

실행 시작 요청은 빠르게 Run ID를 반환해야 한다.

---

## 13. Real-time Event

Codex App Server / SDK가 제공하는 구조화 Event를 활용한다.

Frontend가 Codex의 Raw Protocol을 직접 해석하지 않는다.

구조:

```text
Codex Event
  ↓
Codex Gateway
  ↓
Control Center Event
  ↓
Event Store
  ↓
SSE
  ↓
Web UI
```

Phase 1에서 최소 표준 Event:

- RUN_STARTED
- ACTIVITY
- COMMAND_STARTED
- COMMAND_COMPLETED
- FILE_CHANGED
- WARNING
- RUN_COMPLETED
- RUN_FAILED
- RUN_CANCELLED

숨겨진 Chain-of-Thought를 노출하지 않는다.

사용자에게 유용한 작업 상태만 표시한다.

---

## 14. Steer

실행 중 사용자가 추가 지시를 보낼 수 있어야 한다.

예:

```text
DB 정합성 문제를 우선해서 확인해.
```

Codex Runtime이 현재 Turn Steering을 지원하는 경우
SDK의 해당 기능을 사용한다.

UI 예:

```text
실행 중 추가 지시
[________________________________]
[보내기]
```

---

## 15. Cancel

실행 중 Run을 취소할 수 있어야 한다.

UI:

```text
[실행 취소]
```

Backend는 Codex Runtime의 Interrupt 기능을 사용하고
Run 상태를 `CANCELLED`로 정합성 있게 변경한다.

UI에서 단순히 RUNNING 표시만 제거하는 방식으로 구현하지 않는다.

---

## 16. Resume

과거 Codex Thread를 다시 이어서 실행할 수 있어야 한다.

예:

```text
어제 하던 Architecture 검토 계속하기
```

Phase 1에서는 최소한:

- 기존 Thread ID 저장
- Thread Resume
- 새 Run 생성
- 과거 Run History 유지

를 지원한다.

동일 Run을 다시 부활시키지 않고,
Resume 실행도 새로운 Run Record로 남기는 것을 기본으로 한다.

---

## 17. Artifact

Artifact는 AI 작업으로 생성된 실제 결과물이다.

예:

- Markdown
- Text
- Source Code
- JSON
- Image
- HTML
- 기타 파일

Artifact는 최소 다음 정보를 가진다.

- Artifact ID
- Work ID
- Run ID
- Path
- Name
- Type
- Created At
- Size
- Hash

Phase 1에서는 Artifact Publish / Global Sharing은 구현하지 않는다.

모든 Artifact는 기본적으로 해당 Work에 속한다.

---

## 18. Artifact Detection

가능하면 Codex App Server의 `fileChange` Event와
실제 파일 시스템 상태를 함께 활용한다.

AI가 생성했다고 주장한 파일이 실제 존재하는지 검증한 뒤
Artifact로 등록한다.

단순히 AI 최종 응답의 텍스트만 믿고 Artifact를 등록하지 않는다.

---

## 19. Artifact Preview

Web UI에서 최소 다음 Preview를 제공한다.

- Markdown
- Plain Text
- Source Code
- Image

지원하지 않는 파일은:

- 파일 정보 표시
- 로컬 경로 확인
- 열기 / 다운로드 가능한 방식

을 제공한다.

Phase 1에서는 복잡한 Office 문서 Viewer를 구현하지 않는다.

---

## 20. Context Manifest

각 Run에서 실제로 어떤 Context를 사용했는지 기록한다.

예:

```json
{
  "run_id": "run_001",
  "files": [
    {
      "path": "context/architecture.md",
      "hash": "..."
    },
    {
      "path": "context/phase1-requirements.md",
      "hash": "..."
    }
  ]
}
```

목적:

- 재현성
- 디버깅
- 추후 Artifact Lineage
- 향후 Workflow Handoff

Phase 1에서는 Vector DB를 사용하지 않는다.

---

## 21. Database

Control Plane 상태는 SQLite에 저장한다.

최소 Entity:

- Category
- Work
- Source
- Request
- Run
- Artifact
- Event

향후 확장을 위해 다음 Entity를 추가할 수 있는 구조로 설계한다.

- Workflow
- Task
- Approval
- Schedule

하지만 Phase 1에서는 해당 기능을 구현하지 않는다.

AI Worker는 `control.db`를 직접 수정하지 않는다.

DB 변경은 Backend만 수행한다.

---

## 22. AGENTS.md

Project / Work 수준의 불변 규칙은
Codex의 `AGENTS.md`를 활용할 수 있다.

예:

```text
- control.db를 직접 수정하지 않는다.
- artifacts 영역 외부에 결과 파일을 임의 생성하지 않는다.
- 기존 Artifact를 덮어쓰지 않는다.
- 테스트 실패 상태에서 완료라고 보고하지 않는다.
```

Task별 세부 Instruction을 AGENTS.md에 누적하지 않는다.

AGENTS.md는 프로젝트 운영 규칙에만 사용한다.

---

## 23. Security / Permissions

Phase 1에서는 최소 다음을 보장한다.

- AI Worker의 Control DB 직접 수정 금지
- 허용된 Work / Project Path 중심으로 실행
- Codex Sandbox Capability 활용
- Runtime Permission 요청과 일반 Workflow 상태를 분리
- Shell Command / File Change Event 기록

Runtime이 요청하는 Permission Approval을
향후 UI에서 처리할 수 있도록 확장 지점을 남긴다.

Phase 1에서는 복잡한 Permission Inbox는 필수 요구사항이 아니다.

---

## 24. UI Scope

Phase 1에서는 최소 다음 화면을 제공한다.

### Dashboard

- 최근 Work
- 최근 Run
- 실행 중 Run
- 최근 Artifact

### Category

- Category 목록
- Category 생성

### Work Detail

- Sources
- Context
- Requests
- Runs
- Artifacts

### Request / Run

- 자연어 Instruction
- Model
- Reasoning
- Context 선택
- 실행
- 실시간 상태
- 추가 지시
- Cancel

### Artifact

- 목록
- Detail
- Preview

복잡한 Workflow Canvas는 구현하지 않는다.

---

## 25. Recommended Technology

Phase 1 기본 기술:

```text
Backend
- Python
- FastAPI
- openai-codex Python SDK
- asyncio

Database
- SQLite
- SQLAlchemy
- Alembic

Schema
- Pydantic

Frontend
- HTML / CSS / JavaScript
  또는 현재 프로젝트에 적합한 경량 Frontend

Realtime
- SSE

Local Data
- File System
```

Phase 1에서는 다음 기술을 필요 없이 추가하지 않는다.

- Redis
- Celery
- Kafka
- Kubernetes
- Vector DB
- Distributed Worker

---

## 26. Out of Scope

Phase 1에서는 다음을 구현하지 않는다.

- Multi Worker
- Workflow DAG
- Task Dependency
- Artifact Handoff
- Artifact Lineage Graph
- Shared Library Publish
- Approval Workflow
- Revision Workflow
- Scheduling
- Recurring Workflow
- AI Reviewer Pipeline
- AI Planner
- Automatic Model Routing
- Semantic Search
- Vector DB
- Remote Worker
- Team Collaboration
- Complex Workflow Canvas

이 기능들은 이후 Phase에서 다룬다.

---

## 27. Phase 1 Representative Scenario

사용자는 Category를 생성한다.

```text
Coding
```

Work를 생성한다.

```text
AI Project Control Center
```

Work에 다음 파일을 추가한다.

```text
phase1-requirements.md
architecture.md
```

Request를 입력한다.

```text
현재 Architecture를 검토하고
Phase 1 구현에서 문제가 될 구조를 찾아줘.
```

사용자는:

```text
Model: GPT-6 Astra
Reasoning: High
Context:
- phase1-requirements.md
- architecture.md
```

를 선택하고 실행한다.

Control Center는:

```text
Request 생성
→ Run 생성
→ Codex Thread / Turn 실행
→ Event Streaming
→ Web UI 실시간 표시
```

를 수행한다.

사용자는 실행 중:

```text
DB 정합성 문제를 우선 검토해.
```

라는 추가 지시를 보낼 수 있다.

Codex가 다음 파일을 생성한다.

```text
artifacts/architecture-review.md
```

Control Center는 실제 파일 생성 여부를 확인하고
Artifact로 등록한다.

사용자는 Web에서 결과를 Preview한다.

이후 같은 Thread를 Resume해 추가 작업을 수행할 수 있다.

---

## 28. Acceptance Criteria

Phase 1 완료를 주장하기 전에 최소 다음을 실제 검증한다.

1. ChatGPT 계정 기반 Codex 인증이 동작한다.
2. Runtime에서 사용 가능한 Model 목록을 조회할 수 있다.
3. Category를 생성할 수 있다.
4. Work를 생성할 수 있다.
5. Work 디렉터리가 실제 생성된다.
6. Source / Context 파일을 등록할 수 있다.
7. Request를 생성할 수 있다.
8. Model / Reasoning / Context를 선택할 수 있다.
9. 실행 요청 후 Run ID가 빠르게 반환된다.
10. Codex Turn이 실제 실행된다.
11. 실행 Event가 Web에 실시간으로 표시된다.
12. 실행 중 추가 Instruction이 동작한다.
13. Cancel이 실제 Codex 실행을 중단한다.
14. Run 완료 / 실패 / 취소 상태가 DB와 일치한다.
15. AI가 생성한 파일을 실제 확인 후 Artifact로 등록한다.
16. Markdown / Text / Code / Image Preview가 동작한다.
17. Run에서 사용한 Context Manifest가 저장된다.
18. 과거 Run History를 조회할 수 있다.
19. 기존 Codex Thread를 Resume할 수 있다.
20. Resume 실행은 새 Run History로 저장된다.
21. AI Worker가 `control.db`를 직접 수정하지 않는다.
22. Backend 재시작 후 과거 Work / Run / Artifact가 유지된다.
23. 기존 데이터가 손상되지 않는다.
24. 최종 `docs/architecture.md`가 실제 구현과 일치한다.

---

## 29. Phase 1 Completion Definition

Phase 1은 단순히 Codex를 실행할 수 있다고 완료된 것이 아니다.

다음 전체 흐름이 실제로 안정적으로 동작해야 한다.

```text
Local Work
   ↓
Context 선택
   ↓
Natural Language Request
   ↓
Codex Thread / Turn
   ↓
Realtime Event
   ↓
Steer / Cancel
   ↓
Artifact
   ↓
Preview
   ↓
History / Resume
```

이 흐름이 실제 End-to-End로 동작하고
로컬 Work / Artifact / Run 상태가 일관되게 보존되어야 Phase 1 완료로 본다.
