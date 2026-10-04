# Phase 1·2 중간 구현 리뷰

- 검토일: 2026-09-29
- 기준: [Phase 2 implementation plan](phase2-implementation-plan.md), [Phase 1 요구사항](phase1-requirements.md), [Phase 2 요구사항](phase2-requirements.md)
- 대상: `app/`, `tests/`, migration, 브라우저 UI, 기존 Runtime 증거
- 결과: **Phase 1·2의 핵심 기능은 구현되어 있으며, 이번 검토에서 확인한 결함과 빠진 화면 연결을 수정했다. 오프라인 회귀와 브라우저 검증은 통과했다. 실계정 E2E 및 새 Fork/Git Sandbox 조합의 실측까지 완료됐다고 판정하지는 않는다.**

## 1. 현재 진행 상태

| 영역 | 구현·검증 결과 | 근거 |
| --- | --- | --- |
| Phase 1 기본 흐름 | Category/Work, Source/Context, Request/Run, model/effort, 비동기 실행, Steer/Cancel/Resume, Artifact/preview/manifest/history 구현. 기존 12개 회귀 통과 | [Phase 1 테스트](../tests/test_phase1.py) |
| Phase 2 Workflow | 정의 전체 저장/revision, 불변 snapshot, DAG, Task 시도 이력, 병렬 실행, Retry/Branch/Cancel 구현 | [Workflow](../app/workflow.py), [API](../app/workflow_api.py), [Scheduler](../app/scheduler.py) |
| Phase 2 파일 전달 | 명시적 Source/Artifact 입력, Task output slot, immutable 사본, 필수 출력 Contract, lineage 구현 | [Execution](../app/execution.py), [TaskRunner](../app/task_runner.py), [Artifact](../app/artifact_service.py) |
| Phase 2 재사용·작업 공간 | Work/Category/Global 범위, 수동 Publish, Template 복제/재선택, LINKED import, 관리 Git clone/worktree 구현 | [Git workspace](../app/git_workspace.py), [Workflow UI](../app/static/workflows.js) |
| Runtime 수용 검증 | 과거 기본 SDK/Sandbox 증거는 존재. 실계정 Phase 1 전체 E2E 성공 증거는 없음. 이번에는 실제 모델을 호출하지 않음 | [기존 live 기록](runtime-evidence/phase1-live.json), [실패 원인 확인](review-evidence/historical-live-review.json) |

단순 완료율 퍼센트는 사용하지 않았다. 파일 존재, 자동 회귀 통과, 실제 Runtime 실측을 서로 다른 근거로 판단했다.

## 2. Implementation plan 대조

| 계획 절 | 판정 및 확인 내용 |
| --- | --- |
| §1–2 범위·기존 구조 | 단일 FastAPI/SQLite/Gateway를 유지하고 기존 Run 경로에 Task 계층을 연결했다. 예약 실행·Approval·자동 Merge/Publish는 이후 범위다. |
| §3 Entity·서비스 경계 | Definition/Task/Dependency, WorkflowRun/TaskRun/Output, relation/publication/template 모델과 서비스가 존재한다. 현재 attempt는 최대 attempt_number다. |
| §4 Migration | 기존 `0001`, `0002` 파일은 이번 수정에서 변경하지 않았다. 누락된 조회 인덱스는 `0003_review_indexes`로 보완했다. upgrade 전 SQLite backup과 이후 FK 검사 추가. 임시 DB의 기존 row/경로/hash/Event ID 보존 및 재기동 확인. |
| §5 입력·출력·DAG | cycle/self/소속/output slot 검증과 전체 graph revision 저장 구현. `system`, `.git` 출력 경로 거절 보강. Source뿐 아니라 고정 Artifact hash도 시작 snapshot에 저장한다. |
| §6 상태·Scheduler | READY/BLOCKED/QUEUED/RUNNING/terminal과 PARTIAL 집계, 실패 downstream 대기, 명시적 포기/취소 구현. scheduler 예외로 dispatcher가 영구 종료되던 결함 수정. |
| §7 Handoff·lineage | 새 Thread, 명시적 입력 사본/hash, INPUT/DERIVED_FROM/REVISION_OF, 모델별 전달 확인. Artifact 이름 검색이나 이전 final_text를 입력으로 사용하지 않는다. lineage에 ID cursor 조회 추가. |
| §8 Output Contract | Runtime completed와 Task 성공을 구분한다. 필수 파일 누락, 파일 안전성/immutable 수집, slot 매핑 이후 완료. 복사 중단·terminal/Task 불일치 복구 테스트 통과. |
| §9 병렬성·종료 | 공유 슬롯 한도, standalone lane 1, Thread 소유권, Run별 reader/handle, 다중 interrupt 구현. barrier로 B/C 동시 실행, 한도 1/2/3 설정, 여러 Workflow 합계 및 standalone 공존 확인. |
| §10 Retry·Branch | 새 attempt/Run/Thread, 멱등 Retry, 이전 입력 사본 재사용, 별도 단일 Task Branch 구현. Definition 편집 뒤 Branch가 최신 revision을 잘못 기록하던 문제 수정. Fork adapter는 fake 계약 검증 수준이다. |
| §11 LINKED·Git | 원본과 관리 root 분리, 상대 경로 import, 기준 SHA, 관리 clone의 Run별 worktree와 patch/ZIP 구현. 기존 clone에서 detached HEAD commit 준비 누락 보완. 합성 repository에서 원본 파일·`.git` 비변경 확인. |
| §12 Library·Template | 확정 output slot/availability/scope 검증 강화. Template의 미해결 항목이 재복제 과정에서 사라지던 문제 수정. UI에서 항목별 대체 자료 선택 또는 제외 후 저장한다. |
| §13 API | 기존 guard/Run API 유지, Task 소유 Retry/Resume 우회 차단. Work 상세에 사용 가능한 자체 Artifact 후보를 추가해 UI에서 명시적으로 선택 가능하다. |
| §14 Event·Frontend | 상태와 lifecycle event를 같은 transaction에 기록한다. 상세/이벤트 조회에 SQLite read snapshot을 명시했다. Run/Workflow stream은 독립이며 늦은 선택 응답을 무시한다. 편집·Branch 출력·Template·경로 표시/import·lineage 화면 연결을 보완했다. |
| §15 아키텍처 | 구현 전 문구, 전역 직렬 실행 설명, 경로/모듈 설명을 [architecture.md](architecture.md)에 현행화했다. |
| §16 검증 | 임시 DB/FakeGateway 기반 39개 테스트, Chromium 화면 smoke, JS 구문 검사 통과. 아래 실제 Runtime 및 강제 종료 경계는 별도 검증 항목으로 남긴다. |

