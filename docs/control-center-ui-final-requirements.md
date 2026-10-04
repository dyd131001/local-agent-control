# Control Center Final UI Requirements

## 목적

Phase 1~5에서 구현된 기능을 하나의 일관된 정보 구조로 통합한다.

Backend 기능을 다시 설계하지 않는다.

## Application

- Dashboard
- Category / Work Navigation

## Work

상단:

- Work 이름
- Category
- Workspace
- 실행 상태

Tabs:

- 개요
- 실행
- Workflow
- 자료
- 결과물
- 작업 도구
- 일정
- 검토
- 활동

## 실행

다음 행동을 구분한다.

- 새 요청
- 기존 대화 계속
- 같은 요청 다시 실행
- 질문하기
- 분기
- Compact
- 새 대화로 넘기기

Execution Settings는 공통 Component를 사용한다.

## Workflow

좌측 Flow + 우측 Task Detail 구조.

Task Detail:

- 기본 설정
- 입력
- 출력
- 실행 조건
- Execution Settings Override

## 자료

출처를 구분한다.

- Workspace
- Shared
- External
- Previous Artifact
- Context Pack

## 작업 도구

- 변경사항 보기
- AI 코드 검토

향후 작은 Work Action은 이 영역에 추가한다.

## 일정

Phase 3 Schedule을 관리한다.

## 검토

Phase 3 Approval / Revision을 관리한다.

## Dashboard

Dashboard는 Phase 5 Aggregation API를 사용한다.

우선순위:

1. 진행 중
2. 확인 필요
3. 승인 / 일정
4. Context / Usage 경고
5. 최근 Work / Workflow
6. 최근 Artifact
7. 최근 Review / Diff

Dashboard가 각 기능의 상태를 별도로 재계산하지 않는다.

## Advanced Information

기본 화면에서 숨긴다.

- Run ID
- Thread ID
- Turn ID
- Artifact ID
- Runtime temp path
- Raw Manifest
- Raw Event
- 내부 Control Data 경로

## 디자인

control-center-ui-design-references.md를 따른다.

- Linear: Shell / Navigation
- Vercel: Work / Run
- Retool: Workflow Editor
- GitHub Actions: DAG
- Dagster: Dashboard

기존 기능을 시각 디자인 때문에 제거하지 않는다.