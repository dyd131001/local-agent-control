# AI Project Control Center — UI / Workspace Improvement Requirements

## 1. 문서 목적

이 문서는 현재 Phase 1 / Phase 2 구현을 실제로 사용하면서 발견된 UI, 작업 흐름, Workspace / 파일 관리 문제를 정리하고 개선 방향을 정의한다.

목표는 기능을 더 많이 노출하는 것이 아니라 다음을 달성하는 것이다.

- 사용자가 현재 어떤 작업을 하고 있는지 한눈에 이해할 수 있어야 한다.
- 단일 실행, Workflow, 향후 추가될 실행 모드를 명확히 구분해야 한다.
- 새 작업 시작과 기존 작업 계속하기의 차이가 분명해야 한다.
- Workflow의 순차 / 병렬 / 대기 관계가 시각적으로 보여야 한다.
- Task별 입력 자료, 이전 Task 결과, 생성 결과물을 명확히 구분해야 한다.
- Control Center 내부 관리 데이터와 실제 사용자 작업 파일을 분리해야 한다.
- 기존 프로젝트 또는 사용자가 지정한 외부 작업 폴더를 중심으로 작업할 수 있어야 한다.
- UI는 내부 Runtime 개념을 그대로 노출하지 않으면서도 사용자의 세밀한 제어권은 유지해야 한다.

---

# 2. 현재 확인된 핵심 문제

## 2.1 Dashboard가 상태 요약 수준에 머물러 있음

현재 Dashboard는 주로 다음 정보를 보여준다.

- Work 개수
- Active / queued 개수
- Recent artifacts
- 최근 실행

하지만 실제 장기 프로젝트 관리 화면으로 사용하기에는 다음 정보가 부족하다.

- 어떤 Work가 현재 진행 중인지
- 어떤 실행이 실패 / 대기 / 실행 중인지
- Workflow가 어느 Task까지 진행됐는지
- 다음에 사용자가 확인해야 할 항목
- 최근 생성된 결과물과 연결된 작업
- 최근 실패 원인
- 예약 / 승인 / 검토 등 향후 추가될 운영 상태

Dashboard는 단순 통계 페이지가 아니라 **현재 AI 작업의 진행 상황을 보는 Control Center 홈 화면**으로 강화해야 한다.

---

## 2.2 Work 화면에 기능이 한 영역에 계속 누적될 가능성이 있음

현재 Work 화면은 단일 실행 기능과 Workflow 기능이 같은 페이지에 길게 배치되는 구조에 가깝다.

향후 다음 기능이 추가될 가능성이 있다.

- 단일 실행
- Workflow
- 예약 실행
- 승인 / 검토
- 질문용 임시 실행
- Branch
- Context Handoff
- 기타 자동화 모드

이 기능들을 한 화면에 계속 추가하면 사용자가 현재 어떤 모드에서 작업 중인지 이해하기 어려워진다.

따라서 Work 화면은 **실행 모드별로 명확하게 분리된 구조**가 필요하다.

---

## 2.3 단일 실행에서 "새 작업"과 "기존 작업 계속하기"가 명확하지 않음

현재 단일 실행은 새 Request를 만드는 동작과 이전 Run / Thread를 이어가는 동작의 구분이 약하다.

사용자는 최소 다음 행동을 구분할 수 있어야 한다.

- 새 대화에서 새 요청 시작
- 기존 대화에서 새 요청
- 같은 요청 다시 실행
- 실행 중 추가 지시
- 현재 작업 중지
- 기존 실행 선택 후 상세 확인

즉 단일 실행 안에서도 **새 실행 / 이어서 실행 / 재실행**의 의미를 명확히 분리해야 한다.

---

## 2.4 Workflow 편집 화면이 긴 설정 Form 중심임

현재 Workflow 편집은 Task별 설정 항목이 세로로 길게 나열된다.

이 방식은 다음을 한눈에 보기 어렵다.

- Task 실행 순서
- 병렬 실행 가능 Task
- 현재 Task가 어떤 Task를 기다리는지
- 이전 Task의 어떤 Artifact를 받는지
- 어떤 결과물을 다음 Task에 넘기는지

