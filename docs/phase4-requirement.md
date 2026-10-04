# Phase 4 요구사항

## 0. 문서 목적

Phase 4의 목표는 Control Center가 장기 작업을 수행할수록 대화 Context가 무한히 커지고 오염되는 문제를 줄이는 것이다.

Phase 4는 다음 철학을 따른다.

> **대화는 임시 작업공간이고, 장기 기억은 명시적으로 승격된 자원으로 관리한다.**

모든 대화를 계속 이어붙이지 않는다.

필요한 Context만 선택해 전달하고, 질문은 필요하면 별도의 임시 Thread에서 처리하며, 가치 있는 결과만 Work / Category / Global 자원으로 승격한다.

Phase 4의 핵심 주제는 다음과 같다.

- Context Hygiene
- Thread Branching
- Ephemeral Query
- Context Pack
- Handoff
- Context Promotion
- Thread Lifecycle
- Context Budget
- Cross-Work / Cross-Thread Context Transfer
- 장기 대화 오염 최소화

---


## Thread Actions

- Continue
- Fresh New
- Resume
- Compact and Continue
- Side / Ephemeral Query
- Exact Fork
- Context Pack Handoff

각 기능은 서로 다른 의미를 가진다.

Fresh New
= 기존 Thread Context를 상속하지 않는 새 Thread

Compact
= 현재 Thread의 목표는 유지하면서 Runtime Context를 압축

Side Query
= 메인 Thread에 질문 대화를 누적하지 않는 임시 Thread

Fork
= 현재 시점까지의 정확한 History를 상속한 새 Thread

Handoff
= 전체 History가 아니라 Context Pack만 Fresh Thread에 전달

# 1. Phase 4 핵심 목표

사용자는 하나의 장기 작업을 계속 이어갈 수 있어야 하지만, 모든 질문과 탐색 대화를 기존 Thread에 누적할 필요는 없어야 한다.

대표 시나리오:

```text
현재 개발 Thread
      │
      ├─ 계속 개발
      │
      ├─ 질문만 별도로 수행
      │      ↓
      │   임시 Thread
      │      ↓
      │   답변 확인
      │      ↓
      │   폐기 / 결론만 전달 / 자료로 저장
      │
      ├─ 현재 시점에서 Branch
      │
      └─ Context Pack으로 새 Thread에 Handoff
```

Phase 4에서 사용자는 다음을 명시적으로 선택할 수 있어야 한다.

- 같은 Thread 계속
- 현재 지점에서 정확한 Branch
- 가벼운 질문용 새 Thread
- 현재 상태를 압축해 새 Thread로 넘기기
- 질문 결과 폐기
- 질문 결과를 현재 작업에 전달
- 질문 결과를 장기 자원으로 저장

---

# 2. Codex Context 경계 원칙

Control Center의 Category / Work / Workflow는 Codex의 Context Window와 동일하지 않다.

Codex의 장기 대화 경계는 기본적으로 Thread다.

```text
Thread A
├─ Turn 1
├─ Turn 2
└─ Turn 3

Thread B
├─ Turn 1
└─ Turn 2
```

따라서 다음 원칙을 따른다.

```text
Category
= 분류 + 기본 Resource Scope

Work
= 프로젝트 + 장기 자료 + 결정

Thread
= 특정 작업 흐름의 임시 대화 Context
```

Category에 하나의 Codex Thread를 영구적으로 매핑하지 않는다.

Work에도 하나의 Thread만 강제하지 않는다.

하나의 Work는 여러 Thread를 가질 수 있다.

---

# 3. Thread는 영구 Memory가 아니다

Codex Thread를 장기 프로젝트 Memory로 사용하지 않는다.

장기 기억은 다음에 저장한다.

- Work Resource
- Decision
- Artifact
- Knowledge
- Policy
- Summary
- Context Pack

Thread는 다음 역할만 담당한다.

- 현재 대화
- 현재 작업 흐름
- 단기 Reasoning Context
- 현재 Run의 연속성

