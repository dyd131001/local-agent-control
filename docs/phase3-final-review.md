# Phase 3 최종 Review

기준일: 2026-09-29

Source of Truth: [phase3-requirements.md](phase3-requirements.md).
해당 문서가 언급하는 `phase3-requirements-v2.md`는 현재 저장소에 없어, 실제 존재하는 기준 문서의 요구사항과 마지막 검증 정책을 적용했다.
Architecture, Runtime capabilities, Phase 1 / Phase 2 코드, Workflow / Scheduler / Run / Artifact와 DB Migration을 함께 확인했다.

## 구현 결과

| 기능 | 변경사항 |
|---|---|
| Task 검토 정책 | AUTO / REVIEW_AFTER / APPROVAL_REQUIRED를 정의에 저장하고 Workflow 실행 snapshot으로 고정. 기존 정의와 누락된 과거 snapshot은 AUTO |
| Approval Gate | Scheduler의 dependency 판정, Task enqueue, queued Run dispatch에서 필수 승인을 검사. 미승인 Artifact를 다른 실행의 입력으로 선택하는 우회도 차단 |
| 상태 분리 | TaskRun은 실행 성공 시 COMPLETED 유지. Approval / ArtifactReview / ArtifactPublication은 별도 상태로 보관. 필수 승인이 남은 Workflow는 WAITING_APPROVAL |
| Approval Inbox | 대기 검토 목록, 산출물과 최종 응답 확인, Approve / Reject / Request Revision / Approve & Publish 제공 |
| 중복 처리 | DB `BEGIN IMMEDIATE`, 공통 command lock, 현재 Task 시도와 decision digest 검증. 동일 승인 요청은 기존 결과를 반환하고 downstream을 중복 생성하지 않음 |
| Approve / Publish | 승인 전에 산출물 hash 확인. Approve만으로 Publish하지 않음. Approve & Publish는 기존 Publish 서비스와 DB transaction을 재사용 |
| Reject | 실행 성공 기록을 유지하면서 검토 결과를 REJECTED로 저장. 필수 승인 소비자 진행을 막고 해당 경로를 SKIPPED로 집계 |
| Revision | 새 Task 시도 / Run / Artifact 생성. 원본과 입력 binding을 보존하고 REVISION_OF 연결. 미실행 downstream은 새 승인 대기. 소비자가 이미 진행한 REVIEW_AFTER는 별도 Workflow로 분기 |
| Pause / Resume | 영속 paused 플래그로 새 enqueue와 queued Run dispatch 차단. 진행 중 Task는 정상 마무리하는 soft pause. Resume는 미실행 DAG를 재개 |
| Schedule | ONE_TIME / RECURRING, 시작 시각, 분 단위 반복 간격, 활성화 / 비활성화, 실행 기록. Cron 입력 없이 기존 Engine에 새 WorkflowRun 생성 요청 |
| Schedule 복구 / Misfire | 고유 occurrence와 영속 claim, 다음 시각 advance, WorkflowRun 연결을 transaction으로 처리. FIRE_ONCE는 놓친 회차를 한 번으로 합치고 SKIP은 grace 초과 회차를 기록 |
| Checkpoint | definition snapshot, Task 시도, 출력 ID/hash, 검토 상태, Context Manifest와 최종 응답을 DB에 보관 |
| Delayed Resume | 미래 시각 또는 지연 시간 지정. 완료된 Task의 Checkpoint로 별도 WorkflowRun / TaskRun / Run 생성. 기존 Run을 부활시키지 않고 parent 관계와 checkpoint_id 기록 |
| Recovery | 기존 Runtime reconciliation을 유지하고 승인 대기, Pause, Schedule claim과 pending 지연 예약을 DB에서 이어서 처리. 미확정 Runtime 결과는 기존 safety block으로 차단 |
| Monitoring / 최소 UI | 검토 정책, Inbox, 예약 폼, Pause / Resume, 시간 후 이어하기와 상태 갱신 추가. Dashboard에는 진행 / 승인 대기 / 활성 예약 / 지연 예약 현황만 추가 |

Approval / Schedule / Revision이 모델을 직접 호출하는 별도 경로는 만들지 않았다.
모든 실행은 기존 **Workflow Engine → DAG Scheduler → Run Service → Runner → Codex Gateway**를 사용한다.
Planner, 자동 Model Routing, Vector DB와 최종 UI / Dashboard 디자인은 추가하지 않았다.

## 구현 위치

