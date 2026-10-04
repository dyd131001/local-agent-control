# Phase 2 Implementation Plan

작성일: 2026-09-29. 이 문서는 구현 전 설계이며 Phase 2 구현 완료 보고서가 아니다. 구현 대조·수정·검증 결과는 [중간 리뷰](intermediate-review.md)를 참조한다.

기준: [phase2-requirements.md](phase2-requirements.md), [architecture.md](architecture.md), [runtime-capabilities.md](runtime-capabilities.md), 현재 `app/`, `tests/test_phase1.py`, `app/migrations/versions/0001_initial.py`.

## 1. 적용 범위와 확정 원칙

요구사항의 Managed Workflow를 기존 실행 경로 위에 추가한다. 기존 아키텍처의 Runtime, 저장소 소유권, Sandbox, Run/Thread/Turn 관계, 이벤트 저장 후 SSE 전송 결정은 유지한다. 아래에서 정하는 실패 집계, Retry 선택, Branch 범위 등은 요구사항과 현재 코드 사이의 미정 구현 규칙이다.

```text
Workflow API → WorkflowService → DagScheduler → TaskRunner
                                               ↓
                         기존 Runner / RunService → CodexGateway
                                               ↓
                                  고정된 SDK / App Server
```

- FastAPI 단일 프로세스/단일 worker, SQLite, asyncio를 유지한다. 새로운 Runtime, 외부 Queue, 범용 플러그인 실행 프레임워크를 만들지 않는다.
- Task의 Runtime은 현재 `CODEX`만 허용한다. Model/Reasoning은 기존 Gateway catalog에서 선택하고 실제 사용값을 Run에 고정한다.
- Scheduler와 상태 변경, DB 쓰기, Artifact 등록은 Backend만 수행한다. AI는 현재 작업 지시와 명시한 입력 경로를 받고 파일을 생성한다.
- 일반 Task 및 Retry는 새 Thread를 사용한다. Task 간 전달은 Artifact ID/출처/검증된 바이트를 사용한다. 선행 Task의 대화, final_text, 폴더 탐색을 Handoff로 사용하지 않는다.
- Approval/Schedule/Context Pack/Context Lifecycle, Delegated mode, 자동 Merge, 자동 Publish, 자동 재시도는 구현하지 않는다.
- Shared Library와 Workflow Template은 Phase 2 필수 범위이므로 최소 수동 기능을 포함한다.
- `ARTIFACT_ONLY/GIT_WORKTREE`는 Task 실행 격리 방식, `MANAGED/LINKED`는 Work가 프로젝트를 연결하는 방식이다. 두 개념을 같은 enum으로 합치지 않는다.

## 2. 현재 구조와 재사용 지점

| 현재 파일/진입점 | 확인한 실제 구현 | Phase 2 변경 경계 |
| --- | --- | --- |
| `app/db.py` | SQLAlchemy 모델, WAL/FK/busy timeout, `Session`, `add_event`, `migrate` | 기존 테이블 유지, 신규 모델/이벤트 scope 추가. DB session을 async 실행 사이에 공유하지 않는다 |
| `app/migrations/versions/0001_initial.py` | 고정 SQL의 Phase 1 테이블 생성 | 수정 금지. `0002_phase2.py`, `down_revision="0001"` 추가 |
| `app/runner.py:Runner.start/close` | process flock, Gateway 수명, recovery, dispatcher 소유 | 프로세스/Gateway는 하나로 유지. 여러 실행 coroutine의 시작·종료를 관리 |
| `Runner.dispatch/execute` | 전역 `active_id` 하나, FIFO, `await execute`로 직렬 처리 | `active_tasks: dict[run_id, asyncio.Task]`와 공유 실행 제한으로 변경. `execute`의 Turn 실행 코드는 재사용 |
| `Runner.finish/reconcile/unknown` | Runtime terminal, 파일 scan, Run terminal/event, 결과 불명 차단 | Task 전용 finalizer를 연결. Run terminal과 Task terminal 사이 crash 복구 추가 |
| `app/gateway.py` | 단일 AsyncCodex, Run별 handle dict, 정규화 event, Steer/Interrupt/history | 병렬 Task에도 그대로 사용. Thread 잠금, 실행별 설정 전달, 선택적 공개 `thread_fork` adapter만 추가 |
| `app/workspace.py:prepare_context` | Source snapshot, manifest v1, 별도 Run cwd | 기존 호출 유지. Artifact 입력과 Task metadata를 추가하는 ExecutionCompiler 연결 |
| `safe_child/safe_read/atomic_write/collect_artifacts` | 링크/특수 파일/크기 검사, hash, 결정적인 Artifact ID, immutable 복사 | 파일 검증·복사를 재사용. scan root 인자화, Output Contract와 출력 slot 매핑 추가 |
| `app/main.py:queue_run` | HTTP 검증, Request/Run 생성, commit/wake 결합 | 생성 로직을 transaction 중립인 RunService로 분리. 기존 API wrapper는 유지 |
| `main.py:run_events` | DB Event ID 기반 replay/heartbeat/종료 시 drain | Workflow scope SSE 추가. 별도 메모리 event bus 불필요 |
| Artifact preview/download | hash 재검사, Markdown sanitize, CSP | 기존 API 유지. 검증 함수의 내부 commit은 서비스 재사용을 위해 분리 |
| `app/static/index.html`, `app.js`, `style.css` | vanilla JS, 단일 선택 Run/stream 상태 | Workflow 목록·편집·실행 화면 및 별도 Workflow stream 상태 추가 |
| `tests/test_phase1.py` | FakeGateway와 임시 DB/폴더의 12개 offline test | 회귀 기준. 새 테스트가 실제 Gateway를 열지 않도록 fixture를 명시 |

주의할 현재 코드와 문서의 차이:

- `architecture.md`는 Phase 1 구현 전 문구를 포함한다. 실제 구현 존재 여부는 위 코드 기준이며 문서의 원칙을 뒤집는 근거로 사용하지 않는다.
- 현재 `Work.path`는 항상 Backend가 만든 DATA_DIR 하위 경로다. LINKED 경로, Git repository, 별도 Task output contract는 아직 없다.
- `Runner.finish()`는 `workspace/artifacts`가 비어 있어도 COMPLETED다. Phase 1 텍스트 요청에는 정상이며 Task의 필수 출력 누락과 구분해야 한다.
- 실제 `Event`는 `run_id NOT NULL`이다. Run 생성 전 `TASK_BLOCKED`나 Workflow event를 현재 스키마에 저장할 수 없다.
- 아키텍처에 기재된 Thread/Work 잠금은 현재 별도 구현이 없고, 전역 직렬 dispatcher가 실질적으로 경합을 막는다. 병렬화 전에 명시적인 잠금을 넣어야 한다.
- 현재 `prepare_context/finish`에는 경로 조합이 하드코딩되어 있다. LINKED 경로를 `Work.path`에 대입하거나 worktree를 manifest에만 기록해서는 해결되지 않는다.
- 실제 migration 경로는 `app/migrations`다. 저장소 루트의 `alembic/`는 `db.migrate()`가 사용하지 않는다.

## 3. 추가할 Entity와 서비스 경계

### 3.1 정의와 실행 이력

Definition은 편집 가능한 설계, Run snapshot은 실행 당시의 불변 설계다. Definition 변경이 이미 시작한 실행, Retry, Branch를 바꾸지 않아야 한다.

| Entity | 필드와 제약 |
| --- | --- |
| `WorkflowDefinition` | `id`, `work_id` FK, `name`, `description`, `enabled`, `revision`(1부터), `unresolved_bindings` JSON(default `[]`, Template 복제 시 재선택할 항목), timestamps. Phase 2는 Work 소유 Definition만 만들고 Category 재사용은 Template으로 처리 |
| `TaskDefinition` | `id`, `workflow_definition_id` FK, `name`, `instruction`, `runtime=CODEX`, `model`, `reasoning`, `context_rule` JSON text, `input_rule` JSON text, `output_rule` JSON text, `workspace_mode`, `display_order`, `enabled`, timestamps. 삭제는 `enabled=false`; 실행 참조 ID는 보존 |
| `TaskDependency` | `workflow_definition_id`, `task_definition_id`(소비자), `depends_on_task_definition_id`(생산자). PK는 소비자/생산자 쌍, self-edge CHECK, 동일 Definition 소속 검증 |
| `WorkflowRun` | `id`, `workflow_definition_id` FK, `work_id` FK, `definition_revision`, `definition_snapshot` JSON, `status`, `execution_round=1`, `cancel_requested=false`, `parent_workflow_run_id` nullable FK, `branch_from_task_run_id` nullable FK, `command_key` nullable UNIQUE/`command_hash`, `error` JSON nullable, `created_at/started_at/completed_at` |
| `TaskRun` | `id`, `workflow_run_id` FK, `task_definition_id` FK, `run_id` nullable UNIQUE FK, `attempt_number>=1`, `parent_task_run_id` nullable FK, `operation`(`initial/retry/branch`), `status`, `blocked_reason` JSON nullable, `cancel_requested=false`, `command_key` nullable UNIQUE/`command_hash`, `error` JSON nullable, `contract_report` JSON nullable, `created_at/started_at/completed_at`. UNIQUE(workflow_run_id, task_definition_id, attempt_number) |
| `TaskRunOutput` | `task_run_id` FK, `output_key`, `artifact_id` FK. PK(task_run_id, output_key). 동일 Task의 slot 경로 중복 금지 |
| `ArtifactRelation` | 아래 §7의 INPUT/DERIVED_FROM/REVISION_OF를 저장 |
| `WorkflowTemplate` | `id`, `name`, `description`, `source_workflow_definition_id` nullable, `snapshot` JSON, timestamps. snapshot 복제이며 Definition/실행과 동기화하지 않는다 |
| `ArtifactPublication` | `id`, `artifact_id` UNIQUE FK, `scope`(`WORK/CATEGORY/GLOBAL`), `category_id` nullable FK, `status=PUBLISHED`, `published_at`. 소유 Work는 Artifact에서 유도 |