Workflow는 단순 설정 Form이 아니라 **AI 작업 공정을 설계하는 화면**으로 보여야 한다.

---

## 2.5 Task 자료 관리가 단순 파일 첨부 수준임

현재 참고 자료는 공통 자료 선택 위주다.

실제 개발 / 문서 작업에서는 다음이 필요하다.

- 기존 Workspace 파일 선택
- 특정 docs 경로 지정
- 새 Markdown 생성
- Markdown 파일명 직접 지정
- Markdown 초기 내용 직접 작성
- AGENTS.md 생성
- Requirements / Architecture / Implementation Plan 등 작업용 Markdown 생성
- 생성한 파일을 즉시 Task Input으로 사용

즉 Task 입력 자료 영역은 **파일 선택 + 작업 문서 작성 도구** 역할까지 해야 한다.

---

## 2.6 `작업 공간`이라는 명칭이 의미를 제대로 전달하지 못함

현재 옵션 예:

- 문서·분석 결과물
- 격리된 Git 작업복제본

하지만 사용자는 이것을 실제 경로 선택으로 오해할 수 있다.

실제로 의미하는 것은 Task의 **실행 / 수정 방식**에 더 가깝다.

따라서 UI 명칭을 `작업 공간`보다 `작업 방식`으로 변경하는 것을 권장한다.

---

## 2.7 Git이 없는 병렬 수정 방식이 없음

현재 Git Worktree는 Git Repository에서 병렬 Coding Task를 격리하는 데 적합하다.

하지만 Git을 사용하지 않는 프로젝트에서도 병렬 수정이 필요할 수 있다.

따라서 다음 실행 방식을 추가할 필요가 있다.

- 결과물 생성
- 격리된 일반 복제본에서 수정
- Git 작업복제본에서 수정

같은 원본 Workspace를 여러 AI가 직접 동시에 수정하는 것은 기본적으로 제한해야 한다.

---

## 2.8 Work 관련 파일이 Control Center 내부 Data 경로에 저장되는 구조가 남아 있음

현재 화면에서 Work 관리 경로가 다음과 같이 Control Center 내부 Data 영역으로 노출되고 있다.

```text
.../AI_Control_Center/data/categories/.../works/...
```

그러나 목표 구조는 다음과 달라야 한다.

### Control Center 관리 영역

Control Center 자체가 관리해야 하는 내부 데이터만 둔다.

예:

- control.db
- 내부 metadata
- runtime 상태
- 공용 / Published Artifact Library
- 전역 Resource / Template
- 시스템 설정

### 사용자 Work 영역

실제 작업 파일은 Control Center 프로젝트 내부가 아니라 외부 Workspace에 둔다.

기본 Workspace Root 후보:

```text
~/Developer/
```

예:

```text
~/Developer/AI_Control_Center
~/Developer/GIMS
~/Developer/AI-IP-Studio
~/Developer/MyResearch
```

Control Center는 이 Workspace를 연결해서 관리한다.

**사용자 Work 파일을 Control Center의 `data/categories/.../works/...` 아래에 자동 생성하는 구조는 제거하거나 Legacy 호환 범위로 제한한다.**

---

# 3. 전체 UI 정보 구조 개선

Work 화면은 향후 기능 확장을 고려하여 상단에서 실행 모드를 구분한다.

권장 구조:

```text
Work: 자기소개서

[개요] [단일 실행] [Workflow] [결과물] [자료] [활동 기록]
```

향후 Phase에서 필요하면 다음을 추가할 수 있다.

```text
[일정]
[검토 / 승인]
```

중요한 점은 기능이 늘어날 때 같은 화면 아래로 계속 붙이는 것이 아니라 **기능 영역 자체를 분리**하는 것이다.

---

# 4. Dashboard 개선

## 4.1 Dashboard 목표

Dashboard는 다음 질문에 즉시 답할 수 있어야 한다.

