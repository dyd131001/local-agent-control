# AI Project Control Center — UI Design References

## 1. 목적

이 문서는 Control Center UI를 개선할 때 참고할 외부 제품과,
각 제품에서 **어떤 요소만 참고할지**를 명확히 정의한다.

목표는 특정 서비스를 그대로 복제하는 것이 아니다.

다음 원칙을 따른다.

- 전체 시각 언어는 **Linear / Vercel 계열의 현대적인 개발자 도구 UI**를 지향한다.
- Workflow 편집 구조는 **Retool Workflows**를 참고한다.
- Workflow 실행 관계 표현은 **GitHub Actions**를 참고한다.
- Dashboard / 운영 상태 표현은 **Dagster**를 참고한다.
- 각 레퍼런스는 특정 기능에만 적용하며 서로의 UI를 무작정 섞지 않는다.
- 현재 Control Center의 저채도 Green Accent는 유지한다.
- 기능이 늘어나도 한 화면에 Form과 Card를 계속 쌓는 방식은 피한다.

---

# 2. 전체 Design Direction

Control Center는 다음과 같은 인상을 목표로 한다.

```text
현대적인 개발자 도구
+
개인 작업 관리 도구
+
AI Workflow 운영 화면
```

시각적으로는:

```text
Linear
  ↓
전체 Layout / Sidebar / 정보 계층

Vercel
  ↓
실행 기록 / 상태 / Work Overview

Retool
  ↓
Workflow Editor

GitHub Actions
  ↓
Task Dependency / Run Graph

Dagster
  ↓
Dashboard / 운영 상태 / 실행 관찰
```

---

# 3. Linear — 전체 Layout / Sidebar / Work 구조

## 적용 대상

- 전체 Application Shell
- 좌측 Sidebar
- Category / Work 탐색
- Work Header
- Work Tab Navigation
- Dashboard의 기본 시각 언어
- Typography / spacing / active state

## 참고할 요소

- Sidebar는 본문보다 약간 낮은 대비를 사용한다.
- 선택된 메뉴만 명확한 Active State를 가진다.
- 본문은 충분한 여백을 확보한다.
- 화면 전체를 Card로 채우지 않는다.
- Header / Navigation / View control의 위치를 화면마다 일관되게 유지한다.
- 정보 밀도는 높지만 선과 색을 과도하게 사용하지 않는다.
- 제목, 보조정보, metadata의 계층을 Typography로 구분한다.

## Control Center 적용 예

```text
┌───────────────────────────────────────────────────────────┐
│ Sidebar │ 자기소개서                                     │
│         │ [개요] [단일 실행] [Workflow] [자료] [결과물] │
│ 취업    │────────────────────────────────────────────────│
│  └ 자기 │                                                   │
│ 주식    │                Main Content                    │
│         │                                                   │
└───────────────────────────────────────────────────────────┘
```

## 직접 복제하지 않을 것

- Linear 고유 색상
- Linear 고유 Icon
- Linear의 Issue 중심 정보 구조

Control Center의 Category / Work / Run / Artifact 구조는 유지한다.

## 공식 참고 페이지

https://linear.app/changelog/2026-03-12-ui-refresh

## PNG Reference

https://webassets.linear.app/images/ornj730p/production/696c7f2b0921b5e3163710ea1b310dfb8e4e377c-3600x2080.png?auto=format&dpr=2&q=95

---

# 4. Vercel — Work Overview / Run History / Status UI

## 적용 대상

- Work Overview
- 최근 실행
- Run History
- 현재 실행 상태
- Artifact History
- 실패 / 완료 / 대기 Badge
- 실행 상세

## 참고할 요소

- 가장 중요한 현재 상태를 먼저 보여준다.
- 목록에서 상태를 빠르게 Scan할 수 있게 한다.
- Badge는 작고 일관되게 사용한다.
- 내부 ID보다 사람이 이해하는 이름을 먼저 보여준다.
- 상세정보는 클릭했을 때 펼친다.
- 실행 목록은 과도한 Card보다 정돈된 Row 구조를 우선한다.