`WorkflowRun.definition_snapshot`에 schema_version, Task ID별 전체 실행 설정, 정렬 순서, Dependency 목록, Work/사용자 Context 선택 및 hash, output/input rules를 저장한다. JSON은 Pydantic DTO로 검증하고 내부에서는 파싱된 객체를 사용한다. 별도 Definition version 테이블, 범용 expression DSL, 매 실행마다 TaskDefinition 복제는 필요 없다.

Definition의 Task 삭제는 새 revision에서만 제외한다. 실행 snapshot에 있는 비활성 Task의 FK는 계속 유효하다. snapshot에 없는 TaskRun 생성은 거절한다. Definition 자체는 비활성화만 제공한다.

각 `(workflow_run_id, task_definition_id)`의 **현재 시도는 최대 attempt_number**다. 성공한 과거 시도를 임의로 찾지 않는다. 동일 실행에 Branch 시도를 섞지 않으므로 별도의 selected-attempt 테이블은 필요 없다. attempts는 append-only이고 terminal TaskRun을 Retry 때문에 RUNNING으로 바꾸지 않는다.

`TaskRun.run_id`는 BLOCKED/READY일 때 null일 수 있다. QUEUED로 바뀌는 transaction에서 Request/Run을 생성해 연결한다. Run 생성 전 취소된 Task에도 TaskRun 이력은 남는다.

### 3.2 파일 단위 구현 책임

| 신규/변경 모듈 | 책임 |
| --- | --- |
| `app/workflow.py` | WorkflowService, Definition 저장/검증, snapshot 생성, 실행 생성, 취소/Retry/Branch/Template 복제 |
| `app/scheduler.py` | 순수 DAG 검증·준비 상태 판단·완료 집계와 단일 wake loop. SDK 호출 금지 |
| `app/task_runner.py` | READY를 기존 Request/Run에 연결, Task completion/contract/lineage finalization. 자체 Runtime reader 금지 |
| `app/run_service.py` | 기존 `queue_run`에서 DB 생성/검증 공통 부분 추출. HTTP 객체/commit/wake 없이 caller transaction 사용 |
| `app/execution.py` | ExecutionCompiler: snapshot과 입력 Artifact를 실제 manifest/prompt/cwd로 구체화 |
| `app/artifact_service.py` | 기존 Artifact 검증·수집 helper 활용, output slot, lineage, Library 선택/수동 publish |
| `app/workspace.py` | 관리 경로 resolver, Source/입력 복사, ARTIFACT_ONLY 준비 유지 |
| `app/git_workspace.py` | Backend의 관리용 Git 저장소와 Run별 worktree 준비, baseline/patch 수집, 경로 검증 |
| `app/workflow_api.py` | 신규 FastAPI router/DTO. 기존 인증 middleware와 오류 처리 재사용 |
| `app/runner.py`, `gateway.py`, `db.py`, `main.py` | 기존 실행 경로의 제한된 확장; 기존 코드를 모두 새 프레임워크로 옮기지 않는다 |

## 4. 0002 Migration

### 4.1 기존 테이블 확장

- `works`: `workspace_kind NOT NULL DEFAULT 'MANAGED'`, `linked_workspace_path TEXT NULL`. 기존 `path` 값과 파일 위치는 그대로 유지한다. CHECK로 LINKED이면 연결 경로 필수, MANAGED이면 null을 강제한다.
- `requests`: `artifact_ids TEXT NOT NULL DEFAULT '[]'`. Phase 1 Source용 `context_ids` 형식은 바꾸지 않는다. 명시적 Library/Artifact 선택을 별도 저장한다.
- `runs`: 기존 열/상태/unique(thread_id, turn_id)/command_key를 유지한다. Task 소속은 UNIQUE인 `TaskRun.run_id` 역조회로 찾는다. Workflow ID를 Run에 중복 저장할 필요 없다.
- `artifacts`: 원래 열과 경로, hash, availability, partial 유지. 생산 TaskRun은 Artifact.run_id → TaskRun.run_id로 추적한다. Publish는 별도 테이블이므로 기존 Artifact를 자동 공개하지 않는다.
- `events`: `run_id` nullable로 변경하고 `workflow_run_id`, `task_run_id` nullable FK, `dedupe_key` nullable UNIQUE 추가. 기존 event ID/payload/type/timestamp를 그대로 복사한다. `run_id IS NOT NULL OR workflow_run_id IS NOT NULL` CHECK; task_run_id가 있으면 workflow_run_id도 필수. 관계의 소속 일치는 서비스에서 검증한다.
- 새 index: `events(workflow_run_id, id)`, `task_runs(workflow_run_id, task_definition_id, attempt_number)`, `task_runs(status)`, `workflow_runs(work_id, created_at)`, Dependency 역방향 조회, lineage 양방향 조회. 기존 `ix_events_run_id` 유지.

신규 테이블은 §3과 §7에 적은 필드/FK/unique/CHECK를 명시적으로 `op.create_table`로 만든다. JSON에는 version을 포함하되 SQLite JSON 확장을 필수로 요구하지 않는다. SQLAlchemy default와 migration의 server_default를 혼동하지 않는다. 기존 행에 필요한 기본값은 migration에서 제공한다.

### 4.2 SQLite 적용 순서와 검증

1. Backend 실행/dispatch가 멈춘 상태에서 기존 process lock을 확보한다. 실제 운영 upgrade 전 SQLite backup API 등 일관된 백업을 만든다. WAL 사용 중 `control.db` 파일만 복사하지 않는다.
2. 신규 테이블을 부모부터 생성한다. WorkflowRun의 `branch_from_task_run_id`는 SQLite의 forward-reference FK로 선언한 뒤 TaskRun을 생성한다. migration 중 실행 데이터를 insert하지 않으며 모든 테이블 생성 후 FK check를 수행한다. 상호 참조 때문에 부모 테이블을 나중에 불필요하게 recreate하지 않는다.
3. Work/Request 기본값 열을 추가한다. Work는 기존 자식 FK가 많으므로 recreate하지 않는다. 먼저 workspace_kind를 추가하고 linked_workspace_path를 추가하는 고정 `ALTER TABLE ... ADD COLUMN ... CHECK (...)` SQL에 두 열의 조합 검사를 포함한다. Event의 nullability/FK/CHECK 변경은 Alembic `batch_alter_table`로 recreate한다. Event를 참조하는 기존 자식 테이블은 없지만 모든 기존 ID와 index 보존을 테스트한다.
4. `0001`을 import한 동적 ORM metadata/create_all로 schema를 만들지 않는다. 0002의 DDL은 해당 revision에서 고정한다. `app/migrations/env.py`의 connection/transaction 경로를 사용한다.
5. `PRAGMA foreign_key_check`, row count/ID/hash 보존, 새 default, index/unique, `alembic_version=0002` 확인. Event FK를 일시적으로 무조건 끄는 편법은 쓰지 않는다.
6. fresh DB `0001→0002`, Phase 1 데이터가 든 DB `0001→0002`, 이미 head인 DB 재기동을 각각 테스트한다. migration에 파일 이동, Codex 호출, Task 실행을 넣지 않는다.

FK는 기본적으로 RESTRICT/NO ACTION으로 이력을 보호한다. destructive downgrade는 0001처럼 거절하고 백업 복원을 안내한다. 전환 뒤 마지막 기존 Event ID보다 새 Event ID가 큰지 검증한다. event 삭제/ID 재사용은 제공하지 않는다.

## 5. Task 입력·출력 규칙과 DAG 검증

규칙 예시(D는 B/C에 의존하고 A는 전이적 선행 Task):

```json
{
  "context_rule": {
    "inherit_workflow_context": true,
    "source_ids": [],
    "artifact_ids": []
  },
  "input_rule": [
    {"input_key": "draft", "task_definition_id": "task_a", "output_key": "draft"},
    {"input_key": "market", "task_definition_id": "task_b", "output_key": "review"},
    {"input_key": "technical", "task_definition_id": "task_c", "output_key": "review"}
  ],
  "output_rule": [
    {"output_key": "final", "path": "final-proposal.md", "required": true,
     "media_type": "text/markdown"}
  ],
  "workspace_mode": "ARTIFACT_ONLY"
}
```

고정 Artifact 입력은 `{"input_key":"reference","artifact_id":"art_..."}` 형태를 사용한다. `artifact_id`와 `(task_definition_id, output_key)`는 정확히 하나만 허용한다. Context 선택용 artifact_ids도 실행 시 `context:<artifact_id>` input_key로 정규화한다. 추측 경로/Artifact 이름만으로 입력을 resolve하지 않는다.

