# Execution Settings 최종 Review

검토일: 2026-09-29

기준 문서: [execution-settings-requirements.md](execution-settings-requirements.md).
Architecture, Runtime capabilities, 현재 Run / Task / Gateway / 설정 UI, 운영 DB schema와 Migration을 함께 확인했다.

## 변경사항

| 요구사항 | 구현 결과 |
|---|---|
| 공통 ExecutionProfile | `model`, `reasoning`, `personality`, `permission`, `speed`를 하나의 Pydantic 구조와 Resolver로 관리 |
| 상속 | Global → Category → Work → Run / Task Override. 누락/null은 상속하고 기본값 PUT의 null/누락은 override를 제거 |
| Runtime 지원 값 | Model / Reasoning / Fast 등급은 카탈로그로 검증. 표준 속도는 SDK가 명시한 `default` 사용 |
| Personality | 필드와 snapshot은 제공. SDK 0.158.0에서 선택 기능이 deprecated / 미지원이므로 null만 허용하고 UI 비활성화 |
| Permission | Model과 독립적으로 Read Only / Workspace Write / Full Access를 실제 SDK Sandbox에 매핑. Approval은 deny_all 유지 |
| Run snapshot | Run 생성 시 확정한 전체 profile을 저장하고 Model / Reasoning 컬럼, Manifest, Gateway에 동일하게 전달 |
| 단일 실행 | 신규 / Retry / Resume에 같은 Resolver 적용. 기존 Model / Reasoning 요청 필드는 호환 입력으로 유지 |
| Workflow Task | 정의에는 sparse override를 저장. Workflow 시작 시 Task별 profile을 확정하고 enqueue / Retry는 확정 snapshot 사용 |
| Branch | 부모의 확정 profile에 Branch override 적용. 기존 Branch / Fork 구조와 실행 경로 유지 |
| 최소 UI | 기존 실행 / Task / Branch 입력에 Permission / Speed 선택과 Personality 미지원 표시 추가. 같은 입력 모듈로 범위별 기본값 편집 제공 |
| 이후 재사용 | Query / Handoff / Review / Quick Action이 사용할 공통 Resolver와 Run 생성 계약 마련. 해당 기능 자체는 이번 범위에 추가하지 않음 |

### 구현 위치

- [공통 구조 / Resolver](../app/execution_settings.py), [기본값 / Preview API](../app/execution_settings_api.py).
- [Run 생성](../app/run_service.py), [단일 실행 API](../app/main.py), [Workflow 정의](../app/workflow.py), [Workflow 실행 / Branch](../app/workflow_api.py), [Task enqueue](../app/task_runner.py).
- [Manifest 구성](../app/execution.py), [Runner](../app/runner.py), [SDK Gateway](../app/gateway.py).
- [DB 모델](../app/db.py), [Migration 0005](../app/migrations/versions/0005_execution_settings.py).
- [공통 UI 입력](../app/static/execution-settings.js), 기존 `index.html` / `app.js` / `workflows.js`에 최소 연결.
- [Architecture](architecture.md#15-공통-execution-settings), [Runtime 계약 확인](runtime-capabilities.md#7-execution-settings-계약-확인-2026-09-29) 반영.

## DB와 기존 실행 호환성

운영 `.control-center-state/control.db`를 read-only로 확인했다. 확인 시 revision은 **0004**였으며 Work 2개, Run 4개, TaskDefinition 8개가 있었다. 운영 DB에 이번 migration을 직접 실행하지 않았다.

Migration **0005**는 `execution_defaults` 테이블과 Run / TaskDefinition의 nullable `execution_profile` 컬럼만 추가한다. 기존 row를 backfill하거나 기존 Work / 파일 / 산출물을 삭제·이동하지 않는다. 앱의 기존 startup migration / backup 경로에서 적용된다.

기존 NULL profile Run, Task 정의, Workflow snapshot은 원래 Model / Reasoning과 Workspace Write / Standard 정책으로 해석한다. 수동 Artifact 등록처럼 Runtime을 실행하지 않는 reference Run에는 실행 설정을 강제로 추가하지 않는다.

## 최소 검증 결과

검증: **1개 대표 흐름 통과**, FakeGateway 실행 **2회**, 실제 Codex / App Server / 모델 호출 **0회**.

```sh
.venv/bin/python -m unittest discover -s tests -p test_execution_settings.py -v
```

결과: `Ran 1 test in 2.652s — OK`.

- 임시 DB를 0004에서 0005로 올린 뒤 기존 Run의 모든 기존 컬럼 값과 기존 파일이 그대로인 것을 확인했다.
- Global Model / Speed, Category Reasoning / Permission, Work Permission, 단일 실행 Reasoning override가 Resolve되어 Run / Thread / Turn에 같은 설정으로 전달됐다.
- Workflow Task의 Permission / Speed override가 적용됐다. 실행 슬롯을 점유한 상태에서 Work 기본값을 바꾼 뒤 Task를 시작해도 시작 시 확정한 Model / Reasoning / Permission / Speed가 유지됐다.
- 동일 idempotency key 재요청은 기본값 변경 이후에도 기존 Run과 기존 snapshot을 반환했다.
- 기본값 제거 시 상위 값으로 돌아가는 것과 미지원 Personality / 임의 Speed 값 거절을 확인했다.
- SDK 인자 spy로 Read Only, Full Access, Fork의 Sandbox 매핑과 표준 속도 reset을 확인했다. Turn에서 Sandbox preset을 다시 덮지 않아 Thread의 추가 writable roots를 유지하는 것도 확인했다.
- JavaScript 구문과 HTML ID 중복을 확인했다. 실제 브라우저 검증, 전체 회귀 suite, 실 Runtime 권한·속도 실측은 수행하지 않았다.

대표 검증은 [test_execution_settings.py](../tests/test_execution_settings.py)에 있다. 기존 offline FakeGateway의 메서드 인자와 migration 기대 revision도 새 계약에 맞게 갱신했다.

## 남은 문제와 제한

1. **Personality 선택은 현재 Runtime에서 지원되지 않는다.** 구조와 미지원 처리는 완료했지만 실제 스타일 선택은 Runtime 지원이 추가되어야 활성화할 수 있다. friendly / pragmatic을 별도 프롬프트로 에뮬레이션하지 않는다.
2. **실 계정의 Fast 가용성·효과와 권한 동작은 이번에 실측하지 않았다.** 추가 Speed 선택은 실제 카탈로그에 반환된 등급만 제공한다. 이번 검증은 Resolve / 저장 / Runtime 인자 전달 범위다.
3. **Read Only는 파일 필수 산출물 생성에 사용할 수 없다.** 텍스트 응답 Task는 가능하지만 필수 파일 계약을 만족하지 못하면 기존 계약 검증에서 실패한다.
4. **Full Access는 파일 쓰기 격리를 해제한다.** 명시적으로 선택한 실행에만 적용되며 Workspace Write의 DB·원본 쓰기 차단 보장은 해당 모드에 적용되지 않는다.
5. 운영 DB의 **0005 적용은 앱 재시작 시 필요**하다. 이번 작업에서는 운영 상태를 변경하지 않고 임시 DB에서 additive migration을 확인했다.