### 설계 문구와 실제 구현 방식의 차이

- `0002` 신규 테이블은 고정 SQL DDL로 작성되어 있다. 가변 ORM metadata로 migration을 생성하지 않으므로 기존 revision을 보존했다. 일반 신규 row 기본값은 ORM/service가 채우며, Phase 1 확장 열의 SQL 기본값은 migration에 있다.
- 별도 범용 Workspace 잠금 서비스는 없다. 사용자 지정 cwd를 받지 않고 Backend가 고유 Run ID 하위에 작업 경로를 생성한다. Thread 소유권과 Workflow 명령/finalizer lock, Git 관리 lock을 사용한다.
- `RunService`는 transaction 중립 생성 helper이며, 명령별 검증은 Phase 1 API와 Workflow service에 남아 있다.

## 3. 발견한 결함과 수정

| 우선도 | 수정 전 문제 | 수정 후 동작 / 검증 |
| --- | --- | --- |
| 높음 | scheduler의 저장소 예외 한 번으로 유일한 dispatcher가 종료됨. 기존 테스트는 이 결함 재현을 성공으로 판정 | 예외 로그/health 오류 표시, 기존 실행 소유권 보존, 1초 후 스케줄링 재평가. 테스트를 복구 성공 assertion으로 교체 |
| 높음 | 성공 Task에서 수집만 된 추가 파일도 output slot 확정 없이 Publish 가능. 알려진 unavailable 항목도 Library 목록에 노출 | TaskRunOutput 존재까지 확인. 실패/partial/known missing/modified/unmapped 항목 제외 |
| 높음 | Retry가 이미 고정한 입력에도 현재 Library scope/원본 availability를 다시 적용해 재현 가능한 재시도를 막음 | 기존 INPUT binding/hash 및 이전 Run 사본을 재사용. 공개 범위 변경과 원본 삭제 후 재시도 성공 검증. 새 선택은 현재 scope를 검사 |
| 높음 | SQLite 기본 SELECT 동작만으로 상세 상태와 last_event_id가 같은 read snapshot이라고 보장할 수 없음 | 상세와 SSE 조회에 명시적 read transaction 적용 |
| 중간 | Definition을 편집한 뒤 과거 Task를 Branch하면 과거 설정에 최신 revision 번호가 붙음 | parent WorkflowRun의 definition_revision 보존 |
| 중간 | 미해결 binding이 있는 Template을 다시 저장·복제하면 unresolved 목록이 유실될 수 있음 | Task ID를 다시 매핑하면서 unresolved/name도 보존. reload/reclone 회귀 추가 |
| 중간 | Template UI가 모든 미해결 항목을 한 번에 지우는 버튼만 제공 | Task·자료별 재선택 또는 명시적 제외. 미선택 대체 자료는 거절하고 남은 항목은 저장·재조회 유지 |
| 중간 | 화면에서 같은 Work의 다른 Run/Definition을 빠르게 선택하면 늦은 응답이 최신 화면을 덮음 | 선택 세대 비교, 이동 시 stream/요청 무효화. 브라우저에서 응답 순서를 반대로 완료시켜 검증 |
| 중간 | LINKED 원본/관리 위치·Git 기준 정보·Source import와 Branch output 변경의 화면 연결 부족 | 경로 분리 표시, 기준 SHA/dirty 제외 설명, 상대 경로 import 폼, Branch output 편집 추가 |
| 중간 | 기존 bare clone이 branch ref에 없는 새 detached commit을 가져오지 못함 | 동결된 local commit만 명시적으로 fetch. 다른 HEAD로 대체하지 않음 |
| 중간 | upgrade 전 일관된 DB 백업 및 계획된 복합/역방향 인덱스 누락 | SQLite backup API, FK check, append-only `0003` 인덱스 migration 추가 |
| 낮음 | event의 round/output slot 정보와 reconcile 이전 오류가 부족 | 공통 Task event metadata, ARTIFACT_CREATED.output_key, TASK_RECONCILED.previous_error 추가 |
| 낮음 | Artifact 출처 화면이 raw JSON만 표시하고 자체 Work 결과물을 선택하기 어려움 | 출처/파생/버전/consumer 목록과 이동 버튼, 검증된 Work 결과물 picker 추가. 자동 선택하지 않음 |