- 지금 실행 중인 작업은 무엇인가?
- 실패한 작업이 있는가?
- 내가 확인해야 할 작업이 있는가?
- Workflow가 어디까지 진행됐는가?
- 최근 결과물은 무엇인가?
- 최근 어떤 Work를 사용했는가?

## 4.2 상단 상태 카드

현재 숫자 중심 카드보다 운영 상태를 강화한다.

```text
진행 중 3
대기 중 2
확인 필요 1
최근 결과물 5
```

Phase 3 이후에는 `확인 필요`에 실패, 승인 대기, 수정 필요, 사용자 입력 필요 등을 포함할 수 있다.

## 4.3 진행 중인 작업 영역

Dashboard 핵심 영역으로 추가한다.

```text
진행 중인 작업

자기소개서 만들기
Workflow · 3 / 4 Task 완료

✓ 경력 분석
✓ 경험 정리
● 자기소개서 작성
○ 최종 검토

[계속 보기]
```

Workflow는 진행률을 표시한다.

```text
3 / 5 Task
60%
```

단일 실행은 다음처럼 표시한다.

```text
자기소개서 문장 수정
단일 실행 · 실행 중
GPT-6 Sol / Medium
```

## 4.4 최근 Work

단순 Work 이름만 보여주는 것이 아니라 최근 실행 시각, 마지막 상태, 실행 모드, 최근 결과물을 함께 표시한다.

## 4.5 실패 / 확인 필요 영역

실패를 최근 실행 목록 속 Badge 하나로만 두지 않는다.

```text
확인 필요

자기소개서 / 경력 분석
실패
필수 결과물 career-analysis.md가 생성되지 않았습니다.

[상세 보기] [다시 실행]
```

## 4.6 최근 결과물

결과물 이름과 출처를 함께 표시한다.

```text
final-resume.md
자기소개서 만들기 / 최종 작성
10분 전
```

---

# 5. Work 화면 개선

## 5.1 Work Header

현재 내부 관리 경로를 크게 노출하지 않는다.

기본 표시:

```text
자기소개서

Workspace
~/Developer/job-application

[폴더 열기] [Workspace 변경]
```

Control Center 내부 ID / 관리 경로는 고급 정보에서만 표시한다.

## 5.2 Work 개요 화면

Work를 클릭했을 때 곧바로 실행 Form부터 보여주기보다 현재 상태를 요약한다.

```text
자기소개서

현재 상태
최근 실행: Workflow / 실패
최근 결과물: resume-v2.md

자료 5개
Workflow 2개
결과물 8개

[새 단일 실행]
[Workflow 실행]
```

---

# 6. 단일 실행 UI 개선

단일 실행 화면 상단에서 사용자가 무엇을 할지 먼저 선택한다.

```text
단일 실행

[새 요청]
[기존 대화에서 계속]
```

## 6.1 새 요청

Fresh Thread / 새로운 Request를 생성한다.

```text
새 요청

지시
[                                      ]

자료
[+ 파일 선택]
[+ Markdown 만들기]

모델
[GPT-6 Sol]

추론 수준
[Medium]

[실행]
```

## 6.2 기존 대화에서 계속

Run / Conversation을 먼저 선택한다.

```text
이어서 사용할 대화

○ 자기소개서 문장 개선
   GPT-6 Sol · 완료 · 오늘 10:21

○ 경력 분석
   GPT-6 Astra · 완료 · 어제
```

선택 후:

```text
[이 대화에서 새 요청]
```

## 6.3 Retry 분리

`다시 실행`은 기존 대화 이어가기와 구분한다.

권장 명칭:

```text
같은 요청 다시 실행
```

의미:

- 같은 Request
- 새로운 Run
- 기존 실패 / 완료 Run 유지

## 6.4 실행 중 동작

Run이 실행 중일 때만 표시한다.

```text
현재 작업에 추가 지시
[                                 ] [추가]

[작업 중지]
```

---

# 7. Workflow 메인 UI 개선

Workflow 영역은 목록과 실행 기록을 구분한다.

```text
Workflow

내 Workflow
- 자기소개서 만들기
- 서류 검토

최근 실행
- 자기소개서 만들기 · 실행 중
- 서류 검토 · 완료

[새 Workflow]
[템플릿에서 만들기]
```

