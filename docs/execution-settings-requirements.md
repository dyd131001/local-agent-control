# Execution Settings Requirements

## 목적

단일 실행, Workflow Task, Query, Review 등 Codex를 사용하는 모든 실행이
같은 실행 설정 모델을 사용하도록 한다.

UI 전체 개편 전에 실행 설정의 데이터 구조와 상속 규칙을 고정한다.

## 실행 설정

최소 다음 설정을 지원한다.

- Model
- Reasoning
- Personality
- Permission
- Fast / Speed Mode

Runtime이 실제 지원하는 값만 사용한다.
지원하지 않는 값을 UI나 Backend에서 임의로 만들어내지 않는다.

## Execution Profile

실행 설정은 하나의 공통 개념으로 관리한다.

ExecutionProfile
- model
- reasoning
- personality
- permission
- speed / fast_mode

## 상속

기본 상속 순서:

Global Default
→ Category Default
→ Work Default
→ Run / Task Override

하위 설정이 없으면 상위 기본값을 사용한다.

사용자는 필요한 실행에서만 Override할 수 있다.

## 적용 대상

같은 Execution Settings 구조를 다음에서 재사용한다.

- 단일 실행
- Workflow Task
- Phase 4 Query
- Phase 4 Handoff 후 실행
- 향후 Review / Quick Action

각 기능마다 Model / Reasoning 설정 구조를 따로 만들지 않는다.

## Run Snapshot

실행이 시작되면 최종적으로 Resolve된 설정을 Run에 Snapshot으로 남긴다.

이후 Work 기본 설정이 바뀌어도 과거 Run의 실행 설정은 바뀌지 않는다.

## Permission

Permission은 Model과 별도 설정이다.

최소한 다음 성격을 구분할 수 있어야 한다.

- Read Only
- Workspace Write 허용
- Runtime이 지원하는 추가 권한 Profile

Runtime capability와 맞지 않는 권한을 임의로 에뮬레이션하지 않는다.

## Personality

Personality는 응답 스타일 설정으로 취급한다.

모델 능력이나 Workflow 역할과 동일한 개념으로 취급하지 않는다.

## UI

이번 단계에서는 최종 UI를 만들지 않는다.

현재 화면에서 설정을 사용할 수 있는 최소 연결만 제공한다.

최종 UI 구성은 전체 UI 개선 단계에서 수행한다.