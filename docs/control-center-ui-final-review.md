# Control Center 최종 UI Review

작성일: 2026-09-29

## 적용 기준

- 기능 구조의 Source of Truth: `control-center-ui-final-requirements.md`.
- 디자인 구조: `control-center-ui-design-references.md`의 Shell, Work / Run, Flow + Task Detail, DAG, 운영 Dashboard 원칙.
- **최신 사용자 요청을 우선하여 Green Accent와 밝은 배경 대신 블랙·차콜·그레이 테마를 적용했다.** 상태도 색상에만 의존하지 않고 아이콘, 명도, 테두리, 텍스트로 구분한다.
- Backend API, 실행 엔진, DB 스키마는 재설계하지 않았다.
- Phase 4 참고 문서의 저장소 실제 파일명은 `phase4-requirement.md`다.

## 최종 정보 구조와 화면 개선

Application은 Dashboard와 Category / Work 탐색으로 구성한다. Work 상단에는 이름, Category, Workspace, 실행 상태를 표시하고, 개요·실행·Workflow·자료·결과물·작업 도구·일정·검토·활동의 9개 탭을 제공한다.

| 영역 | 구현 내용 |
|---|---|
| Shell | 블랙톤, 일관된 선택·호버·포커스, Category / Work 검색, `⌘/Ctrl+K`, 사이드바 접기, 모바일 레이아웃 |
| Dashboard | Phase 5 Aggregation API 사용. 진행 항목과 확인 필요 항목을 중심에 배치. 일정, Context, Usage, 과거 기록은 상세 영역으로 분리 |
| Work 개요 | 진행·승인·예정 요약, 실패·복구 알림, 최근 실행·결과물. 부가 운영 상태는 접기 |
| 실행 | 요청 작성과 응답을 중심으로 배치. 같은 요청 재실행과 대화 계속을 구분. 분기·Compact·Handoff는 대화 관리 메뉴. 실행 설정·기본값·이력·Raw Event / Manifest는 상세로 분리 |
| Workflow | 왼쪽 Flow, 오른쪽 선택 Task 설정. 기본·입력·출력·실행 조건·설정 Override 그룹. 실제 의존 관계 SVG 연결선과 병렬 / 합류 관계 |
| 실행 그래프 | Task 완료 진행률, 실행 / 완료 / 실패 / 차단 아이콘, 승인 대기 배지, 선택 강조, 실행 연결선 애니메이션, 확대·축소·맞춤·배경 드래그 이동 |
| 자료 | Workspace, Shared, External, 이전 결과물, Context Pack, Resource 출처 탭. 탭을 바꿔도 자료 선택 유지 |
| 결과물 | 목록 → 미리보기·다운로드·출처 / 전달 관계·Library Publish |
| 작업 도구 | Diff 범위 선택·파일 변화·접힌 Patch, 공통 실행 설정을 쓰는 AI Review, 완료 결과의 명시적 Artifact 저장 |
| 일정 / 검토 | 예약과 Delayed Resume, Approval / Revision을 각각 독립 탭에 배치 |
| 활동 | 요청·실행·Workflow 기록에서 상세 화면으로 이동 |

Run / Thread / Turn / Artifact ID, 내부 경로, Raw Manifest / Event는 기본 화면에서 숨긴다. 실행 중에는 원시 이벤트 대신 짧은 진행 설명을 표시한다. 일반적인 전환과 상태 효과에는 `prefers-reduced-motion`을 적용했다.

## Phase 1~5 기능 연결 상태

아래는 구현·코드 연결 범위다. 전체 End-to-End 통과를 의미하지 않는다.