Workflow 이름이 중복해서 나오는 현재 구조를 정리한다.

---

# 8. Workflow 편집 화면 개선

## 8.1 기본 Layout

긴 Form 하나 대신 좌우 구조를 사용한다.

```text
┌──────────────────────┬──────────────────────────────────┐
│ Workflow 흐름        │ 선택한 Task 설정                 │
│                      │                                  │
│ ① 경력 분석         │ 작업 이름                        │
│ Astra / High         │ 지시                             │
│ ↓                    │ 모델 / Reasoning                 │
│                      │ 입력 / 출력 / 실행 조건          │
│ ② 경험 정리         │                                  │
│ Sol / Medium         │                                  │
│       │              │                                  │
│       ▼              │                                  │
│ ③ 자기소개서 작성   │                                  │
│ Luna / Medium        │                                  │
│                      │                                  │
│ [+ 작업 추가]        │                                  │
└──────────────────────┴──────────────────────────────────┘
```

## 8.2 Workflow 흐름 시각화

순차:

```text
① 설계
   ↓
② 구현
   ↓
③ 검토
```

병렬:

```text
        ① 설계
           │
     ┌─────┴─────┐
     ▼           ▼
② Backend     ③ UI
     │           │
     └─────┬─────┘
           ▼
        ④ 통합
```

복잡한 Drag & Drop Canvas는 Phase 2 필수 요구사항이 아니다.

---

# 9. Task 설정 UI 개선

Task 상세는 다음 4개 영역으로 분리한다.

```text
[기본 설정]
[입력]
[출력]
[실행 조건]
```

## 9.1 기본 설정

- 작업 이름
- 지시
- 모델
- Reasoning
- 작업 방식

## 9.2 작업 방식

기존 `작업 공간`을 `작업 방식`으로 변경한다.

### 결과물 생성

기존 프로젝트 파일을 직접 수정하지 않고 문서 / 분석 / 결과물을 생성한다.

내부: `ARTIFACT_ONLY`

### 격리된 복제본에서 수정

Git이 없는 Workspace용.

Workspace를 Task 전용 영역에 복제하여 다른 Task와 분리해서 수정한다.

내부: `ISOLATED_COPY`

### Git 작업복제본에서 수정

Git Worktree를 만들어 병렬 Coding Task의 파일 충돌을 줄인다.

내부: `GIT_WORKTREE`

Git Repository가 아니면 옵션을 숨기지 않고 Disabled 처리한다.

```text
Git 작업복제본에서 수정
현재 Workspace는 Git 저장소가 아닙니다.
```

---

# 10. Task 입력 자료 UI 개선

입력을 다음 세 영역으로 분리한다.

```text
공통 자료
Task 전용 자료
이전 Task 결과물
```

## 10.1 공통 자료

```text
☑ Work에서 선택한 공통 자료 사용
```

## 10.2 기존 파일 추가

```text
[+ 기존 파일 추가]
```

기준 위치:

- 현재 Workspace
- Shared Library

Workspace 내부 경로는 절대경로보다 상대경로를 기본으로 표시한다.

## 10.3 새 Markdown 만들기

Task 편집 화면에서 직접 Markdown 파일을 생성할 수 있어야 한다.

```text
[+ 새 Markdown 만들기]
```

입력:

```text
저장 위치
● 현재 Workspace
○ Control Center Shared Library

경로
docs/

파일 이름
phase2-implementation-plan.md

문서 종류
[Implementation Plan]

내용
┌─────────────────────────────────────┐
│ # Phase 2 Implementation Plan       │
│                                     │
│ ...                                 │
└─────────────────────────────────────┘

☑ 생성 후 이 Task의 자료로 사용

[파일 만들기]
```

---

# 11. Markdown 문서 종류

다음 선택지를 제공한다.

- 일반 Markdown
- AGENTS.md
- Requirements
- Architecture
- Implementation Plan
- Decision / Note

이 구분은 복잡한 신규 Entity보다 Template / Usage Type으로 우선 구현한다.