- Workflow 저장 시 모든 Task/Dependency를 한 transaction으로 교체하고 `revision` 조건부 UPDATE로 lost update를 방지한다. 요청 revision이 오래되면 409다.
- 빈 graph, self-edge, duplicate edge, 존재하지 않는 Task, 다른 Definition Task, 비활성 Task 참조, cycle을 거절한다. Kahn topological sort로 O(V+E) 검증하며 cycle 오류에 관련 Task ID를 반환한다.
- Input의 생산 Task는 소비 Task의 **직접 또는 전이적 선행 Task**여야 한다. 연결되지 않은 Task의 결과 참조는 오류다. Input을 보고 숨은 dependency를 자동 추가하지 않는다.
- 생산 output_key가 선언되어 있어야 한다. 동적 downstream input은 `required=true` output만 참조하게 하여 optional 출력 누락의 모호함을 없앤다.
- output_key/input_key는 Task 내부 unique다. Output path는 상대 POSIX 경로이며 절대 경로, `..`, backslash, glob, 빈 경로, 예약 관리 경로, 정규화 후 중복을 거절한다. 같은 basename은 서로 다른 상대 경로일 때만 허용한다.
- `output_rule=[]`인 terminal 텍스트 Task는 허용한다. 그런 Task의 final_text를 자동 Artifact로 만들거나 downstream에 전달하지 않는다.
- Definition에는 모델/effort를 명시적으로 저장한다. 저장/실행 시작 시 기존 catalog 검증을 사용한다. 실행 도중 모델이 사라지면 명확히 실패시키며 다른 모델로 대체하지 않는다.
- Source/Artifact/Library 범위와 Workspace 경로 유효성을 저장 및 실행 시 확인한다. 실행 직전 bytes/hash 검사는 별도로 수행한다.
- Workflow Run 생성 시 다시 DAG 검증한 snapshot을 저장하고 각 Task attempt 1을 생성한다. root는 READY, 나머지는 BLOCKED(`DEPENDENCY_PENDING`). 이 transaction에서 최초 상태 Event도 저장한다.

## 6. 상태 전이와 Scheduler

### 6.1 TaskRun 상태

| 전이 | 조건/동작 |
| --- | --- |
| 생성 → READY/BLOCKED | snapshot DAG 기준. AI 응답을 사용하지 않는다 |
| BLOCKED → READY | 현재 시도의 모든 직접 선행 Task가 COMPLETED, Workflow 취소 없음 |
| READY → QUEUED | 입력 Artifact ID를 bind하고 새 Request/Run 생성·연결을 동일 transaction으로 commit |
| READY → FAILED | enqueue 입력 검증 자체가 실패하면 새 Request/실패 Run을 연결하고 Task 오류/event까지 한 transaction에 남김. Task가 READY에서 무한 재평가되지 않게 함 |
| QUEUED → RUNNING | 기존 Runner가 실제 Turn ACK/ID를 저장한 transaction에서 `TASK_STARTED`도 저장 |
| QUEUED → FAILED | 입력 검증/Context/workspace/thread 준비 실패. 모델 호출 전에 실패 가능 |
| RUNNING → COMPLETED | Runtime completed + Run Artifact 확정 + 필수 Contract 검증 + 출력 매핑/lineage commit 성공 |
| RUNNING → FAILED | Runtime 실패, 저장 실패, Contract 실패, 또는 결과 불명. 원인 code 구분 |
| BLOCKED/READY → CANCELLED | Task/Workflow 취소 시 Run 없이 terminal 가능 |
| QUEUED/RUNNING → CANCELLED | 미dispatch Run은 DB 취소, dispatch 이후는 기존 interrupt/terminal 규칙 적용 |
| BLOCKED → SKIPPED | 사용자가 선행 실패 경로를 포기한 경우만. 이유와 원인 Task 기록 |

`RUNNING`에는 Run.phase의 FINALIZING/CANCEL_REQUESTED/RECOVERING이 포함될 수 있다. 별도 Task 상태 enum을 추가하지 않고 UI가 phase를 보조 표시한다. Interrupt ACK로 Task를 취소 완료시키지 않는다. 취소와 completed가 경쟁하면 확인한 Runtime terminal 및 contract를 기록한다. 단 Workflow 전체의 cancel intent는 이후 dispatch를 항상 막는다.

기존 Phase 1의 결과 불명 복구는 별도 예외다. `FAILED + safety_block`은 확정 실패가 아니므로 수동 reconcile에서 실제 terminal이 확인되면 같은 Run/TaskRun의 판정을 정정할 수 있다. `TASK_RECONCILED`에 이전 오류와 새 근거를 보존하며 새 Turn은 시작하지 않는다. 기존 Workflow 집계도 재계산하고, 정지된 Workflow에 다시 실행 가능한 Task가 생기면 새 round로 연다. Retry 때문에 확정 terminal을 되살리는 것과 구분한다. safety_block 상태에서는 Contract scan을 성공 근거로 삼지 않는다.

선행 Task가 FAILED면 downstream은 **BLOCKED를 유지**하고 `DEPENDENCY_FAILED`와 원인 TaskRun ID를 기록한다. 즉시 SKIPPED로 바꾸면 Retry 후 다시 실행하기 어렵다. 선행 Task가 CANCELLED/SKIPPED면 그 영향을 받는 아직 미실행 descendants를 SKIPPED로 정리한다. 다른 독립 경로는 계속 진행한다.

사용자의 “실패한 Task 포기”는 이미 FAILED인 TaskRun을 CANCELLED로 덮어쓰지 않는다. 해당 실패 때문에 대기 중인 descendants를 SKIPPED로 만들고 `TASK_SKIPPED`에 포기 명령을 기록한다. 이 경로를 나중에 다시 실행하려면 새 Workflow Run/Branch를 만든다.

### 6.2 WorkflowRun 상태

- CREATED: snapshot/초기 TaskRun 생성 완료, 아직 dispatcher가 실행을 시작하지 않음.
- RUNNING: 최초 Task 준비 시작 시 `WORKFLOW_STARTED`. READY/QUEUED/RUNNING이 있거나 그 진행으로 실행 가능해질 Task가 있음.
- COMPLETED: 모든 현재 Task 시도가 COMPLETED.
- PARTIAL: 실행 가능한 작업이 더 없고 하나 이상 COMPLETED지만 FAILED/CANCELLED/SKIPPED 또는 실패로 BLOCKED인 Task가 남음.
- FAILED: 실행 가능한 작업이 더 없고 성공 Task 없이 실패/중단 경로만 남음.
- CANCELLED: 명시적 Workflow cancel intent가 있고 모든 dispatch/active Run이 종료 확정됨. 일부 성공 결과는 보존한다. 결과 불명 safety_block이 있으면 취소 완료로 꾸미지 않고 오류를 표시한다.

PARTIAL/FAILED는 현재 시도들의 정지된 집계다. 요구사항의 실패 downstream BLOCKED를 유지하면서 Workflow가 영원히 RUNNING으로 표시되지 않게 한다. 명시적 Retry는 같은 WorkflowRun을 RUNNING으로 재개할 수 있다. 이때 `execution_round += 1`, `completed_at=null`, 이전 round의 집계 오류를 event payload에 보존하고 현재 error는 초기화한다. TaskRun 이력은 변경하지 않는다. `WORKFLOW_STARTED`/종료 이벤트 dedupe는 round별이다.

COMPLETED/CANCELLED Workflow는 Retry로 다시 열지 않는다. 새 실행/Branch를 사용한다. PARTIAL/FAILED에서 Retry 허용 조건은 §10을 따른다. 개별 Task의 runtime_interruption은 실패 원인과 함께 CANCELLED로 남으며 Workflow 전체 취소 의도와 구분한다.

### 6.3 Scheduler 책임과 실행 순서

단일 Scheduler loop가 DB의 TaskRun을 재평가한다. 시작/Run terminal/Retry/Cancel/reconcile 뒤 `wake.set()`하고 기존처럼 짧은 timeout도 두어 commit 후 wake 유실을 복구한다. 상태가 바뀌지 않았으면 같은 event를 다시 만들지 않는다.

```python
async def scheduler_tick():
    # transaction은 짧게, await/runtime/file I/O는 바깥에서 수행
    reconcile_terminal_runs_into_tasks()  # idempotent finalizer
    for workflow in dispatchable_workflows():
        current = latest_attempts(workflow)
        for task in topological_order(workflow.snapshot):
            if task.status == BLOCKED:
                update_readiness_from_dependencies(task, current)
        for task in ready_tasks_ordered_by_display_order_then_id():
            # CAS READY → QUEUED; INPUT binding + Request/Run + events 함께 저장
            bind_and_enqueue(task)
        aggregate_workflow_status(workflow)
    runner.wake.set()  # 실제 실행 슬롯은 Runner 한 곳에서만 배정
```

- Task enqueue는 Workflow별 명령 lock과 DB 조건부 UPDATE를 사용한다. HTTP sync handler와 Scheduler가 다른 thread에서 DB 접근하므로 asyncio lock만으로 정합성을 보장하지 않는다. revision/CAS/unique 제약이 최종 방어선이다.
- 상태 전이와 관련 event insert는 하나의 transaction이다. `queue_run`의 기존 내부 commit을 그대로 호출하면 TaskRun 없는 Run이 dispatcher에 노출되므로 먼저 분리한다.
- READY는 의존성이 해소된 상태, QUEUED는 실행할 Run이 영속 등록된 상태다. QUEUED 전체 수와 실제 실행 중 수를 구분한다.
- 실패 경로를 제외한 독립 Task는 계속 실행한다. fail-fast, 자동 대체 경로, AI 기반 재계획은 없다.
- 모든 판단은 현재 Workflow snapshot과 DB를 읽어 재구성한다. 메모리 task 완료 callback만을 정답으로 쓰지 않는다.

## 7. Artifact Handoff와 Lineage

### 7.1 출력 선택과 입력 고정