| Phase | 연결한 기능 | 사용 API / 기존 경로 |
|---|---|---|
| 1 | Category / Work 생성·편집·보관, 새 / 기존 Workspace 연결, 자료 추가, 단일 요청, 실행 상세, 추가 지시·취소·재시도·복구, Artifact | `/categories`, `/works`, `/runs`, `/requests/{id}/retry`, `/artifacts`, 기존 Storage API |
| 2 | Workflow CRUD, Task DAG, 입력 / 출력 binding, 실행, Task 시도·취소·재시도·분기, 템플릿, Artifact lineage와 Publish | `/workflows`, `/workflow-runs`, `/task-runs`, `/workflow-templates`, `/library` |
| 3 | AUTO / REVIEW_AFTER / APPROVAL_REQUIRED, 승인·반려·수정 요청·승인 후 Publish, Pause / Resume, 단발 / 반복 예약, 활성화, 발생 기록, 시간 후 이어하기 | `/approvals`, `/workflow-runs/{id}/pause`, `/resume`, `/schedules`, `/delayed-resumes` |
| 4 | 새 대화, 기존 대화 계속, Fork, Compact와 상태 확인, 임시 질문·폐기·결론 전달·승격, Pack 생성·미리보기·확인·버전, Handoff, 대화 lifecycle, Context Inspector | `/works/{id}/conversations`, `/conversations`, `/queries`, `/resources`, `/context-packs`, `/runs/{id}/context` |
| 5 | 운영 집계·사용량·Runtime·경고·상세 이동·기존 제어, Git Diff, AI Review 및 결과 저장 | `/operations/dashboard`, `/works/{id}/tools`, `/tools/diff`, `/tools/reviews`, `/work-tools/reviews/{id}/save` |
| 공통 | Model / Reasoning / Personality / Permission / Speed, Global → Category → Work → Override | 기존 Execution Settings Resolver와 공통 Frontend editor. 미지원 Personality 비활성 유지 |

Dashboard 상태와 총수는 서버 집계를 표시한다. 로컬에서 실행 상태를 다시 계산하지 않는다. 그래프의 완료율은 선택 Workflow의 현재 Task 시도에 대한 표시이며 승인 완료율과 구분한다. Review는 기존 Run 경로를 사용하고 Diff 조회는 AI 실행을 생성하지 않는다.

## 요청한 레거시 데이터 정리

`data/categories`에 남아 있던 약 18MB의 두 LEGACY Work와 연결된 활성 DB 항목을 정리했다.

- 삭제 Work: `보유종목 분석`, `자기소개서`.
- 삭제된 빈 Category: `주식`, `취업`.
- 연결 항목: 요청 3개, 실행 4개, Source 1개, 이벤트 16개, Workflow 2개, Task 정의 8개, 의존 관계 6개, 템플릿 1개, 비활성 예약 1개.
- 해당 레거시 디렉터리 및 실행 manifest 4개 제거.
- 외부 Workspace Work `ppt느낌 웹페이지제작`과 `~/Developer/makePage`는 유지.

Backend 프로세스 잠금과 DB transaction 아래 정리했고, DB 외래키 위반은 0건이었다. 이 정리는 현재 `control.db`를 대상으로 했다. 기존 마이그레이션 백업 DB는 수정하지 않았다.

## 확인 범위와 제한

- 사용자 요청에 따라 진행 중이던 End-to-End 검증을 중단했으며, 이후 브라우저 검증이나 실제 모델 호출을 재개하지 않았다.
- 변경 JavaScript의 구문 검사는 통과했다. 데이터 삭제 시 대상 경로, 남은 Work, 외래키 관계를 확인했다.
- 이전 브라우저 검증에서 발견한 늦은 Work 응답의 탭 초기화 문제를 수정했다. 이후 UI의 시각 결과와 전체 사용자 여정은 재검증하지 않았으므로 End-to-End 통과를 주장하지 않는다.
- 기존 `tests/browser_review.py`의 화면 이동 선택자를 새 탭과 접힌 동작에 맞춰 조정했으며 실행하지 않았다.
- 최근 Dashboard Review는 집계 API의 최근 실행 페이지 기준이다. Diff는 서버 저장 이력이 없어 현재 화면 세션에서 조회한 기록만 표시한다.
- Runtime이 제공하지 않는 Usage / Rate Limit / Goal 값은 추정하지 않는다. Compact·Fork 등 Runtime 제약은 기존 Backend 계약을 따른다.
- 새 외부 UI 의존성이나 CDN은 추가하지 않았다. SVG / CSS / 기존 JavaScript로 블랙톤과 그래프 상호작용을 구현했다.

## 주요 변경 파일

- `app/static/index.html`, `style.css`: Shell, 탭, 공통 레이아웃, 블랙톤, 반응형, 상태 효과.
- `app/static/control-center.js`: 탐색, 화면 전환, 집계 Dashboard, 자료 출처 탭, 검색.
- `app/static/presentation.js`: 상세 접기, 그래프 확대 / 축소 / 이동, 화면 편의 동작.
- `app/static/work-tools.js`: Diff / AI Review / Artifact 저장 연결.
- 기존 `app.js`, `workflows.js`, `workflow-operations.js`, `conversations.js`, `storage.js`, `execution-settings.js`: 기존 기능을 새 화면 구조에 연결.
