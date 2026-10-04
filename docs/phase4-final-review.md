# Phase 4 최종 Review

- 작성: 2026-09-29
- Source of Truth: [phase4-requirement.md](phase4-requirement.md).
  요청한 `phase4-requirements.md`는 저장소에 없으므로 실제 존재하는 동일 Phase 요구사항 문서를 사용했다.
- [Architecture](architecture.md), [Runtime Capabilities](runtime-capabilities.md), 현재 Schema / Migration,
  Gateway, Run / Workflow / Execution Settings, Source / Artifact / Library 실행 경로를 확인했다.
- 별도 중간 산출물은 생성하지 않았다.

## 변경사항

| 기능 | 구현 결과 |
|---|---|
| Thread 관리 | Work당 복수 ThreadRecord, Runtime ID 연결, Lifecycle, 부모 관계, Turn 수 / Usage |
| Continue / Resume | 기존 Runtime Thread에 새 Run 생성. 활성 실행 중 중복 제출과 폐기된 Query의 Resume 차단 |
| Fresh New | 기존 Runtime History를 상속하지 않는 Thread. 명시적 Context와 Resource 기본값 선택 |
| Compact | 동일 App Server의 공개 Runtime compact 호출. 새 compaction 항목과 terminal 확인 후 Continue. 불확정 상태 차단 / 확인 API |
| Side Query | Fresh ephemeral Thread, Read Only, Artifact OFF, 최소 명시 Context. Write / Artifact는 명시 선택 |
| Query 처리 | 폐기, 선택한 짧은 결론만 원래 Thread에 전달, Decision / Knowledge / Artifact 등 승격 |
| Exact Fork | 기존 SDK fork 재사용, 마지막 terminal Turn 검증, 원본 보존, FORKED_FROM 기록 |
| Context Pack | 직접 선택 / Backend 후보 제안, 목표·완료·진행·잔여·결정·Blocker·다음 지시, 자료 snapshot, 미리보기 / 확인 |
| Pack Version / Freshness | 불변 버전, ID / hash / version / bytes 보존, CURRENT / CHANGED / MISSING / STALE 표시 |
| Handoff | 검토한 Pack을 Fresh Thread에 전달, HANDOFF_FROM / Handoff 기록, 성공 후 선택적으로 부모 SUPERSEDED |
| Promotion / Scope | Backend Resource 저장, WORK 기본, THREAD / CATEGORY / GLOBAL 명시 선택. Artifact는 기존 등록 / Publish 서비스 재사용 |
| Context 선택 | Resource 기본 포함 / 제외, Run별 추가 / 제외, Work / Category / Global 범위 검사, Published Library Artifact 재사용 |
| Budget / Dedup / Inspector | 파일 크기 기반 근사 예산, 초과 명시 확인, 중복 hash 제거와 alias 출처 추적, 실제 제공 Context 표시 |
| 기존 실행기 | 공통 Run 생성 / Profile Resolver / Runner / Task execution 사용. Workflow 상태 관리 구조 유지 |
| 최소 UI | 기존 Work 화면에 대화 액션·관계 목록·자료 선택·Pack 검토·질문 처리·Inspector 추가 |

### 주요 코드

- [Schema](../app/db.py), [0007 Migration](../app/migrations/versions/0007_conversation_context.py)
- [Context 서비스](../app/conversation.py), [Conversation API](../app/conversation_api.py)
- [공통 Run 생성](../app/run_service.py), [Context 전달](../app/execution.py)
- [Runner](../app/runner.py), [Gateway](../app/gateway.py), [Task 실행](../app/task_runner.py)
- [최소 Conversation UI](../app/static/conversations.js)

### 저장과 호환성

`0007`은 테이블 / 컬럼 / 인덱스를 추가한다. 기존 Work, Source, Artifact, Run의 내용이나 위치를
변경하지 않고 기존 Thread도 자동 backfill하지 않는다. 사용자가 기존 대화에 명령을 실행하면 연결 메타데이터만 생성한다.
Pack / Resource는 Backend DB에 저장하며 프로젝트 파일을 강제로 생성하지 않는다.
Run 입력은 기존 Runtime 입력 스냅샷 경로로 전달한다.