## 4. 검증 결과와 재현 방법

| 검증 | 결과 | 증거 |
| --- | --- | --- |
| 수정 전 offline baseline | 31개 통과. 단, scheduler 결함 재현 테스트가 포함되어 있어 완료 근거로는 불충분했음 | 검토 시작 시 실행 결과 |
| 수정 후 offline suite | **39개 통과** — Phase 1 12개 + Phase 2/검토 27개 | [전체 로그](review-evidence/phase1-phase2-unittest.txt) |
| 실제 Chromium + TestClient/FakeGateway | **PASS**, page error 0 | [브라우저 결과](review-evidence/browser-smoke.json), [재현 코드](../tests/browser_review.py) |
| JS 구문 | `app.js`, `workflows.js` 통과 | `node --check` |
| Migration 불변성 | 검토 전 사본과 비교하여 `0001`, `0002` 변경 없음 | 새 변경은 `0003_review_indexes.py` |
| 실제 계정/모델 호출 | 이번 검토에서는 0회 | Runtime probe/live smoke 미실행 |

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tests/browser_review.py
node --check app/static/app.js
node --check app/static/workflows.js
```

브라우저 smoke는 실제 HTML/JS와 API를 사용하며, Playwright HTTP route를 TestClient로 전달한다. SSE 응답은 heartbeat로 대체하여 두 stream 객체의 공존과 화면 동작을 확인한다. 실제 HTTP 연결의 장시간 스트리밍/재접속 시험을 대신하지 않는다. DB 기반 SSE cursor replay는 별도 API 테스트로 검증한다.

테스트는 독립 임시 root/DB와 FakeGateway를 사용했다. 프로젝트의 운영 DB에는 migration을 적용하지 않았다. 서버를 다음 시작할 때 필요한 upgrade가 수행되며, 이전 revision이 있으면 일관된 백업 파일을 먼저 생성한다. 패키지에서 출력하는 `httpx`/Starlette deprecation 경고는 남아 있으며 테스트 실패는 아니다.

## 5. 남은 수용 검증

1. **실계정 Phase 1 전체 E2E 성공 확인**: 기존 `runtime-evidence/phase1-live.json`은 `passed=false`다. 당시 임시 DB를 읽기 전용으로 확인한 결과 실제 Turn의 실패 원인은 `codexErrorInfo=usageLimitExceeded`였다. 이는 당시 사용량 한도 오류이며 현재 계정 상태를 뜻하지 않는다. 인증/catalog/브라우저 등록/202까지의 과거 성공만으로 전체 완료를 주장할 수 없다.
2. **Fork와 Git Sandbox 실측**: adapter/FakeGateway 계약과 로컬 Git 비오염 테스트는 통과했다. 실제 모델 도구의 `cwd + outputs writable root` 조합에서 Git common-dir/원본/DB 쓰기가 차단되는지와 실제 Fork 성공은 이번 검증 범위 밖이다. 기존 기본 Sandbox VERIFIED 표시는 새 조합의 성공 증거가 아니다.
3. **강제 종료와 전송 경계**: SIGKILL/OS 재부팅/orphan 프로세스, 실제 Turn ACK 전후 crash, 장시간 실제 SSE 재연결은 추가 수용 검증이 필요하다. 현재 자동 테스트는 FakeGateway와 DB/파일 경계 복구 사례를 검증한다.

따라서 다음 단계는 기능을 처음부터 다시 구현하는 작업이 아니라 위 Runtime 수용 검증을 완료하는 것이다. Phase 3·4 기능은 이번 수정 범위에 포함하지 않았다.