1. 생산 Task가 Contract 검증을 통과하면 `TaskRunOutput(task_run_id, output_key, artifact_id)`를 저장한다.
2. 소비 Task enqueue 시 input_rule의 생산 Task에 대한 현재 COMPLETED 시도를 찾고 정확한 output_key를 resolve한다. 이름이 같은 다른 Run Artifact를 대용하지 않는다.
3. 직접 선택 Artifact도 scope, availability, partial, 생산 실행 성공 여부를 검증한다. 다른 Work의 Artifact는 유효한 Publication이 있어야 한다.
4. Artifact ID와 당시 hash/size/생산 TaskRun을 INPUT 관계로 고정한다. 준비 중 bytes를 다시 읽고 hash를 확인한 뒤 **소비 Run의 cwd 밖** `runs/<run-id>/inputs/<input-key>/<artifact-id>/<filename>`에 복사한다.
5. snapshot 경로와 hash를 manifest와 INPUT 관계에 기록하고 `ARTIFACT_HANDOFF`를 commit한다. 이후 실제 전달은 이 snapshot 경로다. 같은 filename의 B/C 출력도 충돌하지 않는다.
6. 입력 바이트가 사라지거나 변경되면 `INPUT_ARTIFACT_UNAVAILABLE`/`INPUT_ARTIFACT_CHANGED`로 Task를 실패시키고 후속 실행을 막는다. directory 검색이나 “가장 최근 파일”로 복구하지 않는다.

Task A가 Astra이고 B가 Luna여도 달라지는 것은 새 Run의 model/effort뿐이다. B는 새 Thread에서 A Artifact의 snapshot과 B instruction을 받는다. A의 history/final_text는 prompt에 합치지 않는다.

### 7.2 ArtifactRelation의 정확한 방향

필드: `id`, `kind`, `source_artifact_id` FK, `target_artifact_id` nullable FK, `target_task_run_id` nullable FK, `input_key` nullable, `expected_sha256` nullable, `snapshot_path` nullable, `created_at`.

| kind | 의미/endpoint | 제약 |
| --- | --- | --- |
| INPUT | source Artifact → 소비 TaskRun | target_task_run_id만 존재; input_key/hash 필수; UNIQUE(target_task_run_id, input_key), INPUT에 한정한 partial unique index |
| DERIVED_FROM | 입력 Artifact → 새 출력 Artifact | target_artifact_id만 존재, self-edge 금지; UNIQUE(kind, source_artifact_id, target_artifact_id) |
| REVISION_OF | 이전 버전 Artifact → 명시적 대체 출력 Artifact | target_artifact_id만 존재, self-edge 금지; 위 unique 적용 |

CHECK로 INPUT과 Artifact→Artifact 관계의 endpoint 형식을 구분한다. polymorphic 문자열 ID 하나에 Task/Artifact를 섞지 않는다. 입력 관계의 생산 Task/Run은 source Artifact의 run_id로 찾는다.

성공한 Task의 각 output에 대해 실제 bind된 INPUT Artifact들에서 DERIVED_FROM edge를 만든다. 이는 “제공된 입력”의 추적이지 AI가 파일을 읽었거나 모든 문장을 사용했다는 증거가 아니다. Context로 선택한 Artifact도 동일하게 추적한다. 일반 Source는 기존 Manifest에서 추적하며 Artifact로 변환하지 않는다.

REVISION_OF는 사용자가 Branch 입력/출력 mapping에서 대체 대상을 명시했을 때만 만든다. 동일 filename, Retry, 같은 내용 hash만으로 버전 관계를 추론하지 않는다. Retry의 실패 partial output에는 자동 revision edge를 만들지 않는다.

실패 Task도 INPUT 관계와 partial Artifact를 보존한다. 실패 산출물은 자동 Handoff/Library 후보에서 제외한다. 확정 성공 output이 아닌 partial에 성공 lineage를 표시하지 않는다. lineage API는 원본 availability도 반환한다.

### 7.3 Manifest 확장

Task용 schema_version=2에 기존 필드를 유지하고 다음을 추가한다. 기존 Phase 1 manifest v1 읽기를 유지한다.

- workflow_run_id, task_run_id, task_definition_id, attempt_number, definition_revision.
- frozen output_rule, workspace_mode, output_root, WorkspaceSpec, Git baseline(해당할 때).
- 파일별 input_key, artifact_id, expected_sha256, source_work_id, source_run_id, source_task_run_id, publication scope(해당할 때), snapshot_path/size/hash/MIME/delivery.
- Work Context/사용자 선택/Task Context 출처와 중복 제거 결과. Work Context는 Workflow 시작 화면에서 명시적으로 선택한 자료이며 모든 Work 파일 자동 포함이 아니다.
- Branch 시 `history_mode`와 fork parent; `ARTIFACT`면 history 없음, `FORK`면 같은 Task의 이전 대화도 상속됨을 표시.

실행 설정은 snapshot으로 고정하고 manifest는 준비 단계를 거쳐 Thread ID를 기록한 후 동결한다. Steer는 기존 Instruction 이력에만 추가한다. retry 입력이 이전 준비에서 이미 snapshot되었다면 기존 hash의 snapshot을 새 Run 입력으로 복사한다. 원본 변조를 새 내용으로 받아들이지 않는다.

## 8. Output Contract 검증과 완료 원자성

Contract는 파일의 존재와 전달 가능성에 대한 계약이다. 문서의 의미적 품질을 AI로 평가하거나 복잡한 schema 검증기를 만들지 않는다.

출력 path는 `WorkspaceSpec.output_root` 기준이다. ARTIFACT_ONLY의 root는 기존 `workspace/artifacts`, GIT_WORKTREE의 root는 별도 `outputs`다. Backend가 manifest/prompt에 정확한 root와 필수 상대 경로 목록을 전달한다.

필수 검사:

1. 실제 Runtime terminal을 먼저 저장한다. `completed` 문구/도구 command 성공/FILE_CHANGED만으로 완료하지 않는다.
2. 정확한 상대 경로의 파일을 기존 `safe_read` 방식으로 읽는다. root containment, 링크/특수 파일 거절, 안정적인 stat, 파일별 64 MiB 및 전체 1,000개/256 MiB 제한을 유지한다.
3. 필수 파일은 존재하고 기본적으로 1 byte 이상이어야 한다. JSON rule의 media_type은 이름 기반 등록 metadata와의 일치 검사다. 문서 내용의 진실성/문법 검증을 보장한다고 표시하지 않는다.
4. 기존 immutable 복사 경로/결정적인 Artifact ID를 활용해 복사하고 destination hash를 검증한다. 각 Artifact의 run_id가 현재 TaskRun.run_id와 일치하는지 확인한다.
5. 필수 출력 모두 AVAILABLE이고 partial이 아니며 exact path별 단일 Artifact에 매핑되는지 검사한다. hash/location/producer/output_key를 contract_report에 남긴다.
6. 성공 transaction에서 Artifact row, TaskRunOutput, lineage, Run/Task terminal 상태 및 `ARTIFACT_CREATED`, `RUN_COMPLETED`, `TASK_COMPLETED`를 함께 저장한다. 이후 Scheduler를 깨운다.

기존 `Runner.finish()`를 두 단계로 나눈다: 파일 수집/검증(짧은 DB transaction 밖) → DB finalization. Task 연결 Run만 TaskRunner의 Contract finalizer를 거친다. Phase 1 Run은 기존 zero-output 성공 규칙을 유지한다.

필수 출력 누락은 Run.runtime_status=`completed`를 보존하면서 Run.status/TaskRun.status=`FAILED`, `error.code=OUTPUT_CONTRACT_FAILED`로 저장한다. 파일 복사 실패는 `ARTIFACT_ERROR`, 입력 검증 실패는 별도 code다. 존재하는 다른 출력은 partial로 보존할 수 있지만 TaskRunOutput의 성공 mapping이나 downstream Handoff로 공개하지 않는다. `artifact_state=READY`는 수집 성공을 뜻하며 Contract 성공과 동일시하지 않는다.

복구의 핵심은 **같은 finalizer를 재실행해도 결과가 바뀌거나 이벤트가 중복되지 않는 것**이다.

- 파일 복사 후 DB commit 전 crash: 같은 path/hash/Artifact ID로 재등록한다.
- Runtime terminal 저장 후 finalizer 전 crash: Runtime 재실행 없이 저장된 terminal과 workspace로 finalizer를 재개한다.
- terminal Run이 있는데 TaskRun 갱신이 누락된 기존 경계: startup/tick에서 Run→Task finalizer를 다시 호출한다.
- 이미 완료된 Task는 mutable workspace를 재scan해 새 성공 출력으로 바꾸지 않는다. 확정 Artifact/mapping을 확인한다. 나중 변조는 availability 문제로 표시한다.
- 확정 전 복구 scan에서 동일 candidate 경로의 바이트가 달라졌다면 기존 row를 덮지 않고 `OUTPUT_CHANGED_DURING_FINALIZATION`으로 실패시킨다.
- finalizer 동시 호출은 Run별 lock과 terminal/CAS/unique로 차단한다. event dedupe key 예: `task:<id>:completed`, `artifact:<id>:created`, `handoff:<task-run-id>:<input-key>`.

## 9. 병렬 실행과 기존 Run 재사용

### 9.1 실행 슬롯과 잠금

`CONTROL_CENTER_MAX_PARALLEL_TASKS`를 config에 추가하고 기본값 3, 양의 정수만 허용한다. 하나의 공유 dispatcher가 **전체 실제 실행 슬롯 수를 이 값 이하**로 제한한다. 슬롯은 PREPARING 시작부터 FINALIZING 종료까지 점유한다. 아직 실행하지 않은 QUEUED Run은 슬롯을 점유하지 않는다.

