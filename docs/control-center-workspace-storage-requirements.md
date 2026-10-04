# AI Project Control Center — Workspace / Storage Architecture Requirements

## 1. 목적

현재 구현에는 Work 관련 실제 파일이 Control Center 내부의 `data/.../works/...` 경로에 생성되는 구조가 남아 있다.

이 구조를 수정한다.

핵심 원칙은 다음과 같다.

> Control Center는 실제 사용자 프로젝트 파일을 자기 `data` 폴더 안에 소유하지 않는다.

> 실제 Work는 외부 Workspace에서 관리하고,
> Control Center 내부 Data 영역은 공용으로 Publish한 산출물 관리 용도로 제한한다.

기본 외부 Workspace Root는 다음을 사용한다.

```text
~/Developer/
```

---

# 2. 최종 경로 구조

## 2.1 Application Root

Control Center 자체 소스코드.

예:

```text
~/Developer/AI_Control_Center/
```

여기에는 애플리케이션 코드만 둔다.

예:

```text
AI_Control_Center/
├── app/
├── migrations/
├── docs/
├── static/
├── tests/
└── ...
```

사용자의 Work 파일을 이 프로젝트 내부에 자동으로 만들지 않는다.

---

## 2.2 Workspace Root

실제 사용자 작업은 외부 Workspace를 기준으로 한다.

기본 Root:

```text
~/Developer/
```

예:

```text
~/Developer/
├── AI_Control_Center/
├── GIMS/
├── AI-IP-Studio/
├── resume-project/
└── market-analysis/
```

각 Work는 하나의 외부 Workspace를 연결한다.

예:

```text
Work: GIMS
Workspace:
~/Developer/GIMS
```

---

## 2.3 Control Center Data 영역

Control Center의 기존 `data` 폴더는
**공용 산출물 관리 용도**로 제한한다.

예:

```text
AI_Control_Center/data/
└── shared/
    ├── global/
    └── category/
```

이 영역에는 사용자가 명시적으로 공용화한 결과물만 저장한다.

예:

```text
data/shared/global/coding-principles.md
data/shared/category/finance/market-analysis-template.md
```

다음은 이 영역에 저장하지 않는다.

- 개별 Work의 원본 자료
- 개별 Work의 docs
- 개별 Work의 소스코드
- 개별 Work의 일반 Artifact
- 개별 Work의 임시 실행 파일
- Work별 `runs/`
- Work별 `context/`
- Work별 `decisions/`
- Work별 `work.json`

---

# 3. Work의 의미 변경

Work는 더 이상 Control Center 내부 폴더를 의미하지 않는다.

```text
Work
= Control Center가 관리하는 논리적 작업 단위
+ 연결된 외부 Workspace
```

예:

```text
Work
Name: AI IP Studio
Category: 기획
Workspace: ~/Developer/AI-IP-Studio
```

DB에는 Workspace 경로만 기록한다.

실제 파일은 Workspace에 존재한다.

---

# 4. Work 생성 방식

새 Work 생성 시 두 가지 방식을 제공한다.

```text
새 작업

○ 새 Workspace 만들기
○ 기존 폴더 연결하기
```

---

## 4.1 새 Workspace 만들기

기본 위치:

```text
~/Developer/
```

UI 예:

```text
새 Workspace 만들기

기본 위치
~/Developer

폴더 이름
[ AI-IP-Studio ]

생성 위치
~/Developer/AI-IP-Studio

[작업 만들기]
```

생성 후 해당 폴더를 Work의 Workspace로 연결한다.

---

## 4.2 기존 폴더 연결하기

이미 존재하는 프로젝트를 선택한다.

예:

```text
~/Developer/GIMS
```

UI:

```text
기존 폴더 연결

[폴더 선택]

선택된 Workspace
~/Developer/GIMS
```

Control Center는 선택된 폴더를 복사하지 않는다.

---

# 5. LINKED Workspace 비침투 원칙

기존 Workspace를 연결했을 때
Control Center가 관리 목적으로 임의의 파일 / 폴더를 생성하지 않는다.