장기 프로젝트 상태는 Thread가 없어도 재구성 가능해야 한다.

---

# 4. Context 계층

Phase 4부터 Context를 다음 계층으로 구분한다.

## 4.1 Global Context

모든 Work에서 재사용 가능한 자원.

예:

- 공통 Policy
- 공통 Skill
- 공통 Template
- 공통 Knowledge

## 4.2 Category Context

같은 Category 내에서 공유되는 자원.

예:

```text
Category: 개발

- coding-policy.md
- code-review-skill.md
```

## 4.3 Work Context

해당 Work에만 속하는 장기 자원.

예:

- architecture.md
- decisions/
- requirements/
- 중요한 Artifact
- Work Policy

## 4.4 Thread Context

현재 Thread에만 존재하는 대화 Context.

## 4.5 Run Context

현재 Run에 실제로 전달되는 최종 Input Set.

---

# 5. Context Pack

Context Pack은 새로운 Thread 또는 Run에 전달할 수 있는 명시적인 Context 묶음이다.

Context Pack은 전체 대화 복사본이 아니다.

예:

```text
Context Pack: Control Center Phase 4

현재 목표
- Context Hygiene 구현

현재 구조
- FastAPI
- SQLite
- Codex Gateway
- Workflow Engine

주요 결정
- Work / Workspace / Control Data 분리
- Context는 Input Set
- Artifact는 위치가 아닌 결과 객체

관련 자료
- architecture.md
- phase4-requirements.md

최근 상태
- Phase 3 완료
- Phase 4 구현 예정
```

Context Pack은 다음을 포함할 수 있다.

- 목표
- 현재 상태
- 완료된 작업
- 남은 작업
- 주요 결정
- 관련 Artifact
- 선택된 Source
- Resource
- 관련 파일
- 최근 중요 결과

---

# 6. Context Pack 생성 방식

Context Pack은 최소 두 가지 방식으로 만들 수 있다.

## 6.1 Manual

사용자가 포함할 항목을 직접 선택한다.

```text
☑ 현재 목표
☑ 주요 결정
☑ architecture.md
☑ 최근 Artifact
□ 전체 Run History
```

## 6.2 Assisted

AI 또는 Backend가 후보를 제안한다.

단, 자동 생성 Context Pack은 사용자가 검토할 수 있어야 한다.

Phase 4에서는 자동 Semantic Search가 필수는 아니다.

---

# 7. Thread Action

Phase 4에서 Thread에 다음 Action을 제공한다.

```text
[계속하기]
[질문하기]
[이 지점에서 분기]
[새 대화로 넘기기]
```

각 Action의 의미를 명확히 구분한다.

---

# 8. Continue

`계속하기`는 기존 Thread를 그대로 이어간다.

특징:

- 기존 대화 Context 유지
- 같은 Codex Thread 사용
- 현재 대화 흐름 유지

권장 용도:

- 짧은 후속 작업
- 직전 결과를 바로 이어서 수정
- Context 오염 위험이 낮은 경우

---

# 9. Exact Fork

`이 지점에서 분기`는 현재 Thread를 기준으로 새로운 Thread를 만든다.

가능한 경우 Codex의 `thread_fork`를 사용한다.

```text
Thread A
   │
   ├─ Thread B
   └─ Thread C
```

특징:

- 현재 시점까지의 Context를 상속
- 원본 Thread는 유지
- 이후 대화는 서로 독립
- 정확한 과거 Context가 필요한 실험에 적합

주의:

> Fork는 Context 오염 방지에는 유용하지만 Token 절약을 보장하지 않는다.

기존 Thread가 이미 매우 크다면 Fork된 Thread도 무거울 수 있다.

---

# 10. Ephemeral Query

`질문하기`는 기존 Thread를 그대로 Fork하지 않고, 별도의 가벼운 질문용 Thread를 만든다.

기본 정책:

- Fresh Thread
- Ephemeral
- Read Only
- 필요한 Context만 전달
- Artifact 생성 기본 비활성
- 질문 완료 후 기본적으로 폐기

