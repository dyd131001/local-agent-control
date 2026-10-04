docs/phase3-requirements-v2.md,
docs/architecture.md,
docs/runtime-capabilities.md와 현재 Phase 1 / Phase 2 코드를 확인해.

기존 Phase 1 / Phase 2 구조를 최대한 유지하면서 Phase 3를 끝까지 구현해.

구현 전에 현재 구조에서 Phase 3 요구사항과 직접 충돌하는 부분만 짧게 확인해.
구조를 크게 바꿔야 하는 문제가 없다면 별도의 분석 문서를 작성하지 말고 바로 구현을 시작해.

세부 작업 분해와 구현 순서는 네가 결정해.

핵심 목표는 기존 Managed Workflow 위에 다음 운영 기능을 추가하는 것이다.

- Task별 AUTO / REVIEW_AFTER / APPROVAL_REQUIRED
- Approval Gate
- Approval Inbox
- Reject / Request Revision / Approve & Publish
- Revision 시 기존 Artifact 보존 및 새 Run / Artifact 생성
- Workflow 예약 실행
- 반복 Schedule
- Delayed Resume
- Pause / Resume
- Workflow Monitoring
- Backend 재시작 후 상태 복구

중요 원칙:

- Approval / Schedule / Revision이 Codex를 직접 호출하지 말 것
- 모든 실행은 기존 Workflow Engine / DAG Scheduler / Run Service / Codex Gateway를 재사용할 것
- Approval 상태와 TaskRun 상태를 섞지 말 것
- Artifact Review 상태와 Publish 상태를 분리할 것
- APPROVAL_REQUIRED 상태에서는 Backend가 downstream Task 실행을 실제로 차단할 것
- UI에서 버튼만 비활성화하는 방식으로 Approval Lock을 구현하지 말 것
- Approval 처리는 DB Transaction과 상태 검증을 통해 중복 실행을 막을 것
- Revision은 기존 Run / Artifact를 덮어쓰지 말고 새 Run / Artifact를 생성할 것
- Schedule Trigger는 새 WorkflowRun을 생성하고 기존 DAG Scheduler에 넘길 것
- 예약/반복 실행은 Cron 문법을 사용자에게 직접 요구하지 않는 UI로 제공할 것
- Delayed Resume는 기존 Run을 부활시키지 말고 새 Run History로 남길 것
- Resume에 필요한 상태는 AI의 기억이 아니라 Checkpoint / Artifact / Context Manifest로 보존할 것
- Backend 재시작 후 Approval / Schedule / Delayed Resume 상태를 복구할 것
- Runtime Permission Approval과 Workflow Artifact Approval을 분리할 것
- AI Worker가 Approval / Schedule / control.db를 직접 수정하지 못하게 할 것
- AI Planner / Automatic Model Routing / Vector DB 등 이후 Phase 기능은 구현하지 말 것

특히 다음은 반드시 실제 실행으로 확인해:

- APPROVAL_REQUIRED Task에서 Workflow 정지
- Approve 후 downstream Task 자동 진행
- Reject
- Request Revision → 새 Run → 새 Artifact → 재승인
- 중복 Approve 요청 시 downstream 중복 실행 방지
- Approve와 Publish 상태 분리
- ONE_TIME 예약 실행
- RECURRING Schedule 실행
- Schedule 활성/비활성
- Backend 재시작 후 Schedule 복구
- WAITING_APPROVAL 상태 복구
- Schedule Misfire 처리
- 5시간 후 Delayed Resume
- Delayed Resume 시 새 Run History 생성
- Pause / Resume
- Dashboard에서 실행 중 / 승인 대기 / 예약 작업 표시
- 기존 Phase 1 단일 Run Regression Test
- 기존 Phase 2 A → B/C → D Workflow Regression Test

구현 중 필요한 테스트와 수정은 스스로 반복해.

## 검증 정책

실제 Codex Runtime을 반복 호출하지 않는다.

기존 Runtime capability가 이미 확인된 기능은 재검증하지 않는다.

대표 흐름만 최소 확인한다.

- Approval Gate → Approve → downstream 진행
- Schedule → WorkflowRun 생성
- Pause → Resume
- Backend 재시작 후 상태 복구

나머지는 현재 구현과 DB 상태 전이를 기준으로 확인한다.
완료 후 docs/architecture.md를 실제 최종 구현과 일치하도록 갱신한다.