## Control Center 적용 예

```text
최근 실행

자기소개서 분석        완료      Sol · Medium     10분 전
문장 수정              실행 중   Luna · Medium    지금
시장 조사              실패      Astra · High     1시간 전
```

Run ID와 Thread ID는 기본 목록에서 숨긴다.

## 공식 참고 페이지

https://vercel.com/changelog/deployment-filters-for-project-dashboard

## PNG Reference

https://assets.vercel.com/image/upload/contentful/image/e5382hct74si/1I6wKPapdDZjZ0iRKjFxBe/03a3248b6686034d6b5cc12560581f35/Deployment_Filtering-1.png

---

# 5. Retool Workflows — Workflow Editor

## 적용 대상

- Workflow 편집
- Task 선택
- Task별 설정
- Flow 영역과 Detail 영역 분리
- Task Input / Output 설정

## 참고할 요소

Workflow 전체 구조와 선택한 Task의 상세 설정을 분리한다.

권장 Control Center Layout:

```text
┌──────────────────────┬───────────────────────────────────┐
│ Workflow Flow        │ 선택한 Task                      │
│                      │                                   │
│ ① 설계              │ 기본 설정                        │
│     │                │ 입력 자료                        │
│     ▼                │ 출력 결과물                      │
│ ② 구현              │ 실행 조건                        │
│     │                │ Model / Reasoning                │
│     ▼                │                                   │
│ ③ 검토              │                                   │
│                      │                                   │
│ [+ 작업 추가]        │                                   │
└──────────────────────┴───────────────────────────────────┘
```

Task 설정을 하나의 긴 세로 Form으로 만들지 않는다.

## 참고할 Interaction

- Flow에서 Task 클릭
- 선택 Task 강조
- 상세 Panel에서 해당 Task 편집
- Input / Output / 실행 조건을 별도 그룹으로 구분
- 전체 Workflow 구조는 항상 보이게 유지

## 직접 복제하지 않을 것

Phase 2에서는 완전한 자유 Canvas / Drag & Drop Workflow Editor는 필수로 하지 않는다.

현재는 단순화된 DAG Flow + Task Detail Panel이면 충분하다.

## 공식 참고 페이지

https://docs.retool.com/education/labs/examples/inventoryreorderwf

## PNG Reference

https://docs.retool.com/assets/images/workflowinit-42ae88ba7e3f4d3ac85e32381b23ff14.png

---

# 6. GitHub Actions — Workflow Run / Dependency Graph

## 적용 대상

- Workflow 실행 상태
- Task Dependency
- 순차 / 병렬 관계
- Task Status
- 어떤 Task가 무엇을 기다리는지 표현

## 참고할 요소

Task를 Card 또는 Node로 표시하고 연결선으로 Dependency를 표현한다.

예:

```text
             ✓ 설계
                │
        ┌───────┴───────┐
        ▼               ▼
 ● Backend 구현      ● UI 구현
        │               │
        └───────┬───────┘
                ▼
             ○ 검토
```

상태는 Node 자체에서 바로 확인할 수 있게 한다.

예:

- ✓ 완료
- ● 실행 중
- ○ 대기
- ! 실패
- 잠금 / 차단

Task를 클릭하면 상세 정보 영역에서 다음을 표시한다.

```text
Backend 구현

상태       실행 중
Model      Luna
Reasoning  Medium

Input
- implementation-plan.md

Output
- backend-result.md
```

## 공식 참고 페이지

https://docs.github.com/en/actions/how-tos/monitor-workflows/use-the-visualization-graph

## PNG Reference

https://docs.github.com/assets/cb-63715/images/help/actions/workflow-graph.png

---

# 7. Dagster — Dashboard / 운영 상태

## 적용 대상