## 11.1 AGENTS.md

AGENTS.md 선택 시 파일명을 `AGENTS.md`로 기본 지정한다.

설명:

```text
이 파일은 해당 Workspace에서 AI 작업 규칙을 정의합니다.
```

LINKED Workspace에는 사용자 명시적 요청 없이 자동 생성하지 않는다.

---

# 12. 이전 Task 결과물

참고 자료와 이전 Task 결과물을 같은 목록으로 섞지 않는다.

```text
이전 작업 결과

① 경력 분석
☑ career-analysis.md

② 경험 정리
☐ experience-summary.md
```

Artifact를 선택하면 필요한 Dependency를 자동 제안할 수 있다.

```text
career-analysis.md를 사용하려면
① 경력 분석이 먼저 완료되어야 합니다.

[선행 작업 자동 추가]
```

---

# 13. Task Output UI

출력 결과물은 명시적인 Output Contract로 표현한다.

```text
출력 결과물

이름
경력 분석 결과

경로
docs/career-analysis.md

형식
Markdown

☑ 필수 결과물
```

필수 결과물이 생성되지 않으면 AI가 완료했다고 응답해도 Task를 완료 처리하지 않는다.

---

# 14. 실행 조건 UI

```text
실행 조건

● Workflow 시작 시 실행
○ 다른 작업 완료 후 실행
```

두 번째 선택 시:

```text
먼저 완료되어야 하는 작업

☑ ① 경력 분석
☐ ② 경험 정리
```

여러 Task를 선택하면 `①, ② 모두 완료 후 실행`이라고 요약한다.

## 14.1 병렬 실행

별도의 `병렬 실행` 체크박스는 기본적으로 필요하지 않다.

Dependency가 같고 서로 의존하지 않는 Task는 Scheduler가 병렬 가능 Task로 판단한다.

UI에서는 다음처럼 보여준다.

```text
②와 ③은 동시에 실행할 수 있습니다.
```

---

# 15. Workflow 실행 화면

편집 화면과 실행 화면의 구조를 최대한 동일하게 유지한다.

```text
✓ ① 경력 분석
   Astra · 완료
   → career-analysis.md

● ② 경험 정리
   Sol · 실행 중

● ③ 프로젝트 분석
   Sol · 실행 중

○ ④ 자기소개서 작성
   ②, ③ 완료 대기
```

사용자가 확인할 수 있어야 하는 것:

- 완료 Task
- 현재 실행 Task
- 병렬 Task
- 대기 Task
- 대기 이유
- 실패 Task
- 생성 Artifact
- Input / Output 관계

---

# 16. Workspace / 저장 경로 구조 개선

## 16.1 기본 원칙

**Control Center 프로젝트 폴더는 사용자 Work 파일의 기본 저장소가 아니다.**

현재처럼:

```text
AI_Control_Center/data/categories/.../works/...
```

아래에 실제 Work 내용을 저장하는 방식을 제거한다.

## 16.2 기본 Workspace Root

기본 Work 생성 위치는 다음을 기본 후보로 둔다.

```text
~/Developer/
```

설정에서 변경 가능해야 한다.

```text
기본 Workspace 위치
~/Developer
[변경]
```

## 16.3 새 Work 생성

새 Work를 만들 때 두 가지를 제공한다.

```text
새 Work

○ 새 Workspace 만들기
○ 기존 폴더 연결
```

### 새 Workspace 만들기

```text
기본 위치
~/Developer

폴더 이름
resume-project

실제 위치
~/Developer/resume-project
```

### 기존 폴더 연결

Finder / File Picker에서 기존 프로젝트를 선택한다.

---

# 17. Control Center Data Root 역할 제한

Control Center 관리 영역은 내부 상태와 공용 자원 관리에 집중한다.

```text
~/.control-center/
├── control.db
├── runtime/
├── metadata/
├── library/
│   ├── global/
│   └── category/
└── settings/
```

중요:

**사용자 Work의 실제 프로젝트 파일을 이 경로에 기본 저장하지 않는다.**

## 17.1 Shared / Published Artifact