- [운영 상태 / 승인 / Revision / Checkpoint](../app/workflow_operations.py).
- [Inbox / decision / Pause / Schedule / Delayed Resume / Monitoring API](../app/workflow_operations_api.py).
- [영속 시간 트리거](../app/workflow_triggers.py).
- [Workflow 정의](../app/workflow.py), [실행 API / 예약 공통 Engine](../app/workflow_api.py), [DAG Scheduler](../app/scheduler.py), [Task / Run 연결](../app/task_runner.py).
- [Run dispatch / 복구](../app/runner.py), [Manifest](../app/execution.py), [Artifact admission / Publish](../app/artifact_service.py).
- [DB 모델](../app/db.py), [Migration 0006](../app/migrations/versions/0006_workflow_operations.py).
- [운영 UI 연결](../app/static/workflow-operations.js)과 기존 화면의 최소 수정.
- [최종 Architecture](architecture.md#16-phase-3-workflow-운영), [Runtime 검증 범위](runtime-capabilities.md#8-phase-3-앱-상태-전이-확인-2026-09-29).

## 권한과 기존 구조

Runtime Permission Approval과 Workflow Artifact Approval은 서로 다른 개념으로 유지했다.
Worker에는 기존 Read Only / Workspace Write Sandbox와 deny_all을 적용하고, Approval / Schedule / control DB를 writable root에 넣지 않는다.

**Full Access는 신규 실행과 queued Run dispatch에서 차단한다.** SDK에는 존재하지만 Phase 3의 제어 DB 보호 요구와 충돌하므로 기본값 저장과 선택 UI에서도 제한했다. 과거 Profile과 기존 Run 기록을 자동 변경하지 않는다. 이전에 저장한 Full Access 기본값이 있다면 사용자가 제한된 권한으로 바꿔야 새 실행을 시작할 수 있다.

기존 Run / Workflow의 실행 이력과 Artifact 파일을 삭제하거나 이동하지 않았다. Revision / Delayed Resume는 새 실행 이력과 새 출력으로 연결한다.

## DB 확인과 적용

운영 `.control-center-state/control.db`를 read-only로 확인했다.
확인 당시 revision은 **0004**, Work 2개, Run 4개, TaskDefinition 8개, WorkflowRun 0개였고 Phase 3 테이블은 없었다.
운영 DB에는 이번 migration을 직접 실행하지 않았다.

Migration **0006**은 운영 테이블 6개(`approvals`, `artifact_reviews`, `workflow_checkpoints`, `workflow_schedules`, `schedule_fires`, `delayed_resumes`)와 Task 검토 정책 / 시도 override / Workflow Pause 컬럼을 추가한다.
기존 앱 시작 시 backup / migration 경로로 **0004 → 0005 → 0006**을 적용한다. 기존 정의는 AUTO로 유지하고 과거 snapshot은 누락 필드를 호환 해석한다.

## 최소 검증 결과

[대표 검증](../tests/test_phase3.py):

```sh
.venv/bin/python -m unittest discover -s tests -p test_phase3.py -v
```

성공 결과: **1개 흐름, 3.519초, OK**.
성공 흐름의 Fake Turn은 **7회**, 실제 Codex / App Server / 모델 호출은 **0회**다.
첫 확인에서 Schedule 이벤트 기록의 import 누락을 발견해 수정하고 동일 대표 흐름만 재실행했다. 전체 회귀 suite와 기존 Runtime capability 실측은 반복하지 않았다.

확인한 전이:

- Phase 1 단일 실행과 Phase 2의 A → B/C → D 구조 유지.
- A의 APPROVAL_REQUIRED에서 정지하고 다른 Task의 Run이 생성되지 않는 것, 미승인 출력의 Publish / 입력 선택 차단.
- Pause 상태에서 Revision enqueue 차단 → Resume → 새 A Run / Artifact → 재승인 → B/C → D 진행.
- 원본 파일 bytes 보존, 새 Artifact ID와 REVISION_OF 관계.
- 동시 중복 Approve 요청의 동일 결과와 downstream 시도 중복 생성 방지.
- Approve 직후 Publication 없음, 별도 Publish 성공, REVIEW_AFTER가 downstream 완료를 막지 않는 것.
- ONE_TIME / RECURRING의 새 WorkflowRun 생성, 고유 occurrence 재사용, 활성 / 비활성, FIRE_ONCE coalescing과 SKIP 기록.
- Backend 재시작 2회에서 PAUSED / 승인 대기 / committed claim / pending Delayed Resume 보존과 기존 Run 재실행 방지.
- 5시간 지연을 테스트 시계로 전진한 뒤 새 Run ID, parent Run 관계, delayed_resume operation과 Checkpoint Manifest 확인.
- Reject 후 검토 상태와 완료 Task 상태 분리, 거절 출력 Publish 차단.
- Monitoring 데이터, 임시 DB revision 0006과 foreign key 검사, HTML ID 중복 및 Python / JavaScript 구문 확인.

Schedule 검증은 enqueue를 일시 차단하고 **WorkflowRun 생성까지** 확인했다.
5시간을 실제로 기다리지 않았으며 실 Runtime을 호출하지 않았다.
Approve & Publish의 결합 경로와 나머지 예외 처리는 구현 / transaction 경로를 검토했고, 모든 버튼 조합이나 실제 브라우저를 별도로 반복 검증하지 않았다.

## 남은 문제와 운영 범위

1. **운영 DB 적용과 앱 재시작이 필요하다.** 이번 검증은 임시 DB에서 수행했으며 운영 DB 상태를 변경하지 않았다.
2. **Pause는 실행 중 Task를 즉시 중단하지 않는다.** 새 dispatch를 막고 진행 중 작업을 마무리한다. 즉시 종료가 필요하면 기존 Cancel을 사용한다.
3. **Delayed Resume는 완료된 Task의 이어하기다.** 기존 Workflow 전체를 재생하거나 terminal Run을 다시 활성화하지 않는다. 새 실행에도 원래 검토 정책을 적용한다.
4. **시간 트리거는 Backend가 실행 중일 때 처리된다.** 중단 중 놓친 예약은 재시작 후 misfire 정책으로 처리하며 별도 OS 예약 데몬은 추가하지 않았다. 반복 Workflow가 겹치면 기존 Run pool이 실행 슬롯을 제한한다.
5. **없는 파일이나 변경된 Checkpoint 입력은 임의 복원하지 않는다.** hash / availability 오류를 기록하고 새 실행의 실패 원인을 노출한다. 미확정 Runtime 상태나 준비되지 않은 Work는 예약을 대기시킬 수 있다.
6. 실제 모델, 실 계정별 Fast, Runtime 권한 경계의 추가 실측과 전체 회귀 / 실제 브라우저 검증은 이번 최소 검증 범위에 포함하지 않았다. UI와 Dashboard 최종 디자인은 이후 단계로 남는다.