예:

```text
현재 개발 Thread
      │
      └─ 질문하기
             ↓
       Ephemeral Thread
             ↓
       Context Pack
       + 선택 파일
       + 사용자 질문
             ↓
          답변
```

---

# 11. Query Mode

질문용 Thread는 기본적으로 다음 Mode를 가진다.

```text
Mode: QUERY
Sandbox: READ_ONLY
Persistence: EPHEMERAL
Artifact creation: OFF
```

목적:

- 구조 질문
- 코드 이해
- 설계 비교
- 특정 파일 설명
- 개념 질문
- 의사결정 보조

질문 과정에서 Workspace 파일을 수정하지 않는다.

---

# 12. 질문 결과 처리

질문이 끝난 뒤 사용자는 다음 중 하나를 선택할 수 있다.

```text
[폐기]
[현재 작업에 결론 전달]
[자료로 저장]
```

## 12.1 폐기

질문 Thread와 답변을 장기 Context에 남기지 않는다.

## 12.2 현재 작업에 결론 전달

질문 대화 전체를 기존 Thread에 붙이지 않는다.

대신 짧은 Handoff를 전달한다.

예:

```text
결론:
TaskRun은 Workflow 상태를,
Run은 Runtime 실행을 표현하도록 분리한다.
```

## 12.3 자료로 저장

답변을 장기 자원으로 승격한다.

예:

- Decision
- Knowledge
- Artifact
- Note

---

# 13. Handoff

Handoff는 전체 대화를 새 Thread에 복사하지 않고, 현재 작업 상태만 정리해 전달하는 기능이다.

예:

```text
Thread A
Context 매우 커짐
      ↓
Handoff
      ↓
Context Pack 생성
      ↓
Fresh Thread B
```

Handoff에 포함할 기본 요소:

- 현재 목표
- 완료된 작업
- 현재 작업
- 남은 작업
- 주요 결정
- 중요 Artifact
- 관련 파일
- Blocker
- 다음 지시

---

# 14. 새 대화로 넘기기

UI:

```text
[새 대화로 넘기기]
```

동작:

1. 현재 Thread 상태 확인
2. Context Pack 생성
3. 사용자 확인
4. Fresh Thread 생성
5. Context Pack 전달
6. 새 Thread에서 작업 계속
7. 기존 Thread는 Archived / Closed 상태로 전환 가능

기존 Thread를 삭제하지 않는다.

---

# 15. Context Promotion

대화 중 생성된 모든 정보가 장기 Memory가 되어서는 안 된다.

Context Promotion은 임시 정보를 장기 자원으로 승격하는 과정이다.

승격 대상:

- Decision
- Knowledge
- Policy
- Artifact
- Template
- Note
- Summary

예:

```text
질문 20개
↓
중요한 결론 2개
↓
Decision / Knowledge로 승격
```

---

# 16. Context Demotion / Exclusion

장기 자원이 항상 모든 Run에 포함되어서는 안 된다.

각 Resource는 기본 포함 여부를 가질 수 있다.

예:

```text
architecture.md
Scope: WORK
Default Include: ON

old-review.md
Scope: WORK
Default Include: OFF
```

Run마다 포함 여부를 조정할 수 있다.

---

# 17. Context Budget

Context Pack과 Run Context에는 Budget 개념을 둔다.

예:

```text
Context Budget

Target: 40k
Current: 28k
```

정확한 Token 계산이 어려운 경우 초기에는 문자수 / 파일 크기 기반 Estimate로 시작할 수 있다.

목표:

- 무제한 Context 전달 방지
- 불필요한 파일 포함 방지
- 너무 큰 Context에 대한 경고

---

# 18. Context Warning

다음 조건에서 사용자에게 경고할 수 있다.

- Thread가 너무 길어짐
- 너무 많은 파일 선택
- Context Pack이 지정 Budget 초과
- 동일 자료 반복 포함
- 오래된 Run History 과다 포함

예:

```text
현재 대화 Context가 커지고 있습니다.

권장:
[현재 상태를 새 대화로 넘기기]
```

---

# 19. Context Deduplication

같은 정보가 중복 전달되지 않도록 한다.

예:

```text
architecture.md
+
Context Pack 안의 architecture.md 전체 복사
```

같은 중복을 피한다.

Hash / Resource ID / Artifact ID를 이용해 중복 입력을 감지할 수 있다.

---

# 20. Context Source Tracking

Run이 어떤 Context를 사용했는지 추적 가능해야 한다.

Context Manifest 예:

```text
Run #52

Workspace Files
- docs/architecture.md

Artifacts
- Artifact #201

Decisions
- Decision #14

Resources
- Policy #3
- Skill #2

Context Pack
- Pack #8
```

Raw Manifest는 사용자 기본 화면에서 숨기고 상세정보에서 제공한다.

---

# 21. Cross-Thread Context Transfer

Thread 간 정보를 전달할 때 전체 Conversation 복사를 기본으로 하지 않는다.

지원 방식:

- Exact Fork
- Context Pack
- Handoff
- Artifact
- Decision
- Knowledge

---

# 22. Cross-Work Context Transfer

다른 Work의 정보를 사용할 때도 전체 Work Context를 복사하지 않는다.

예:

```text
Work A
미국금리분석.md

      ↓ Publish

CATEGORY Resource

      ↓

Work B
Alphabet 분석
```

기존 Shared Library를 활용한다.

---

# 23. Thread Lifecycle

Thread는 명시적인 Lifecycle을 가진다.

예:

- ACTIVE
- IDLE
- ARCHIVED
- CLOSED
- EPHEMERAL
- SUPERSEDED

`SUPERSEDED`는 Handoff 후 새 Thread가 후속 작업을 이어가는 경우 사용할 수 있다.

---

# 24. Thread Relation

Thread 간 관계를 기록한다.

Relation Type 예:

- CONTINUATION_OF
- FORKED_FROM
- HANDOFF_FROM
- QUERY_FROM

예:

```text
Thread B
relation = QUERY_FROM
parent = Thread A
```

---

# 25. Query Thread 기본 폐기 정책

Ephemeral Query는 기본적으로 장기 History에 노출하지 않아도 된다.

다만 최소 Metadata는 남길 수 있다.

예:

- 질문 시각
- Parent Thread
- 사용 Context Pack
- 폐기 여부
- Promote 여부

전체 답변 본문은 사용자가 저장하지 않으면 삭제 가능하다.

---

# 26. 중요 질문 보존

질문 답변이 중요한 경우 다음으로 승격할 수 있다.

```text
[Decision으로 저장]
[Knowledge로 저장]
[Artifact로 저장]
```

예:

```text
Decision:
TaskRun과 Run을 분리한다.
```

---

# 27. Context Pack 재사용

Context Pack은 다음 Thread에서 재사용 가능하다.

예:

```text
Context Pack:
Phase 4 Architecture

사용:
- Query Thread
- Review Thread
- Implementation Thread
```

단, Pack이 오래되면 `STALE` 경고를 표시할 수 있다.

---

# 28. Context Pack Versioning

Context Pack은 수정 시 새 Version을 만들 수 있다.

```text
Pack #12 v1
Pack #12 v2
```

기존 Run이 어떤 Version을 사용했는지 추적한다.

---

# 29. Context Freshness

Context Pack에 포함된 파일/Artifact가 변경되면 상태를 표시한다.

예:

```text
architecture.md
Pack 생성 후 변경됨
```

상태:

- CURRENT
- CHANGED
- MISSING
- STALE

---

# 30. Workspace Read-Only Query

Query Mode에서는 기본적으로 Workspace를 Read Only로 연다.

목표:

- 질문 때문에 프로젝트 파일이 수정되는 사고 방지
- 단순 분석에 Write 권한 낭비 방지

필요할 경우 사용자가 명시적으로 Write Mode로 전환해야 한다.

---

# 31. Context Inspector