- Workflow Task는 빈 슬롯에서 동시 실행한다. standalone Phase 1 Run은 별도 lane 제한 1을 유지하며 shared slot에도 포함한다. 따라서 Phase 1끼리는 기존 FIFO/직렬 동작이고 Workflow와 공존해도 전체 한도를 넘지 않는다.
- dispatch 가능한 Run을 created_at/id 순으로 선택한다. standalone lane 또는 Thread/Workspace 충돌 때문에 실행할 수 없는 row는 건너뛰어 다른 Task를 실행할 수 있다.
- `active_tasks`에 coroutine을 등록하고 await를 loop 밖에서 관리한다. 각 coroutine은 기존 `Runner.execute(run_id)`를 사용하며 gateway.handle은 Run별로 분리된다.
- Thread ID별 실행 소유권은 준비부터 terminal/finalization까지 유지한다. Resume/Fork/Start는 이 소유권과 queued DB 검사를 확인한다. Steer/Interrupt는 현재 소유 Run의 handle을 사용하므로 terminal까지 잡는 lock을 다시 기다리지 않고 짧은 command lock만 사용한다. 새 Task는 고유 Thread다.
- 쓰기 잠금은 Work 전체가 아니라 실제 canonical writable root별로 건다. 서로 다른 Run workspace/worktree는 병렬 가능하다. Backend의 Work provisioning/관리 Git 갱신은 별도 Work/repository lock으로 짧게 직렬화한다.
- current `Run.safety_block` 전역 차단은 Phase 2에서도 유지한다. 결과 불명 후 새 Run/Retry/Branch/dispatch를 막고 현재 다른 실행의 terminal 처리는 계속한다. safety_block을 단순 실패로 보고 슬롯 재사용하여 새 모델 호출을 시작하지 않는다.
- 동기 파일 scan/hash/Git 명령은 `asyncio.to_thread` 또는 비동기 subprocess로 event loop 밖에서 처리한다. ORM Session을 worker thread에 넘기지 않고 immutable DTO와 파일 경로만 전달한다.

단일 프로세스의 asyncio 소유권과 DB `CREATED/QUEUED → PREPARING` CAS를 같이 사용한다. 별도 broker/lease/분산 Semaphore를 추가하지 않는다.

### 9.2 RunService/Runner 연결

Task enqueue는 명시적인 instruction/context/model/effort로 Request를 만든다. Retry에서 변경되지 않은 Request를 재사용할 수 있지만 Run은 항상 새로 만든다. 새 Run의 operation은 `new/retry/branch`, parent_run_id는 해당 Task의 이전 Run에만 연결한다. 다른 선행 Task Run을 대화 parent로 지정하지 않는다.

ExecutionCompiler는 Runner의 준비 단계에서 TaskRun 존재 여부에 따라 Task snapshot을 적용한다. Task 없이 호출하면 기존 Phase 1 prepare_context 경로를 유지한다. WorkspaceSpec은 다음 정도의 concrete DTO면 충분하다.

```python
WorkspaceSpec(cwd, output_root, input_root, writable_roots,
              mode, git_base_commit=None, git_admin_root=None)
```

Gateway의 thread 생성/Resume/Fork에는 실행별 sandbox settings/developer instructions를 넘길 수 있게 한다. 기존 기본 인자는 Phase 1 SETTINGS/RULES다. 공유 dict를 실행별로 mutate하지 말고 복사한다. GIT_WORKTREE도 Turn에서 완전한 policy를 preset으로 덮어쓰지 않는다.

### 9.3 정상 종료/재시작

종료 시 Scheduler/dispatch 중지 → 모든 active Run의 cancel intent 저장 → 각 handle interrupt → bounded gather로 terminal/finalize 대기 → 미확정 Run RECOVERING/safety_block 기록 → Gateway close → flock 해제 순서를 따른다. 한 Run만 대상으로 하는 현재 `active_id` 종료 코드를 반드시 교체한다.

시작 시 migration → Work/workspace 준비 복구 → 기존 Run recovery → Task finalizer/상태 reconciliation → Workflow 집계 → Scheduler/dispatch 순이다. TaskRun이 QUEUED인데 Run이 terminal인 경우부터 정리한다. SUBMITTING을 자동 재전송하지 않는다. 아직 dispatch하지 않은 CREATED/QUEUED만 안전하게 재개한다. Worktree 준비 도중 crash는 Backend 경로/등록/기준 commit을 확인해 재개하거나 PREPARATION_FAILED로 정리하며 사용자 저장소를 reset하지 않는다.

## 10. Retry와 Branch

### 10.1 Retry

- 대상은 현재 최대 attempt이며 상태가 FAILED여야 한다. safety_block이 있으면 먼저 reconcile해야 한다. terminal이 확인된 실패만 재시도한다.
- PARTIAL/FAILED Workflow 또는 다른 독립 경로가 실행 중인 RUNNING Workflow에서 허용한다. 대상 descendants가 BLOCKED로 남아 있는지 확인한다. 이미 QUEUED/RUNNING/COMPLETED/SKIPPED된 descendant가 있으면 같은 실행 내 Retry는 409다.
- 새 TaskRun의 attempt_number는 +1, parent_task_run_id는 실패 시도, operation=`retry`다. 원래 snapshot의 instruction/model/effort/output rules를 사용한다. 변경 실행은 Branch로 한다.
- 새 Run, 새 cwd, 새 Thread를 사용하고 이전 실패 Run의 Thread를 resume하지 않는다. 입력은 실패 시도의 고정 Artifact binding/hash를 재사용한다. 아직 binding 전에 실패했으면 snapshot 규칙에서 처음 resolve한다.
- Source Context도 이전 manifest의 검증된 snapshot이 있으면 동일 바이트를 새 Run에 복사한다. 준비 전에 실패해 snapshot이 없다면 frozen Source ID/hash로 원본을 검증한다. Retry에서 수정된 파일을 새 Context로 조용히 채택하지 않는다.
- 실패 Task/Run/Event/partial Artifact는 보존한다. 새 시도가 성공해야 downstream이 READY가 된다. 과거 성공 Artifact를 최신 실패의 대용으로 선택하지 않는다.
- `RETRY_CREATED`와 새 TaskRun 생성/Workflow round 변경을 같은 transaction으로 기록한다. idempotency key/hash를 새 TaskRun에 저장할 nullable UNIQUE 열로 둔다. 동일 key 재전송은 기존 새 시도를 반환하며 attempt를 다시 올리지 않는다.

### 10.2 Branch의 최소 범위

Phase 2 Branch는 **선택한 완료 Task 결과를 입력으로 하는 별도 단일 Task WorkflowRun**으로 정한다. 기존 Workflow의 실행 중 graph/선택 output을 교체하지 않는다. 모든 descendants의 선택적 재계산 엔진은 구현하지 않는다. UI에서 “이 결과로 다른 방향 실행”이며 원본 Workflow를 자동 이어가는 기능으로 표시하지 않는다.

- source TaskRun은 COMPLETED, 결과 Artifact는 AVAILABLE이어야 한다. 사용자가 source output_key/Artifact와 새 instruction, 필요하면 model/effort를 선택한다.
- 새 WorkflowRun은 원본 Definition FK와 parent_workflow_run_id/branch_from_task_run_id를 가진다. 실행 snapshot에는 선택한 Task 하나, 새 지시/모델 설정, 빈 dependency, 명시적으로 고른 고정 Artifact inputs/output rules를 저장한다. 원본 Definition 자체는 수정하지 않는다.
- 원본 Task의 선행 Task inputs를 유지할 경우 이미 고정된 Artifact ID로 변환해 snapshot에 포함한다. 원본 Workflow의 미래 실행 결과를 동적으로 참조하지 않는다.
- TaskRun attempt는 새 Workflow 안에서 1, operation=`branch`, parent_task_run_id는 원본이다. 별도의 Request/Run/Artifact/경로를 생성한다. Branch input/output mapping에 지정한 항목만 REVISION_OF로 연결한다.
- 기본 history_mode=`ARTIFACT`: 새 Thread, 선택된 결과와 Context만 제공한다. 모델 변경/다른 Task로의 Handoff는 이 모드를 사용한다.
- 선택적 history_mode=`FORK`: **동일 논리 Task의 대안 실행이고 같은 모델이며 사용자가 대화 상속을 명시했을 때만** source Thread를 fork한다. 일반 Task 전달에 사용하지 않는다.
- 현재 고정 SDK `openai_codex/api.py`에는 공개 `AsyncCodex.thread_fork`가 있다. 소스 주석상 `include_turns`는 응답의 history 포함 여부이며 모델 Context 제거 옵션이 아니다. Fork를 Artifact-only 전달로 설명하면 안 된다.
- Fork는 현재 runtime-capabilities에 실측 성공으로 기록되어 있지 않다. Gateway adapter + fake 계약 테스트로 구현하고 지원 여부/실패를 별도 표시한다. private API, 임의 low-level transport 재구현을 사용하지 않는다.
- SDK fork는 특정 turn_id를 선택하는 인터페이스가 아니다. parent Thread의 마지막 terminal Turn이 source Run.turn_id와 같은지 읽어 확인하고, source Thread를 공유하는 queued/active Run이 없을 때만 허용한다. 후속 Resume가 있는 과거 지점 fork는 409로 거절하고 Artifact 방식 선택을 제공한다.
- fork 실패/timeout을 조용히 Resume나 새 Thread 실행으로 바꾸지 않는다. 결과 불명 경계를 기록한다. fork 성공 Thread ID를 저장한 뒤 Turn을 시작한다.

Branch 생성 idempotency는 새 WorkflowRun.command_key/hash로 관리하고 `BRANCH_CREATED`를 저장한다. 원본 이력 화면은 parent 관계를 조회해 Branch를 표시한다. 원본의 이미 종료된 SSE를 억지로 다시 열어 알리지 않는다.

## 11. Workspace 격리와 LINKED 오염 방지

### 11.1 두 경로의 역할