- Dashboard
- 전체 Work / Workflow 상태
- 실행 중 / 실패 / 대기
- 장기적으로 Schedule / Automation
- Run monitoring
- 운영 화면

## 참고할 요소

Dashboard는 단순 숫자 통계가 아니라 현재 시스템이 무엇을 하고 있는지를 보여준다.

Control Center Dashboard가 우선 답해야 할 질문:

1. 지금 무엇이 실행 중인가?
2. 무엇이 대기 중인가?
3. 무엇이 실패했는가?
4. 사용자가 확인할 항목이 있는가?
5. Workflow가 어디까지 진행됐는가?
6. 최근 어떤 결과물이 생성됐는가?

예:

```text
진행 중
3

대기
2

확인 필요
1

최근 결과물
5
```

그리고 그 아래 실제 진행 항목을 표시한다.

```text
자기소개서 만들기
3 / 4 Task 완료

✓ 경력 분석
✓ 경험 정리
● 자기소개서 작성
○ 최종 검토
```

## 직접 복제하지 않을 것

Dagster의 높은 정보 밀도와 데이터 엔지니어링 전용 용어는 그대로 사용하지 않는다.

Control Center에서는 일반 사용자가 이해하기 쉬운 이름으로 단순화한다.

## 공식 참고 페이지

https://docs.dagster.io/guides/operate/webserver

## PNG Reference

https://docs.dagster.io/assets/images/factory-floor-7eb8447fdb3081b7c8a7428030cc2cba.png

---

# 8. 화면별 Reference Mapping

| Control Center 화면 | 주 Reference | 보조 Reference |
|---|---|---|
| Application Shell | Linear | Vercel |
| Sidebar | Linear | - |
| Dashboard | Dagster | Linear |
| Work Overview | Vercel | Linear |
| 단일 실행 | Vercel | Linear |
| Run History | Vercel | Dagster |
| Workflow 목록 | Linear | Vercel |
| Workflow 편집 | Retool | Linear |
| Workflow 실행 | GitHub Actions | Dagster |
| Task Detail | Retool | Vercel |
| Artifact 목록 | Vercel | Linear |
| 향후 Schedule | Dagster | Linear |

---

# 9. Visual Rules

## Layout

- Content 영역은 충분한 여백을 둔다.
- 모든 영역을 Card로 감싸지 않는다.
- Card는 실제 정보 단위가 명확할 때만 사용한다.
- 긴 화면 하나보다 Tab / Panel로 역할을 분리한다.
- 주요 작업 버튼의 위치를 화면마다 일관되게 유지한다.

## Color

- 현재 Control Center의 Green Accent를 유지한다.
- 기본 배경은 밝은 Neutral 계열을 사용한다.
- Sidebar는 Main Content보다 약간 낮은 대비를 사용한다.
- Status Color 외에는 지나치게 많은 색을 사용하지 않는다.

## Border / Shadow

- 얇은 Border를 기본으로 한다.
- 강한 Drop Shadow 사용을 피한다.
- Modal 등의 Layer 구분이 필요한 곳에서만 Shadow를 사용한다.
- Border Radius를 화면 전체에서 일관되게 사용한다.

## Typography

정보 계층을 명확히 구분한다.

```text
Page Title
Section Title
Primary Content
Secondary Metadata
Technical / Advanced Info
```

UUID / 절대경로 / 내부 Runtime ID가 본문보다 시각적으로 강하게 보여서는 안 된다.

## State

다음 상태는 모든 화면에서 동일한 시각 언어를 사용한다.

- 실행 준비
- 대기
- 실행 중
- 완료
- 실패
- 취소
- 차단

## Interaction

다음 상태를 시각적으로 명확히 구분한다.

- Hover
- Selected
- Active
- Disabled
- Running
- Failed
- Completed

클릭 가능한 항목은 클릭 가능하다는 것이 보여야 한다.

---

# 10. Dashboard Design Direction