사용자는 Run 또는 Thread가 현재 어떤 Context를 보는지 확인할 수 있어야 한다.

UI 예:

```text
현재 Context

Work
- Control Center 개발

파일
- architecture.md
- phase4-requirements.md

결정
- Decision #12

Policy
- Coding Safety

총 예상 Context
- 28k
```

---

# 32. Context Selection UI

사용자는 Context를 출처별로 선택한다.

```text
Workspace 파일
☑ architecture.md
☑ phase4-requirements.md

이전 결과물
☑ workflow-review.md

결정
☑ Work / TaskRun 분리

공유 자료
□ Codex Runtime Guide

Resource
☑ Software Architect
```

---

# 33. 질문 UI

현재 Thread 화면에 다음을 제공한다.

```text
[질문하기]
```

클릭 후:

```text
질문 모드

Context:
☑ 현재 Context Pack
☑ architecture.md
□ 전체 Run History

권한:
읽기 전용

저장:
임시

질문:
[________________________________]

[질문 실행]
```

---

# 34. 질문 결과 UI

```text
질문 결과

TaskRun과 Run을 분리하는 이유는 ...

[폐기]
[현재 작업에 결론 전달]
[Decision으로 저장]
[Knowledge로 저장]
```

---

# 35. Branch UI

Thread 또는 Run에서:

```text
[이 지점에서 분기]
```

Branch 생성 Dialog:

```text
Branch 이름:
대안 Architecture 검토

Context 방식:
● 정확한 Fork
○ Context Pack 기반 Fresh Thread
```

두 방식을 명확히 구분한다.

---

# 36. Context Handoff UI

현재 Thread에서:

```text
[새 대화로 넘기기]
```

Preview:

```text
새 Thread에 전달할 내용

☑ 현재 목표
☑ 완료된 작업
☑ 남은 작업
☑ 주요 결정
☑ architecture.md
☑ 최신 Artifact

예상 Context: 18k

[새 대화 시작]
```

---

# 37. Thread Tree

Work 내부에서 Thread 관계를 볼 수 있다.

초기 UI는 복잡한 Graph가 아니라 Tree List면 충분하다.

```text
Phase 4 구현
├─ 개발 Thread
│  ├─ 질문: Thread Context 구조
│  └─ Branch: 대안 구조
└─ Handoff → Phase 4 구현 2
```

---

# 38. Workflow와 Thread 분리

Workflow Task와 Thread를 동일 개념으로 취급하지 않는다.

TaskRun은 필요하면:

- 새 Thread
- 기존 Thread Continue
- Fork
- Context Pack Fresh Thread

중 하나를 실행 전략으로 사용할 수 있다.

Workflow 상태는 Backend가 관리한다.

---

# 39. Context Strategy

TaskDefinition 또는 Run에 Context Strategy를 지정할 수 있다.

예:

- CONTINUE_THREAD
- FORK_THREAD
- FRESH_CONTEXT
- CONTEXT_PACK
- EPHEMERAL_QUERY

초기 UI에서는 모든 전략을 노출하지 않아도 된다.

---

# 40. Resource Promotion Scope

저장된 질문 결과 / 결정 / Knowledge는 Scope를 가진다.

- THREAD
- WORK
- CATEGORY
- GLOBAL

기본값은 WORK를 권장한다.

GLOBAL 자동 승격은 하지 않는다.

---

# 41. Token / Usage Awareness

Phase 4는 모델 Token을 완벽하게 예측하는 시스템이 아니다.

대신 사용자가 Context 비용을 인지할 수 있게 한다.

예:

```text
Context 규모
낮음 / 중간 / 높음
```

또는 가능하면 Runtime Usage 정보를 기반으로 실제 값도 표시한다.

---

# 42. Long Thread Policy

긴 Thread를 계속 유지하는 것을 기본 권장하지 않는다.

다음 조건에서 Handoff를 추천할 수 있다.

- 일정 Turn 수 초과
- Context Budget 초과
- Context Compaction 발생
- 반복적인 질문 다수
- 이전 Turn 대부분이 현재 작업과 무관