Query 답변은 사용자 확인을 위해 최대 24시간 임시 보류하며 일반 Run / Request History에서 숨긴다.
결과 처리 후 질문 / 답변 / 입력 스냅샷과 DB·파일 Manifest의 질문 본문을 제거한다.
사용자가 명시적으로 생성 / 승격한 Artifact와 Resource는 보존한다.

Continue와 Fork는 Runtime History를 사용하고, Query / Handoff는 전체 대화를 복사하지 않는다.
Context Manifest는 실제 제공한 자료를 기록한다. 모델의 내부 전체 Context나 과거 대화 Token 수를
정확히 보여 주는 것으로 해석하지 않는다.

## 최소 검증 결과

실제 Codex / 모델 호출: **0회**.

[대표 테스트](../tests/test_phase4.py)를 임시 DB / FakeGateway로 실행했다.
최종 결과: **1 test, PASS, 5.115초**, Fake Turn 10회. 별도의 전체 Regression Suite나 실제 Runtime 반복 실측은 하지 않았다.

확인한 흐름:

1. New → Continue: 동일 Thread, 별도 Run. 완료 이후 같은 idempotency key 재요청도 원래 Run 반환.
2. 최신 완료 지점 Fork: 새 Thread, 원본 독립 유지.
3. Query: fresh / ephemeral / Read Only, 기본 Artifact 없음, 일반 History 제외.
4. Query 결과의 Category Decision / Work Artifact 승격.
5. 다른 Work에서 Category Resource를 Pack에 선택, v1 / v2 분리, Resource 변경 감지.
6. 과거 Pack v1의 실제 입력 bytes 유지, 미검토 Pack 실행 거절.
7. Handoff: Fresh Thread, 원본 보존 / SUPERSEDED, 동일 자료 중복 제거와 출처 alias.
8. Compact 후 Continue: 동일 Fake Thread, compaction 완료 이후 실행.
9. Query의 짧은 결론만 메인 Thread로 전달; Discard 후 DB / 저장된 Manifest에서 질문 제거.
10. 예산 초과 / 다른 Work의 private Resource / 오래된 Run 시점 Fork 거절.
11. 기존 Workflow Task가 같은 Run / Context compiler로 범위별 기본 Resource를 전달.

공개 SDK 인자 spy에서 ephemeral / read-only 전달을 확인했다.
Compact adapter 별도 spy에서 공개 compact 호출과 동일 Thread의 새 compaction terminal 확인을 검증했다.
Python 수정 모듈의 구문 확인과 `node --check`도 통과했다.
기존 테스트의 Migration head 기대값만 `0007`로 갱신했다.

## 남은 문제 / 제한

- **운영 DB는 아직 `0004`**: 읽기 확인 시 Work 2개, Run 4개, WorkflowRun 0개였다.
  이번 작업에서 운영 DB를 수정하지 않았다. 앱 재시작 시 기존 백업 / Alembic 경로가 `0005`~`0007`을 적용한다.
- **새 Runtime 동작은 실측하지 않음**: fork / ephemeral / 수동 compact는 공개 SDK 연결과 Fake / spy 계약으로 확인했다.
  기존 VERIFIED resume / sandbox 결과를 이 기능들의 새로운 성공 증거로 확대하지 않았다.
- **Compact 완료 확인의 Runtime 의존성**: 공개 Thread History에 새 contextCompaction terminal이 나타나야 한다.
  180초 내 확인되지 않으면 UNKNOWN으로 잠그며 자동 재호출하지 않는다. History 확인 또는 Fresh Handoff로 진행한다.
- **Exact Fork는 현재 최신 완료 지점**: 임의의 오래된 Turn으로 History를 자르는 UI / API는 제공하지 않는다.
  과거 결과는 검토한 Context Pack으로 전달한다.
- **Budget은 근사값**: UTF-8 bytes / 파일 크기 기반이며 Runtime History의 정확한 비용을 포함하지 않는다.
  긴 대화 / Usage / compaction 경고와 함께 사용해야 한다. Run 생성 시 선택 자료의 예산을 검사하고,
  Task dependency가 추가된 최종 입력과 프롬프트 크기는 Manifest에서 다시 계산해 경고한다.
- **UI 확인 범위**: JavaScript 구문과 API 기반 대표 흐름을 확인했다. 실제 브라우저 시각 검증과
  전체 Phase 1~3 Regression 반복은 수행하지 않았다. 최종 Thread Tree / Dashboard 디자인은 요청 범위에서 제외했다.
