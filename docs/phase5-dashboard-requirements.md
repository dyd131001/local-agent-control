# Phase 5 — Operations Dashboard Requirements

## 목적

Phase 5는 Control Center 전체의 실행 상태를 한눈에 파악하고
필요한 작업으로 이동할 수 있는 Operations Dashboard를 만든다.

Dashboard는 새로운 실행 엔진이 아니다.

Phase 1~4에서 만들어진 상태와 기능을 집계하고 연결하는 운영 계층이다.

## Dashboard가 답해야 하는 질문

- 지금 무엇이 실행 중인가?
- 무엇이 대기 중인가?
- 무엇이 실패했는가?
- 무엇이 사용자 확인을 기다리는가?
- 어떤 Workflow가 어디까지 진행됐는가?
- 어떤 Schedule이 예정되어 있는가?
- 현재 Context 사용 상태는 어떤가?
- Runtime / Usage 상태는 어떤가?
- 최근 어떤 결과물이 생성됐는가?

## Dashboard 상태

최소 다음을 집계한다.

- RUNNING
- QUEUED
- FAILED
- WAITING_APPROVAL
- PAUSED
- SCHEDULED
- RECOVERY_REQUIRED
- CONTEXT_WARNING

## Runtime Status

가능한 Runtime capability 범위에서 다음을 표시한다.

- 현재 Model
- Reasoning
- Permission
- Runtime 상태
- Context 상태
- Usage / Rate limit 정보

Runtime이 제공하지 않는 값은 추정하지 않는다.

## Codex 기능 분류

Codex 기능을 Slash Command 이름 그대로 UI에 노출하지 않는다.

### Execution Settings

- model
- reasoning
- personality
- permissions
- fast / speed

### Conversation / Context

Phase 4에서 관리한다.

- new
- resume
- compact
- side
- fork
- handoff

### Dashboard / Status

- status
- usage
- runtime 상태
- context warning
- schedule / approval / recovery 상태

### Work Tools

작은 단위 작업은 Work의 별도 작업 도구 영역에서 관리한다.

초기 기능:

- Diff
- AI Review

향후 같은 성격의 기능을 이 영역에 확장할 수 있다.

## Diff

Diff는 가능하면 AI Run 없이 Git 변경사항을 조회한다.

표시:

- 변경 파일
- 추가 / 삭제
- 변경 내용

## AI Review

Review는 기존 Run Service와 Execution Settings를 재사용한다.

기본 권한은 Read Only를 권장한다.

검토 범위:

- 현재 변경사항
- 선택 파일
- 필요 시 Branch 비교

결과는 필요하면 Artifact로 저장할 수 있다.

## Quick Action 원칙

Diff / Review 때문에 별도의 새로운 실행 시스템을 만들지 않는다.

AI가 필요한 Action은 기존 Request / Run 구조를 재사용한다.

AI가 필요하지 않은 Action은 Backend Tool로 처리한다.

## Dashboard Aggregation

Dashboard가 각 기능의 DB를 직접 임의 해석하지 않도록
운영 상태를 반환하는 집계 Service / API를 둔다.

Dashboard UI는 이 계약을 사용한다.

## Goal

Runtime에서 Goal 기능을 안정적으로 사용할 수 있다면
Work의 현재 Goal을 Dashboard에 표시할 수 있다.

지원되지 않는 경우 Phase 5 필수 구현으로 강제하지 않는다.

## UI

이번 단계에서는 Dashboard 최종 디자인을 하지 않는다.

Dashboard가 필요로 하는 Backend 상태와 API,
Work Tools 기능을 먼저 구현한다.

최종 시각 UI는 전체 UI 개편 단계에서 구현한다.