자동으로 강제 전환하지 않는다.

---

# 43. Context Compaction 대응

Codex Runtime 내부 Compaction이 발생하더라도 Control Center의 장기 상태는 영향을 최소화해야 한다.

중요 정보는 Thread 내부에만 두지 않는다.

다음은 외부 Control Data로 승격한다.

- 결정
- 최종 설계
- 완료 상태
- 주요 Artifact
- 다음 작업
- 장기 Policy

---

# 44. Conversation 오염 방지 규칙

기본 UX는 다음을 유도한다.

- 단순 질문 → Query
- 다른 방향 실험 → Fork
- 오래된 Thread → Handoff
- 중요한 결론 → Promote
- 중요하지 않은 답변 → Discard
- 장기 지식 → Resource
- 실제 결과 → Artifact

---

# 45. 데이터 모델 추가

Phase 4에서 다음 Entity를 고려한다.

## ThreadRecord

- id
- work_id
- codex_thread_id
- status
- title
- parent_thread_id
- relation_type
- created_at
- archived_at

## ContextPack

- id
- work_id
- name
- version
- status
- estimated_size
- created_at

## ContextPackItem

- id
- context_pack_id
- source_type
- source_id
- source_version / hash
- include_mode

## Handoff

- id
- source_thread_id
- target_thread_id
- context_pack_id
- summary
- created_at

## Promotion

- id
- source_thread_id
- source_run_id
- target_type
- target_id
- scope
- created_at

## EphemeralQuery

- id
- parent_thread_id
- codex_thread_id
- context_pack_id
- status
- result_action
- created_at
- disposed_at

---

# 46. 기존 Entity 재사용

가능한 기존 Entity를 재사용한다.

- Work
- Run
- Artifact
- Resource
- Shared Library
- Decision
- Workflow
- TaskRun

Phase 4 때문에 기존 Run / Workflow 구조를 대체하지 않는다.

---

# 47. Context Pack 저장 위치

Context Pack은 Workspace 안에 강제로 파일을 만들지 않는다.

Control Data Root에 저장한다.

```text
~/.control-center/works/{work_id}/context-packs/
```

또는 DB + Controlled File 방식으로 관리한다.

---

# 48. Security / Permission

Query Mode는 기본 Read Only다.

Handoff / Context Pack 생성은 프로젝트 파일을 수정하지 않는다.

Resource Promotion은 Backend Service를 통해 처리한다.

AI가 Control DB를 직접 수정하지 않는다.

---

# 49. UI/UX 원칙

- 사용자는 Context Window라는 기술 개념을 몰라도 된다.
- `질문하기`, `분기`, `새 대화로 넘기기`의 차이가 명확해야 한다.
- Fork와 Fresh Query의 Token 비용 차이를 설명할 수 있어야 한다.
- 질문 결과는 자동으로 현재 Thread에 합쳐지지 않는다.
- 중요한 정보만 사용자가 승격한다.
- 현재 Context가 무엇인지 확인 가능해야 한다.
- 기본 화면에서 Raw Thread ID는 숨긴다.

---

# 50. 저비용 테스트 전략

Phase 4 구현에서도 실제 Codex 호출을 반복하지 않는다.

Mock / Unit Test 대상:

- Thread Relation
- Context Pack 생성
- Context Pack Version
- Promotion
- Handoff
- Ephemeral Query lifecycle
- Context Budget
- Context Deduplication
- Freshness
- Thread Tree
- UI State
- Persistence

실제 Codex 호출이 필요한 기능:

- thread_fork
- thread_resume
- ephemeral thread_start
- read_only query

이미 Runtime Capability가 VERIFIED되어 있다면 반복 검증하지 않는다.

---

# 51. 수동 Acceptance Scenario

## Scenario A — Continue

기존 Thread에서 후속 작업 실행.

Context가 유지됨.

## Scenario B — Query

현재 작업에서 `질문하기`.

Fresh Ephemeral Thread 생성.

선택한 Context만 전달.