자동 생성 금지 예:

```text
artifacts/
context/
runs/
decisions/
work.json
.control-center/
```

또한 Control Center 전용 `AGENTS.md`를 자동 생성하지 않는다.

사용자가 명시적으로 `AGENTS.md` 생성을 선택한 경우에만 Workspace에 생성한다.

---

# 6. Work 자료 관리

Work의 실제 자료는 Workspace 기준 상대경로로 관리한다.

예:

```text
Workspace:
~/Developer/AI-IP-Studio

자료:
docs/architecture.md
docs/phase2-requirements.md
research/market-report.pdf
```

UI에서는 가능하면 전체 절대경로 대신 상대경로를 보여준다.

예:

```text
docs/architecture.md
```

필요할 때만 전체 경로를 표시한다.

---

# 7. Markdown 생성

Task 또는 Work 화면에서 새 Markdown을 만들 때
기본 생성 위치는 현재 Workspace다.

예:

```text
Workspace
~/Developer/AI_Control_Center

경로
docs/

파일 이름
phase2-implementation-plan.md
```

실제 생성:

```text
~/Developer/AI_Control_Center/docs/phase2-implementation-plan.md
```

Control Center의 내부 `data` 폴더에 생성하지 않는다.

---

# 8. Markdown 문서 종류

UI에서 다음 문서 유형을 선택할 수 있다.

- 일반 Markdown
- AGENTS.md
- Requirements
- Architecture
- Implementation Plan
- Decision / Note

이 구분은 기본적으로 Template / Usage Type으로 취급한다.

예:

```text
문서 종류
[ Implementation Plan ]

경로
docs/

파일 이름
phase2-implementation-plan.md

내용
[ 직접 입력 ]
```

---

# 9. Artifact 저장 원칙

Artifact는 항상 Control Center 내부 `artifacts/` 폴더에 복사하지 않는다.

Artifact는 **결과 객체**로 관리한다.

최소 Location Type:

```text
WORKSPACE
SHARED
EXTERNAL
```

---

## 9.1 WORKSPACE

현재 Work의 Workspace 안에 존재하는 결과물.

예:

```text
~/Developer/GIMS/docs/report.md
```

DB에는 다음과 같이 저장할 수 있다.

```text
location_type = WORKSPACE
relative_path = docs/report.md
```

---

## 9.2 SHARED

사용자가 명시적으로 공용 Library에 Publish한 결과물.

예:

```text
AI_Control_Center/data/shared/global/coding-principles.md
```

또는 Category 단위:

```text
AI_Control_Center/data/shared/category/development/backend-rules.md
```

공용화 전에는 이 위치로 자동 복사하지 않는다.

---

## 9.3 EXTERNAL

Workspace 외부 파일을 참조하는 경우.

예:

```text
~/Documents/reference.pdf
```

Control Center는 원본을 임의로 이동하지 않는다.

---

# 10. Shared Artifact Publish

Work 결과물을 다른 Work에서도 사용하고 싶은 경우에만
Shared 영역에 Publish한다.

예:

```text
Workspace Artifact
docs/coding-principles.md

        ↓

[공용 산출물로 등록]

        ↓

Scope
○ Category
○ Global

        ↓

Control Center data/shared/
```

기본 상태에서는 Work Artifact를 공용 영역에 자동 등록하지 않는다.

---

# 11. Control Center 내부 상태 데이터

Work 파일과 Control Center 내부 상태는 구분한다.

다음은 사용자 Workspace 파일이 아니다.

- Work ID
- Run ID
- Request ID
- Thread ID
- Turn ID
- Workflow 상태
- TaskRun 상태
- Artifact Relation
- Event
- Runtime metadata

이 정보는 DB에서 관리한다.

가능하면 Application Repository의 Work 폴더 구조와 분리한다.

예:

```text
~/.control-center/
├── control.db
├── runtime/
└── metadata/
```

중요:

`~/.control-center/`는 시스템 상태 영역이며,
사용자 Work의 실제 작업 파일을 저장하는 공간이 아니다.

---

# 12. 최종 책임 분리

```text
~/Developer/AI_Control_Center/
        │
        └─ Control Center Application

~/Developer/<project>/
        │
        └─ 실제 Work / 프로젝트 파일

~/.control-center/
        │
        └─ DB / Runtime / 내부 Metadata

AI_Control_Center/data/shared/
        │
        └─ 사용자가 공용화한 Shared Artifact
```

즉 네 영역을 분리한다.

### Application

```text
프로그램 자체
```

### Workspace

```text
사용자 실제 작업
```

### Internal State

```text
Control Center가 동작하기 위해 필요한 상태
```

### Shared Library

```text
여러 Work에서 재사용할 목적으로 사용자가 공용화한 산출물
```

---

# 13. UI 변경

## 13.1 Work Header

현재처럼 다음 경로를 기본 노출하지 않는다.

```text
관리 데이터:
/.../AI_Control_Center/data/categories/.../works/...
```

대신:

```text
Workspace
~/Developer/AI-IP-Studio

[폴더 열기]
[Workspace 변경]
```

를 보여준다.

Control Center 내부 경로는 고급 정보로 이동한다.

---

## 13.2 새 Work

```text
새 작업

작업 이름
[                ]

Category
[                ]

Workspace

○ 새 Workspace 만들기
○ 기존 폴더 연결

기본 위치
~/Developer
```

---

## 13.3 자료 추가

```text
자료 추가

[기존 Workspace 파일]
[새 Markdown 만들기]
[Shared Library에서 추가]
[외부 파일 연결]
```

각 자료의 출처를 명확히 표시한다.

예:

```text
architecture.md
Workspace · docs/architecture.md

coding-principles.md
Shared · Global

reference.pdf
External
```

---


# 14. Acceptance Criteria

다음 조건을 만족해야 한다.

1. 새 Work 생성 기본 Root가 `~/Developer`로 설정된다.
2. 새 Workspace를 `~/Developer/<name>`으로 생성할 수 있다.
3. 기존 `~/Developer/...` 프로젝트를 Work로 연결할 수 있다.
4. Work 실제 파일이 `data/categories/.../works/...`에 자동 생성되지 않는다.
5. Work Header에서 실제 Workspace 경로를 확인할 수 있다.
6. Workspace를 Finder에서 직접 열 수 있다.
7. Workspace 기준 상대경로로 자료를 선택할 수 있다.
8.  웹페이지에서 원하는 작업에 필요한 새 Markdown을 생성할 수 있다.
10. 기존 Workspace를 연결할때 공용부분은 ~/Developer/AI_Control_Center/data/ 적재되고 개별 부분은 해당 Workspace에 생성된다. .
12. Shared 영역으로 등록되기전 임시폴더에 적재되고 사용자가 Publish 한 Artifact만 Shared 영역에 적재된다.(임시폴더에 해당 잔여파일 삭제)
13. Shared Artifact를 다른 Work에서 선택할 수 있다.
16. 기존 Work를 외부 Workspace로 전환할 수 있다.
17. Phase 1 단일 실행과 Phase 2 Workflow 모두 동일한 Workspace 모델을 사용한다.

---

# 15. 완료 후 기대 구조

```text
~/Developer/
├── AI_Control_Center/
│   ├── app/
│   ├── docs/
│   ├── ...
│   └── data/
│       └── shared/
│
└──  develop(카테고리)/
       ├── GIMS(work)/
       │    ├── src/
       │    ├── docs/
       │    └── ... 
       └── AI-IP-Studio/
           ├── src/
           ├── docs/
           └── ... 


~/.control-center/
├── control.db
├── runtime/
└── metadata/
```

사용자가 보는 핵심 구조는 더 단순하다.

```text
Work
↓
Workspace
↓
자료 / 코드 / 문서 / 결과물
```

Control Center 내부 상태와 저장 구조는 일반 사용자 화면에서 최소화한다.