Control Center가 파일 콘텐츠 자체를 관리하는 대표 영역은 Shared Library다.

```text
~/.control-center/library/
```

여기에 들어갈 수 있는 것:

- GLOBAL Artifact
- CATEGORY Artifact
- 사용자가 명시적으로 Publish한 Artifact
- 공용 Template
- 공용 Resource

Work 전용 파일은 해당 Workspace에 남기는 것을 기본으로 한다.

## 17.2 내부 Metadata

다음 정보는 외부 Workspace에 강제 생성하지 않는다.

- Run ID
- Thread ID
- TaskRun 상태
- Artifact relation
- Workflow metadata
- Runtime state

이 정보는 DB / Control Data Root에서 관리한다.

---

# 18. Artifact 위치 표현

Artifact는 반드시 `artifacts/` 폴더 안에 있어야 하는 파일이 아니다.

### WORKSPACE

실제 Work 프로젝트 안의 결과물.

```text
~/Developer/project/docs/result.md
```

### CONTROLLED

Control Center가 관리하는 Shared / Published 결과물.

```text
~/.control-center/library/...
```

### EXTERNAL

외부 참조 파일.

UI에서는 내부 Enum보다 사용자 친화적으로 표시한다.

---

# 19. Work Header의 경로 표시 개선

현재 `관리 데이터:` 절대경로를 크게 보여주는 UI는 제거한다.

대신:

```text
Workspace
~/Developer/resume-project

[폴더 열기]
[변경]
```

을 기본으로 표시한다.

필요한 경우 `고급 정보`에서 Work ID, Control Data ID, Runtime Path 등을 확인한다.

---

# 20. Dashboard와 Work의 상태 모델 통일

Dashboard, Work, Workflow 화면에서 서로 다른 상태 표현을 사용하지 않는다.

기본 표시:

- 실행 준비
- 대기
- 실행 중
- 완료
- 실패
- 취소
- 차단

색 / Badge / 문구를 동일하게 유지한다.

---

# 21. 영문 UI 정리

현재 다음과 같은 영문이 혼재한다.

- Works
- Active / queued
- Recent artifacts
- Nothing here yet
- Select a Run or start a new Request.
- Archive
- Work / Category Library / Global Library

사용자에게 노출되는 기본 UI는 한국어로 통일한다.

Model 이름, 파일 이름, Runtime 이름은 원문 유지 가능하다.

---

# 22. UI 설계 원칙

## 22.1 내부 명령어는 숨기되 제어권은 숨기지 않는다

사용자는 thread_resume, thread_fork, turn_id, ContextPack ID, RRULE 등의 내부 이름을 몰라도 된다.

하지만 다음 행동은 직접 선택할 수 있어야 한다.

- 새 대화
- 기존 대화 계속
- 같은 요청 다시 실행
- 분기
- 작업 중지
- 자료 선택
- 실행 순서
- 실행 일정
- 결과 저장 / 폐기

## 22.2 입력 → 실행 → 출력 구조를 유지한다

모든 실행 UI는 가능하면 다음 순서로 이해되어야 한다.

```text
무엇을 할지
↓
무엇을 사용할지
↓
어떤 방식으로 실행할지
↓
무엇을 결과로 남길지
```

## 22.3 고급 정보는 기본 화면에서 숨긴다

기본 화면에서 숨길 대상:

- Run ID
- Request ID
- Thread ID
- Turn ID
- SHA256
- Raw Manifest
- Raw Runtime Event
- Control Data Path

필요 시 `고급 정보`에서 확인한다.

---

# 23. 우선 구현 순서

## Priority 1 — Workspace 구조 수정

가장 먼저 실제 파일 저장 위치 문제를 바로잡는다.

- Work 내부 Data 경로 사용 축소
- 기본 Workspace Root `~/Developer`
- 새 Workspace / 기존 폴더 연결
- Control Center Data Root 역할 제한
- Shared Library 분리

이 부분은 이후 모든 파일 / Workflow 기능의 기반이므로 UI보다 먼저 구조를 확정해야 한다.

## Priority 2 — Work 화면 정보 구조