Workspace는 Read Only.

질문 완료 후 `폐기`.

기존 Thread에는 질문 대화가 추가되지 않음.

## Scenario C — Query Promotion

질문 결과에서:

```text
[Decision으로 저장]
```

선택.

Work Decision으로 저장.

새 Run에서 필요할 때 선택 가능.

## Scenario D — Query Handoff

질문 결과에서:

```text
[현재 작업에 결론 전달]
```

선택.

전체 질문 대화가 아니라 짧은 Handoff만 기존 작업에 전달.

## Scenario E — Exact Fork

현재 Thread에서 정확한 Fork 생성.

부모 Thread와 Fork Thread가 이후 독립적으로 진행.

## Scenario F — Fresh Handoff

긴 Thread에서:

```text
[새 대화로 넘기기]
```

실행.

Context Pack 생성.

Fresh Thread에서 작업 지속.

기존 Thread는 보존.

## Scenario G — Context Budget

너무 많은 자료 선택.

Budget Warning 표시.

일부 Context 제거 후 정상 실행.

## Scenario H — Cross-Thread

Thread A에서 저장한 Decision을 Thread B에서 선택해 사용.

## Scenario I — Cross-Work

Work A의 CATEGORY Resource를 Work B의 Context Pack에 포함.

---

# 52. Phase 4 완료 기준

다음을 모두 만족하면 Phase 4 완료로 본다.

- Work당 여러 Thread 관리
- Thread Lifecycle
- Thread Relation 기록
- Continue
- Exact Fork
- Fresh Query
- Ephemeral Query
- Read Only Query
- Context Pack
- Context Pack Version
- Handoff
- Fresh Thread Handoff
- 질문 결과 Discard
- 질문 결과 Current Work 전달
- Decision / Knowledge / Artifact Promotion
- Context Source Tracking
- Context Deduplication
- Context Freshness
- Context Budget / Warning
- Cross-Thread Context Transfer
- Cross-Work Resource Transfer
- Thread Tree UI
- Context Inspector
- Context Selection UI
- Query UI
- Branch UI
- Handoff UI
- 기존 Phase 1~3 Regression 유지

---

# 53. Phase 4 제외 범위

다음은 Phase 4 필수 범위가 아니다.

- Vector DB 기반 자동 Memory Search
- Embedding 기반 자동 Context 추천
- 완전 자동 Context Pruning
- 완전 자동 Memory Promotion
- 모델이 임의로 Global Memory 수정
- 모든 Thread 자동 Summarization
- Remote Thread Sync
- Team Shared Memory
- Multi-user Memory Conflict Resolution
- 자동 Prompt Compression Model
- 자동 Model Routing
- AI Planner

필요한 경우 이후 Phase에서 확장한다.

---

# 54. Phase 4 대표 사용자 흐름

```text
Work: Control Center 개발

현재 Thread
Phase 4 구현

        │
        ├─ 계속하기
        │
        ├─ 질문하기
        │      ↓
        │   임시 Thread
        │      ↓
        │   답변
        │      ↓
        │   폐기 / 결론 전달 / 저장
        │
        ├─ 이 지점에서 분기
        │      ↓
        │   새로운 Branch
        │
        └─ 새 대화로 넘기기
               ↓
           Context Pack
               ↓
           Fresh Thread
```

---

# 55. 최종 철학

Phase 4의 핵심은 Thread를 오래 유지하는 것이 아니다.

> **필요한 정보만 다음 실행으로 전달하고, 가치 없는 대화는 버리며, 중요한 정보만 장기 자원으로 승격한다.**

즉:

```text
Conversation
= 임시 작업공간

Context Pack
= 필요한 상태 묶음

Artifact
= 실제 결과

Decision / Knowledge
= 장기 기억

Thread
= 소비 가능한 실행 Context
```

Control Center는 모든 대화를 기억하는 시스템이 아니라, **무엇을 기억하고 무엇을 버릴지 사용자가 통제할 수 있는 Context Control Plane**으로 발전한다.