Dashboard 우선순위:

```text
현재 진행상황
↓
확인 필요
↓
최근 Work / Workflow
↓
최근 결과물
↓
통계
```

현재처럼 통계 숫자 3개가 화면의 가장 중요한 정보가 되지 않도록 한다.

Dashboard는 "얼마나 많이 만들었는가"보다
"지금 무엇이 진행되고 있는가"를 우선한다.

---

# 11. Work Screen Design Direction

Work를 열었을 때 모든 기능을 한 페이지 아래에 나열하지 않는다.

권장:

```text
자기소개서

Workspace: ~/Developer/job-application
[폴더 열기]

[개요] [단일 실행] [Workflow] [자료] [결과물] [활동]
```

향후:

```text
[일정]
[검토]
```

등을 추가할 수 있다.

---

# 12. Workflow Design Direction

Workflow는 다음 정보를 화면에서 설명 없이 이해할 수 있어야 한다.

- 무엇이 먼저 실행되는가
- 무엇이 동시에 실행되는가
- 무엇이 무엇을 기다리는가
- 어떤 Artifact를 전달하는가
- 어떤 Model이 실행하는가
- 현재 어떤 상태인가

예:

```text
① 구현 설계
Astra · High
↓ implementation-plan.md

       ┌────────────────┐
       ▼                ▼

② Backend 구현       ③ UI 구현
Luna · Medium         Luna · Medium

       └────────┬───────┘
                ▼

④ 통합 검토
Sol · High
```

---

# 13. Agent Implementation Instruction

UI를 구현하는 Agent는 단순히:

```text
"Linear처럼 만들어라."
```

라고 해석하지 않는다.

각 Reference에서 이 문서에 명시된 요소만 선택적으로 참고한다.

우선순위:

1. 정보 구조
2. 사용자의 현재 위치와 상태 인지
3. 실행 흐름 가시성
4. 선택 / Hover / Status 표현
5. 여백과 Typography
6. 장식

디자인을 위해 기존 기능이나 데이터 구조를 임의로 제거하지 않는다.

Reference의 특정 UI를 픽셀 단위로 복제하지 않는다.

현재 Control Center의 기능 구조와 한국어 UI를 기준으로 재구성한다.

---

# 14. Reference Links Summary

## Linear

Page:
https://linear.app/changelog/2026-03-12-ui-refresh

PNG:
https://webassets.linear.app/images/ornj730p/production/696c7f2b0921b5e3163710ea1b310dfb8e4e377c-3600x2080.png?auto=format&dpr=2&q=95

## Vercel

Page:
https://vercel.com/changelog/deployment-filters-for-project-dashboard

PNG:
https://assets.vercel.com/image/upload/contentful/image/e5382hct74si/1I6wKPapdDZjZ0iRKjFxBe/03a3248b6686034d6b5cc12560581f35/Deployment_Filtering-1.png

## Retool Workflows

Page:
https://docs.retool.com/education/labs/examples/inventoryreorderwf

PNG:
https://docs.retool.com/assets/images/workflowinit-42ae88ba7e3f4d3ac85e32381b23ff14.png

## GitHub Actions

Page:
https://docs.github.com/en/actions/how-tos/monitor-workflows/use-the-visualization-graph

PNG:
https://docs.github.com/assets/cb-63715/images/help/actions/workflow-graph.png

## Dagster

Page:
https://docs.dagster.io/guides/operate/webserver

PNG:
https://docs.dagster.io/assets/images/factory-floor-7eb8447fdb3081b7c8a7428030cc2cba.png

---

# 15. 참고 이미지 사용 주의

위 이미지는 구현 참고용이다.

- 이미지 자체를 Control Center에 배포 자산으로 포함하지 않는다.
- UI 구조 / 정보 계층 / Interaction 참고 목적으로만 사용한다.
- 외부 이미지 URL이 변경될 수 있으므로 공식 페이지 링크도 함께 유지한다.