- 개요
- 단일 실행
- Workflow
- 자료
- 결과물
- 활동 기록

으로 분리한다.

## Priority 3 — 단일 실행 UX

- 새 요청
- 기존 대화에서 계속
- 같은 요청 다시 실행
- 실행 중 추가 지시
- 중지

를 명확히 구분한다.

## Priority 4 — Workflow 편집 UI

- 좌측 Workflow Flow
- 우측 Task 설정
- 순차 / 병렬 관계
- 대기 조건
- Artifact Handoff

를 시각화한다.

## Priority 5 — Task 자료 관리

- 기존 파일 선택
- Workspace 상대경로
- 새 Markdown
- AGENTS.md
- Requirements
- Architecture
- Implementation Plan
- 초기 내용 입력

을 추가한다.

## Priority 6 — Dashboard 운영 화면 강화

실제 Work / Workflow 데이터가 쌓인 뒤 다음을 강화한다.

- 진행 중 작업
- Workflow 진행률
- 실패 / 확인 필요
- 최근 Work
- 최근 Artifact

---

# 24. 사용자 수동 검증 체크리스트

## Workspace

- 새 Work 생성 시 `~/Developer` 아래 새 Workspace를 만들 수 있는가?
- 기존 `~/Developer/...` 폴더를 Work로 연결할 수 있는가?
- LINKED Workspace에 Control Center 관리 폴더가 자동 생성되지 않는가?
- Work 화면에 Control Center 내부 Data 경로 대신 실제 Workspace가 보이는가?
- Shared Library만 Control Center 관리 영역에 명시적으로 저장되는가?

## 단일 실행

- 새 요청과 기존 대화 계속하기를 구분할 수 있는가?
- Retry가 기존 대화 계속하기와 다르게 보이는가?
- 현재 Run을 선택했을 때 요청 / 모델 / 상태 / 결과를 이해할 수 있는가?

## Workflow

- 어떤 Task가 먼저 실행되는지 한눈에 알 수 있는가?
- 어떤 Task가 동시에 실행 가능한지 알 수 있는가?
- 대기 중 Task가 무엇을 기다리는지 알 수 있는가?
- 어떤 Artifact가 다음 Task에 전달되는지 알 수 있는가?
- Output Contract를 이해할 수 있는가?

## 자료

- 기존 Workspace 파일을 쉽게 선택할 수 있는가?
- 새 Markdown을 UI에서 직접 생성할 수 있는가?
- docs 상대경로를 설정할 수 있는가?
- 파일 이름과 초기 내용을 직접 작성할 수 있는가?
- AGENTS.md와 일반 Markdown의 용도가 구분되는가?

## Dashboard

- 현재 실행 중인 Work를 찾을 수 있는가?
- 실패한 작업을 바로 찾을 수 있는가?
- Workflow 진행 정도를 알 수 있는가?
- 최근 결과물을 바로 열 수 있는가?

---

# 25. 완료 기준

이번 UI / Workspace 개선은 단순히 화면을 예쁘게 바꾸는 것으로 완료되지 않는다.

다음 흐름이 자연스러워야 한다.

```text
Dashboard
↓
Work 선택
↓
Workspace 확인
↓
실행 모드 선택
├─ 단일 실행
└─ Workflow
↓
자료 선택 / 생성
↓
실행
↓
현재 진행 상태 확인
↓
결과물
↓
후속 작업
```

그리고 Workflow에서는 다음이 UI만 보고 이해되어야 한다.

```text
Astra 설계
    ↓
implementation-plan.md
    ↓
┌───────────────┐
Luna Backend   Luna UI
└───────┬───────┘
        ↓
     Sol 검토
```

사용자는 Codex 내부 명령이나 DAG 구현 방식을 몰라도 되지만,

- 어떤 작업을 먼저 할지
- 어떤 작업을 동시에 할지
- 어떤 자료를 사용할지
- 어떤 결과물을 다음 작업에 넘길지
- 새 대화로 시작할지 기존 대화를 이어갈지

는 직접 세밀하게 제어할 수 있어야 한다.