`Work.path`는 앞으로도 Backend 관리 root다. `linked_workspace_path`는 사용자가 선택한 원본 프로젝트 root이며 읽기/기준 commit 획득에만 쓴다. `provision_work`, Source 업로드, `work.json`, rules/manifest/artifact/run 생성은 항상 관리 root에 수행한다.

```text
<linked project>/                      # 사용자 파일 그대로 유지
<DATA_DIR>/categories/<cat>/works/<id>/
  work.json, AGENTS.md, sources/, context/, artifacts/
  git/repository.git/                  # Backend 관리 Git object/ref 저장소
  runs/<run-id>/
    inputs/                           # Backend-owned, writable root 밖
    workspace/                        # ARTIFACT_ONLY cwd
      AGENTS.md, scratch/, artifacts/
    worktree/                         # GIT_WORKTREE cwd, 프로젝트 파일
    outputs/                          # GIT_WORKTREE 전용 쓰기 output root
<STATE_DIR>/control.db, manifests/, backend.lock
```

- LINKED root에 `artifacts/context/runs/decisions/AGENTS.md/work.json`을 생성하거나 `.gitignore`를 수정하지 않는다. Work 이름 변경/Archive/recovery도 연결 폴더를 수정하지 않는다.
- API에서 임의 execution cwd/writableRoots를 받지 않는다. 사용자가 등록한 경로는 realpath로 고정하고 directory 존재 여부, symlink 경계, STATE_DIR/DATA_DIR와 양방향 포함 관계를 검사한다. 연결 프로젝트와 관리 root가 서로 포함되면 거절한다. 관리 경로를 프로젝트에 복사하는 사고도 막는다.
- 기존 MANAGED Work는 값/폴더를 그대로 유지한다. 기존 연결 경로를 자동 추론하거나 현재 저장소를 자동 LINKED로 바꾸지 않는다.
- MANAGED는 기존 Source/snapshot 기반 작업을 계속 지원한다. GIT_WORKTREE는 유효한 연결 Git repository가 있는 Work만 선택할 수 있다. 비Git LINKED는 ARTIFACT_ONLY 가능, Git 모드는 명시적 준비 오류다.
- 선택한 LINKED 파일을 Context로 쓸 때 Backend가 상대 경로 검증 후 기존 Source 저장소로 import하고 hash를 고정한다. 프로젝트 전체 자동 복사/자동 Context 포함은 없다.

### 11.2 ARTIFACT_ONLY

기존 Run workspace를 그대로 재사용한다. 각 Run의 inputs는 cwd 밖, 결과 후보는 cwd/artifacts다. Worker가 확정 Artifact나 다른 Task 출력 디렉터리를 직접 수정할 수 없다. 동일 Work의 여러 Task도 Run ID가 다른 output root를 쓰므로 파일 충돌이 없다.

### 11.3 GIT_WORKTREE

연결 원본 repo에서 직접 `git worktree add`를 실행하면 원본 `.git/worktrees`를 변경한다. LINKED 비오염 원칙을 지키기 위해 **Backend 관리 Git 복제본에서만 worktree를 생성**한다.

1. Backend가 명시적으로 선택된 local repository의 HEAD commit SHA를 확인한다. 원본은 읽기 전용으로 취급한다. 로컬 dirty/untracked 변경은 자동 포함하지 않고 UI에 “기준 commit의 내용 사용”을 표시한다.
2. 관리 `git/repository.git`를 local bare clone으로 만들되 `--no-hardlinks`를 사용한다. 이후 Backend가 repository lock 아래 원본 local ref를 fetch한다. 네트워크 remote를 자동 fetch하지 않는다. hooks/submodule/LFS 자동 실행·설치를 하지 않으며 필요한 파일이 없다면 구체적인 준비 오류를 반환한다.
3. Workflow 시작 시 baseline commit을 snapshot에 고정한다. 각 Task/Retry는 해당 commit의 detached worktree를 `runs/<run-id>/worktree`에 만든다. 공통 user branch를 checkout하거나 commit/reset/stash하지 않는다.
4. Gateway cwd는 그 worktree, 추가 writable root는 **해당 Run outputs 하나**다. Git common dir, 다른 worktree, 원본 프로젝트, control.db/inputs/확정 Artifact는 writable root에 넣지 않는다. 모델은 소스 파일을 편집하며 Git commit/branch/merge 등 metadata 수정은 필요하지 않다.
5. 기존 고정 RULES의 “artifacts/에 저장”은 Git 모드와 맞지 않는다. 실행별 지시로 정확한 output_root를 전달한다. 프로젝트 tracked `AGENTS.md`를 Backend 파일로 덮지 않고 별도 developer instructions/관리 snapshot의 hash를 기록한다.
6. Backend는 terminal에 base commit 대비 tracked 변경의 binary-safe patch와 안전하게 읽은 untracked 신규 파일 목록/내용을 수집한다. `changes.patch`, `changes.json`(경로, 변경종류, hash, base commit), `new-files.zip`을 Artifact 후보로 만든다. tracked 변경은 `git diff --binary <base>`로 staged/unstaged 모두 포함한다. 신규 파일은 링크/특수 파일/크기 검증을 거쳐 상대 경로만 가진 ZIP으로 묶고 목록/hash를 changes.json에 기록한다. ignored 파일은 자동 산출물에서 제외한다.
7. 사용자 Output Contract는 명시적 deliverable에 적용한다. 위 세 파일은 Backend 산출물이며 `system/git/...` 예약 namespace에 둔다. Git 모드를 저장할 때 `git_patch/git_changes/git_new_files` 세 output slot을 예약·명시하여 `TaskRunOutput`으로 동일하게 연결하고 downstream input_rule에서 선택 가능하게 한다. Worker가 예약 namespace/slot을 사용하면 거절한다. 무변경이면 빈 patch/빈 ZIP과 명시적인 changes.json을 생성한다. 이 Backend 전용 patch slot만 0 byte를 허용하고 사용자 필수 파일의 nonempty 규칙은 유지한다.
8. downstream은 위 Artifact를 명시적으로 선택해 읽는다. 이전 Task worktree를 공유하거나 Backend가 자동 apply/merge/unzip하지 않는다. B/C의 동시 수정은 별도 worktree에 남고 통합 Task는 입력 patch/신규 파일을 보고 자신의 worktree에서 작업한다.
9. worktree 경로/기준 SHA/관리 repo 경로는 manifest로 보존한다. 이 단계는 자동 정리/삭제 정책을 만들지 않는다. worktree가 사라졌으면 복구 시 성공으로 추정하지 않는다.

Git 명령은 `shell=False` 인자 배열, timeout, 정규화된 관리 경로로 실행한다. branch/ref/path를 shell 문자열로 삽입하지 않는다. `.git` 파일/common-dir 경계를 명시적으로 검사한다. worktree 기준 Git 명령도 `--git-dir/--work-tree`를 Backend가 보존한 값으로 지정하고 hooks, external diff/textconv, 모델이 바꾼 Git config를 실행하지 않게 한다. 작업복제본 경로 격리만으로 Git metadata 쓰기 격리가 검증되었다고 주장하지 않는다. 새 조합은 §16의 합성 repository 및 제한된 비모델 검증 대상으로 남긴다.

## 12. Library와 Template의 최소 구현

Library Publish는 사용자가 특정 immutable Artifact를 선택하는 명령이다. 성공 Run의 AVAILABLE/non-partial Artifact만 허용하고 Task Artifact면 TaskRun COMPLETED 및 output 확정을 추가 확인한다.

- WORK는 소유 Work만, CATEGORY는 소유 Work의 Category에 속한 Work, GLOBAL은 모든 Work에서 선택 가능하다. Category/Work scope를 payload 임의 값으로 바꿔 소유 범위를 위조하지 못하게 한다.
- 파일을 옮기거나 복제하지 않고 Publication이 기존 immutable Artifact를 가리킨다. 소유 Work의 관리 경로는 안정적으로 유지된다. Archive로 bytes를 삭제하지 않는다.
- 같은 Artifact 재Publish는 scope 변경을 명시적으로 처리하며 과거 consumer manifest/INPUT 관계는 바뀌지 않는다. 새 실행에만 새 scope 검증을 적용한다. 자동 Publish/unpublish/approval workflow는 없다.
- Library 목록은 current Work 기준 사용 가능 항목만 반환한다. 아무 항목도 자동 선택하지 않는다. 단일 Phase 1 실행도 새 artifact_ids 필드로 명시 선택할 수 있다.

Template은 Definition snapshot을 저장하고 새 Work에서 새 WorkflowDefinition/TaskDefinition ID로 복제한다. Dependency/input task reference는 old→new ID로 모두 변환한다. Source/WORK 범위 Artifact/linked path는 다른 Work에 자동 이식하지 않는다. 대상에서 접근할 수 없는 binding은 제거하고 원래 Task/input_key/자료 설명을 `unresolved_bindings`에 저장하여 응답에도 반환하는 **disabled Definition**으로 생성한다. 사용자가 항목별로 다시 선택하거나 명시적으로 제외하고 validation을 통과해야 enabled=true로 저장할 수 있다. 새로고침으로 재선택 항목이 사라지면 안 된다. Category/Global Artifact도 대상 scope를 재검사한다. 실행 이력/Thread/Run/Artifact output을 복제하지 않는다.

## 13. Backend API 변경

기존 `/api/works/.../runs`, Request Retry, Run detail/Steer/Cancel/Resume/reconcile, Artifact preview/download, Source API를 유지한다. 새 mutation에도 기존 session cookie/token/Origin guard를 적용한다.

| API | 요청/응답 핵심 |
| --- | --- |
| `POST /api/works` 확장 | workspace_kind(default MANAGED), linked_workspace_path(nullable). 응답의 path는 관리 root 유지 |
| `GET /api/works/{id}/directory` 확장 | 기존 path/files 유지 + workspace_kind/linked_workspace_path 추가 |
| `POST /api/works/{id}/sources/import` | LINKED 상대 파일 경로 목록 → 검증·복사된 Source ID. 임의 absolute file 읽기 API 금지 |
| `POST /api/works/{id}/workflows` | name/description/tasks/dependencies, 완전한 graph 검증 → Definition+revision |
| `GET /api/works/{id}/workflows` | 활성/비활성 Definition 목록 |
| `GET/PUT /api/workflows/{id}` | 전체 graph 조회/expected_revision 포함 교체. task별 연속 저장으로 중간 불완전 graph를 commit하지 않는다 |
| `POST /api/workflows/{id}/runs` | expected_revision, 선택 workflow_context(source_ids/artifact_ids), Idempotency-Key → 202 WorkflowRun+초기 TaskRun IDs |
| `GET /api/works/{id}/workflow-runs` | 실행/Branch 이력, pagination |
| `GET /api/workflow-runs/{id}` | frozen 설정, 현재 attempt, 전체 attempts, Run 링크, input/output/오류, parent/branch 관계, last_event_id |
| `POST /api/workflow-runs/{id}/cancel` | intent 저장, 대기 Task 취소, active Run interrupt → 202. ACK로 종료 확정하지 않는다 |
| `POST /api/task-runs/{id}/retry` | Idempotency-Key, 동일 snapshot 재시도 → 202 새 TaskRun ID |
| `POST /api/task-runs/{id}/cancel` | 실행 중 취소 또는 FAILED 경로 포기. 이미 terminal이면 상태를 덮지 않고 §6 정책 적용 |
| `POST /api/task-runs/{id}/branch` | instruction, model/effort, 선택 source outputs, output_rule, history_mode, revision mapping → 202 새 WorkflowRun/TaskRun |
| `GET /api/workflow-runs/{id}/events` | Last-Event-ID 또는 after, DB-backed SSE |
| `GET /api/artifacts/{id}/lineage` | direct incoming/outgoing Artifact edge 및 consumer TaskRun, ID 기반 pagination. 복잡한 graph view 불필요 |
| `POST /api/artifacts/{id}/publish` | scope → Publication |
| `GET /api/library?work_id=...&scope=...` | 접근 가능한 PUBLISHED Artifact, metadata/producer |
| `POST /api/workflows/{id}/templates` | 현재 revision의 template 저장 |
| `GET /api/workflow-templates` | template 목록 |
| `POST /api/workflow-templates/{id}/clone` | target_work_id → 새 Definition과 unresolved_bindings |

정의 validation은 422, 없는 ID는 404, revision/idempotency/상태 경합은 409, Runtime catalog 연결 오류는 기존처럼 503이다. 실행 후의 파일 누락은 Task error로 기록한다. 생성 명령은 key scope+canonical request hash를 저장하고 재전송 시 동일 resource를 반환한다. key가 같고 body가 다르면 409다. cancel/publish 같은 set-state 명령도 재전송에 중복 이력을 만들지 않는다.

Idempotency 조회는 현재 실행 상태의 허용 여부 검사보다 먼저 한다. 이미 성공한 Retry 명령을 재전송했을 때 “현재 시도가 FAILED가 아니다”라며 실패시키지 않고 저장된 결과를 돌려준다.

기존 ExecuteBody에 `artifact_ids=[]`를 추가하고 Request에 저장한다. 기존 `queue_run` command fingerprint에도 artifact_ids를 포함하며 Retry/Resume와 Source 선택 검증을 함께 확장한다. 필드를 생략한 Phase 1 요청의 의미는 바뀌지 않는다.

Workflow 실행 생성은 snapshot+TaskRun들을 한 transaction으로 만든 뒤 202를 반환한다. 아직 없는 Run ID는 null이며 소비자가 가짜 Run을 기대하게 하지 않는다.

기존 Run 화면에서 Task-owned Run을 발견하면 task_run_id/workflow_run_id를 응답에 추가한다. `/api/requests/{id}/retry`, `/api/runs/{id}/resume`는 Task-owned 대상에 409와 Task API 안내를 반환하여 Scheduler를 우회하지 못하게 한다. Task-owned Run cancel은 Task cancel service로 위임하고 Steer는 기존 검증을 유지한다. 일반 Phase 1 Run의 동작은 그대로다.

## 14. Event 흐름과 Frontend

### 14.1 하나의 Event Store

`add_event(db, run_id, type, payload, *, workflow_run_id=None, task_run_id=None, dedupe_key=None)`로 호환 확장한다. Task Run의 Runtime event는 DB lookup/cached immutable ownership mapping으로 Workflow/Task ID를 추가한다. SDK 타입을 UI에 전달하지 않는다.

```text
Gateway normalized event → Run service transaction → Event commit → Run/Workflow SSE
Run terminal → Artifact/Contract finalizer transaction
             → ARTIFACT_CREATED → RUN_COMPLETED → TASK_COMPLETED
             → scheduler wake → downstream READY → QUEUED
             → snapshot/Handoff commit → start Turn → TASK_STARTED
```

필수 Workflow/Task 이벤트: `WORKFLOW_STARTED/COMPLETED/FAILED`, `TASK_BLOCKED/READY/STARTED/COMPLETED/FAILED/CANCELLED`, `ARTIFACT_HANDOFF/CREATED`, `BRANCH_CREATED`, `RETRY_CREATED`.

표현 누락을 막기 위한 추가 이벤트: `WORKFLOW_CREATED/PARTIAL/CANCELLED`, `TASK_QUEUED/SKIPPED/RECONCILED`. payload 공통 필드는 workflow_run_id/task_run_id/run_id(있을 때), task_definition_id, attempt_number, status, execution_round, error code다. ARTIFACT_HANDOFF에는 input_key/Artifact ID/source_task_run_id/hash, ARTIFACT_CREATED에는 생산 ID/output_key/hash를 넣는다.

- 상태 변경과 event는 같은 transaction이다. `Runner.emit()`처럼 새 Session을 열어 먼저 commit하는 helper로 상태 이벤트를 발행하지 않는다.
- 한 Runtime Event row에 Run/Workflow scope를 함께 넣고 두 SSE가 각 scope로 조회한다. 동일 Runtime event를 두 테이블에 이중 저장하지 않는다.
- event IDs는 전역 증가 값이며 scope 내 연속일 필요 없다. `dedupe_key`는 lifecycle에만 사용하고 ACTIVITY delta는 내용 hash로 제거하지 않는다.
- Workflow SSE도 기존처럼 commit된 rows를 id 순서로 replay하고 terminal에서 남은 rows를 drain한 후 닫는다. Retry가 Workflow를 다시 열면 UI가 새 stream을 after=last_event_id로 연결한다.
- Workflow 상세 상태와 last_event_id는 같은 read snapshot에서 읽는다. 조회와 SSE 연결 사이 event는 cursor replay로 수신한다. 프론트는 cursor를 stream scope별로 관리하고 id로 중복 제거한다.

### 14.2 Frontend 최소 변경

- 기존 Request/Run 영역을 유지하고 Work 화면에 Workflow 목록/실행 이력/Template 메뉴를 추가한다.
- Definition 편집은 Task 목록/폼이다. name/instruction/model/reasoning/context/dependencies/input output/workspace mode를 편집하고 전체 graph를 저장한다. drag/drop canvas는 없다.
- Input UI는 “Task 이름 → output slot” 또는 “선택 Artifact”를 사용한다. 사용자가 DB ID/SDK 명령을 입력할 필요가 없다. Output은 상대 파일명과 필수 여부를 설정한다.
- 실행 화면은 Task별 현재 상태, BLOCKED 원인, 실행 중 병렬 Task, model/effort, attempt selector, input/output, 오류, 기존 Run 상세 링크를 보여준다. Runtime completed인데 Contract 실패한 경우를 “필수 결과물 누락”으로 구분한다.
- Retry는 현재 실패 시도에만, Branch는 완료 결과에만 표시한다. Branch UI는 “결과만 사용” 기본값과 지원되는 경우 “현재 대화에서 분기”를 구분한다. 원본 Workflow를 바꾸지 않는다는 동작을 설명한다.
- Work 등록은 관리 Work/기존 프로젝트 연결을 선택한다. 연결 원본과 관리 데이터 위치를 분리 표시하고 Git 모드는 기준 commit/미포함 dirty 파일 안내를 보여준다.
- Artifact preview에 입력/출처/파생 결과 목록과 수동 Library 등록 버튼을 추가한다. Context picker는 Work/Category Library/Global Library로 구분하며 Library는 자동 체크하지 않는다.
- 현재 `state.stream/cursor` 하나를 `runStream/runCursor`와 `workflowStream/workflowCursor`로 분리한다. Workflow 화면에서 Run detail을 열었다고 Workflow 스트림이 종료되지 않게 한다. 화면 이동 시 각각 close하고 선택 ID가 달라진 지연 응답은 무시한다.
- `selectWork(..., true)`/`dashboard()`의 전체 재렌더가 Workflow 편집 입력과 SSE를 초기화하지 않게 한다. 기존 escape/CSP/preview sandbox를 유지한다.

## 15. 구현 순서와 주요 위험

### 15.1 권장 구현 순서

1. **첫 작업: Phase 1 회귀 기준을 유지하면서 0002 모델/마이그레이션과 upgrade 테스트를 만든다.** 기존 데이터, Event ID, Work.path를 보존하고 fresh/upgrade 모두 통과시킨다. 운영 DB에는 아직 시험 migration을 적용하지 않는다.
2. `queue_run`의 transaction 중립 생성 helper, Event scope/동일 transaction 저장, managed path resolver를 분리한다. 동작을 바꾸기 전 Phase 1 테스트를 통과시킨다.
3. Definition DTO/저장/revision/snapshot/순수 DAG 검증, TaskRun 초기 상태와 현재 attempt 조회를 구현한다.
4. Artifact input binding/manifest v2/TaskRunOutput/Contract finalizer/lineage를 구현한다. FakeGateway로 단일 Task의 필수 출력 누락·정상 완료·crash 복구를 검증한다.
5. DagScheduler + TaskRunner를 기존 Runner에 연결한다. 우선 max_parallel_tasks=1로 A→B→D와 실패 downstream BLOCKED를 검증한다.
6. Runner pool/Thread·workspace 잠금/다중 close-recovery를 구현하고 max=2/3의 A→B/C→D를 fake barrier로 검증한다. standalone lane 1도 확인한다.
7. Task Retry/포기/Workflow Cancel/Branch(Artifact 기본, Fork adapter 선택)를 구현한다. 멱등성·terminal 경합을 검증한다.
8. LINKED 등록/import와 관리 Git clone/worktree를 구현한다. synthetic local Git repository에서 원본 비오염/병렬 파일 충돌 방지를 검사한다.
9. Library/Template 최소 API와 범위 검증을 구현한다. cross-Work 명시적 Artifact Context까지 연결한다.
10. Workflow API/SSE/UI를 통합하고 fake backend browser smoke를 수행한다. 기존 Run 화면 회귀를 확인한다.
11. 실제 구현의 모듈/상태/저장 경로와 `docs/architecture.md`를 맞춘다. 실측하지 않은 Fork/Git Sandbox 조합은 VERIFIED로 승격하지 않는다.

### 15.2 구조에 영향을 주는 위험과 방어

| 위험 | 반드시 적용할 방어 |
| --- | --- |
| 기존 전역 serial 보호가 사라짐 | pool 이전에 Thread/경로 잠금, CAS, Run별 reader/handle, 다중 shutdown 구현 |
| Task보다 Run이 먼저 commit되어 실행됨 | enqueue transaction에서 Request/Run/TaskRun linkage/event를 함께 저장 |
| Model의 DONE/Runtime completed만 믿음 | Contract/등록/출력 mapping까지 완료되어야 Task COMPLETED |
| Retry가 옛 실패를 숨기거나 다른 시도 출력을 선택 | append-only attempt, 최대 attempt만 선택, input binding 고정 |
| PARTIAL 상태 후 이벤트 중복/재개 손실 | execution_round별 workflow event dedupe, Retry 후 새 SSE 연결 |
| branch가 기존 graph의 출력 의미를 바꿈 | 별도 WorkflowRun, 명시적 selected Artifact, 원본 terminal rows 보존 |
| fork를 대화 제거 수단으로 오해 | 기본 새 Thread; fork는 대화 상속 선택이며 source 마지막 Turn 검증 |
| 확정 전 output이 downstream에 노출됨 | Contract 통과 transaction 뒤 READY/Handoff 허용 |
| 링크/변조/파일 DB crash 경계 | 기존 안전한 read+hash+atomic 복사, 결정적인 ID, idempotent finalizer |
| Work.path를 LINKED로 치환해 원본 오염 | 관리 root 유지, 별도 linked path, 모든 writer의 resolver audit |
| Git worktree가 원본 .git 또는 관리 DB 쓰기를 허용 | 관리 Git 복제본, cwd/output만 writable, common-dir/원본 제외 |
| Phase 1 Retry/Resume가 Task 실행 규칙 우회 | Task-owned API guard/위임; standalone 경로의 기존 동작 보존 |
| SQLite write lock/event loop 정체 | 짧은 transaction, 무 await, 파일/Git 작업 offload; 새 분산 DB 도입 금지 |
| 대량 Runtime delta와 UI 재렌더 | 기존 bounded payload/replay 유지, 화면 scope별 cursor/stream 분리 |
| Library를 자동 컨텍스트로 주입 | scope는 접근 가능 범위이고 실제 포함은 명시적 선택만 |

Work/Definition archive는 새 실행을 막지만 이미 실행 중인 snapshot을 지우지 않는다. 삭제/자동 정리는 이 단계에서 추가하지 않는다. Sandbox는 쓰기 경계이며 읽기 기밀성 격리나 모델의 지시 준수를 보장하는 것으로 설명하지 않는다.

## 16. 저비용 테스트 계획과 완료 판단

### 16.1 이 설계 작업에서 확인한 내용

- 현재 DB를 읽기 전용으로 조회하여 `alembic_version=0001`, Phase 1 테이블만 존재함을 확인했다. 운영 데이터/schema를 수정하지 않았다.
- `.venv/bin/python -m unittest discover -s tests -v`: 기존 FakeGateway 기반 12개 테스트 통과. 실제 Codex 계정/Thread/모델을 호출하지 않는다.
- 고정 SDK의 공개 thread_fork 소스만 읽었다. 실측 성공으로 간주하지 않는다.
- 문서의 16개 절/로컬 링크/코드 블록을 검사했고, 별도 in-memory SQLite에서 Work 열 추가 CHECK와 WorkflowRun/TaskRun forward-reference FK 구문을 확인했다. 전체 0002 migration의 검증을 대신하지 않는다.
- `probe_codex_runtime.py`, `smoke_live.py`는 실행하지 않았다. runtime-capabilities의 VERIFIED 동시 Thread/Sandbox/Resume/Steer/Interrupt를 다시 검증하지 않았다.

### 16.2 구현 중 자동 테스트

| 계층 | 검증 항목과 증거 |
| --- | --- |
| Migration | 0001 fixture 데이터→0002 후 기존 row/ID/경로/hash 보존, FK/default/index, Event 새 ID, 재기동. pristine 0001 파일 hash 불변 |
| 순수 Scheduler | A→B/C→D, root 복수, cycle/self/cross-definition 거절, 전이적 input A→D, dependency 실패 BLOCKED, 포기 SKIPPED, PARTIAL/FAILED 집계 |
| FakeGateway 병렬성 | B와 C가 모두 start barrier에 도달하기 전 release하지 않는 테스트로 실행 겹침을 증명. max=1/2/3, 여러 Workflow 합계 한도, standalone lane=1, Thread별 중복 start 없음 |
| Task 완료 | DONE이나 terminal completed지만 파일 없음→FAILED, 이름 불일치, empty/대용량/symlink/special file/변조, 성공 output slot mapping, zero-output Phase 1 성공 |
| Handoff | 서로 다른 fake model/effort 전달, 새 Thread ID, prompt에 명시 snapshot 경로와 hash, 이전 history/final_text 미포함, 같은 basename 두 입력 구분 |
| Lineage/Library | INPUT 및 DERIVED_FROM/명시 REVISION_OF 방향·중복 방지, cross-Work scope, 미선택 자료 미포함, 변조/삭제/partial 거절, Source와 Artifact manifest 공존 |
| Retry/Branch | 실패 TaskRun/Run 보존, 새 attempt/Run/Thread/경로, 동일 명령 재전송, 원본 Workflow 불변, Branch artifact 기본, fork public adapter 및 마지막 Turn 검증/실패 처리 |
| Race/crash | enqueue 직후·Turn ACK 전후·파일 rename 후·terminal 저장 후 crash 주입, 중복 finish, cancel vs completion, retry vs cancel, unknown safety_block, event 중복 없음 |
| 재시작/종료 | 여러 활성 fake Run 모두 interrupt/finalize, QUEUED 복구, SUBMITTING 자동 재실행 금지, 이미 완료된 Task 재실행 없음 |
| LINKED/Git | 임시 local Git repo에 A/B worktree 별도 수정, 기준 SHA 고정, 원본 파일·원본 .git 목록/hash 불변, .gitignore 변경 없음, dirty 미포함, diff/new-file artifact, 관리 파일 모두 외부 위치 |
| API/SSE/UI | 한 transaction 상태/event, Last-Event-ID replay, scope별 cursor, terminal drain 후 Retry 재구독, 기존 Run API guard, Template ID 재매핑/unresolved 처리, fake Playwright smoke |

파일/DB/실행 경계 테스트는 독립 임시 디렉터리와 별도 DB를 사용한다. 환경변수는 app.config import 전에 설정하고 FakeGateway를 lifespan 이전에 주입한다. `sleep` 시간 비교보다 asyncio.Event/barrier를 사용한다. mock Session으로 핵심 SQL transaction/unique/FK 검증을 대체하지 않는다.

Git Sandbox에서 새 cwd+output-root 조합이 policy를 정확히 구성하는지는 우선 adapter DTO와 파일 경로 불변식으로 검사한다. 추가 실제 검증이 필요할 경우 **미검증 조합만**, synthetic repository와 dummy control.db를 대상으로 한 비모델 검증을 분리한다. 이미 VERIFIED인 기본 Sandbox 기능을 반복 probe하지 않는다. 실제 모델을 사용하는 반복 E2E를 개발 loop/CI에 넣지 않는다.

FakeGateway 통과는 실제 모든 모델·Fork·Git 도구의 runtime 실측 성공을 뜻하지 않는다. Phase 2 구현 보고서는 자동 검증한 Control Center 동작과 기존 runtime 증거, 아직 미검증인 새 Runtime 조합을 구분해야 한다. 다음 구현 Agent는 모델 호출 없이 위 핵심 경로를 먼저 완성하고, A→B/C→D의 scheduling/Artifact chain/History/UI와 Phase 1 회귀가 함께 통과했는지 확인한다.
