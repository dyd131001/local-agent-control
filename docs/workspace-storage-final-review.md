# Workspace / Storage 최종 Review

작성일: 2026-09-29

Source of Truth: [control-center-workspace-storage-requirements.md](control-center-workspace-storage-requirements.md)

## 변경사항

### 저장소와 기존 데이터 호환성

- 새 Work는 기본 `~/Developer/<폴더 이름>`에 Workspace를 만들거나 기존 폴더를 연결한다. 생성 위치를 직접 지정할 수 있으므로 Category 하위 폴더도 사용할 수 있다.
- 새 Work 생성에서 `data/categories/.../works/...`를 만들지 않는다. 기존 폴더 연결 자체는 파일 복사나 `AGENTS.md`, `work.json`, `context/`, `runs/`, `.control-center/` 생성을 수행하지 않는다.
- 신규 설치의 내부 상태 기본 경로는 `~/.control-center/`다. 기존 Application 내부 `.control-center-state/control.db`가 있는 설치는 그 DB를 그대로 사용한다. 환경변수로 상태·Workspace·Shared Data·Runtime 임시 위치를 지정할 수 있다.
- 기존 Work는 `LEGACY` 저장 방식으로 유지한다. 사용자가 Workspace 변경을 요청하면 외부 연결 정보만 바꾸며 기존 파일과 기존 Source/Artifact 경로를 유지한다. 활성 또는 결과 불명 Run, 활성 Workflow가 있으면 변경을 거절한다.
- 실행 입력/작업복제본/후보 결과는 분리된 시스템 임시 Runtime 경로를 사용한다. 단일 실행과 Workflow가 같은 resolver를 사용하며 manifest에 실행 당시 저장 위치를 고정한다.

### 자료와 문서

- 기존 Workspace 파일을 상대경로로 탐색·선택하여 Source 참조로 등록한다. 새 저장 방식에서는 원본을 내부 Data에 복사하지 않는다.
- 외부 파일은 `EXTERNAL` 참조로 등록하며 원본을 이동하지 않는다.
- 일반 Markdown, AGENTS.md, Requirements, Architecture, Implementation Plan, Decision/Note를 선택하여 Workspace 상대경로에 생성할 수 있다. 기존 파일은 덮어쓰지 않는다. `AGENTS.md`는 사용자가 해당 문서 종류를 명시해야 생성한다.
- Source 위치/root/사용 유형을 기록한다. 파일을 다시 등록하면 바뀐 내용은 새 Source ID/hash로 관리하고 이전 입력의 hash를 바꾸지 않는다.

### Artifact / Publish / Workflow 재사용

- Artifact에 `WORKSPACE`, `SHARED`, `EXTERNAL` 위치 유형과 root·상대경로를 추가했다. 이전 Artifact의 위치는 `LEGACY`로 해석한다.
- 새 실행 결과는 연결 Workspace의 `outputs/<run-id>/<output-path>`에 저장한다. Run별 출력 분리를 유지하여 기존 파일 덮어쓰기와 병렬 Task 충돌을 피한다.
- Workspace/외부의 기존 결과 파일도 이동 없이 Artifact로 등록할 수 있다. 기존 Artifact의 `run_id NOT NULL` 계약을 유지하기 위해 수동 등록은 Runtime Thread/Turn이 없는 `reference` 이력으로 기록하며 AI Retry는 제공하지 않는다.
- 사용자가 Category/Global Publish를 요청한 경우에만 검증된 bytes를 `data/shared/category/<category-id>/<artifact-id>/` 또는 `data/shared/global/<artifact-id>/`에 복사한다. Artifact ID·hash·생산자·lineage는 유지하고 Workspace 원본은 보존한다.
- Publish 완료 후 해당 새 실행의 임시 후보 파일을 삭제한다. 기존 Data 파일, 사용자 Workspace 원본, 입력 snapshot, 다른 결과 파일은 삭제하지 않는다. 기존 Publication을 시작 시 자동 복사하지 않는다.
- Shared 결과를 다른 Work에서 명시적으로 선택할 수 있으며 기존 범위 검증·Output Contract·Task handoff·Retry/Branch·Git clone/worktree 기능을 재사용한다.

### 최소 UI 변경

- Work Header에 실제 Workspace를 표시하고 폴더 열기/Workspace 변경을 추가했다. 내부 저장 경로는 고급 정보에 표시한다.
- Work 생성에 새 Workspace/기존 폴더 연결, 기본 위치·폴더 이름·생성 위치, macOS 폴더 선택을 연결했다.
- 기존 Work 화면에 Workspace 파일 선택, 새 Markdown, 외부 파일, 기존 Shared 선택 버튼과 자료 추가 dialog를 추가했다. Task 화면에서도 새 Markdown을 만들 수 있다.
- 자료의 Workspace/Shared/External 출처와 상대경로를 표시한다. Dashboard 및 기존 Workflow/Run 화면 구조는 유지했다.

## DB / Migration

새 revision: [0004_workspace_storage.py](../app/migrations/versions/0004_workspace_storage.py)

| 대상 | 추가 내용 |
| --- | --- |
| Work | `storage_layout`(기존 row 기본값 `LEGACY`), `workspace_path`, Workspace 연결 중복 방지 index |
| Source | `location_type`, `location_root`, `usage_type` |
| Artifact | `location_type`, `location_root`, `origin_path`, `staging_path` |
| Run / Workflow | 테이블 재구성 없이 기존 manifest/snapshot에 실행 저장 위치를 기록 |

`0001`–`0003` revision은 변경하지 않았다. `0004`는 열과 index를 추가하며 기존 Work/Source/Artifact row의 ID·경로·hash를 새 값으로 자동 변환하지 않는다. 기존 테이블 삭제·파일 이동·파일 삭제 작업이 없다.

현재 운영 DB는 읽기 전용으로 확인했으며 기존 revision은 `0003`이다. 운영 DB에 이번 migration을 직접 적용하거나 실제 서버를 기동하지 않았다. 다음 정상 기동에서는 기존 백업 절차를 거쳐 schema만 `0004`로 확장한다. 기존 Work의 외부 Workspace 전환은 별도 사용자 명령이다.

핵심 구현: [storage.py](../app/storage.py), [storage_api.py](../app/storage_api.py), [workspace.py](../app/workspace.py), [artifact_service.py](../app/artifact_service.py), [storage.js](../app/static/storage.js). [architecture.md](architecture.md)와 [phase2-requirements.md](phase2-requirements.md)에 우선 기준과 현재 경로 구조를 반영했다.

## 최소 검증 결과

대표 API End-to-End 흐름 **1개 통과**. 독립 임시 DB·폴더와 FakeGateway를 사용했다.

```bash
.venv/bin/python -m unittest discover -s tests -p test_workspace_storage.py -v
```

확인한 흐름:

1. `0003` DB의 기존 Work/Source/Artifact를 보존하며 `0004` 적용.
2. 외부 Workspace 생성 및 기존 폴더 비침투 연결.
3. Workspace Markdown 생성·기존 파일 덮어쓰기 거절·외부 파일 참조.
4. Phase 1 단일 실행에서 입력 snapshot 제공 및 Workspace Artifact 저장.
5. Global Publish와 Shared 복사, 원본 보존, 해당 임시 후보 삭제.
6. 다른 Work에서 Shared Artifact 선택 → 2단계 Workflow → 결과 handoff.
7. 기존 Work의 명시적 연결 변경 뒤 원래 Source/Artifact 조회와 파일 bytes 보존.
8. Finder 열기 명령의 대상 경로 확인(프로세스 실행은 mock), 상대경로 탈출 거절.

Fake Turn은 총 3개(단일 실행 1개 + Workflow Task 2개)이며 **실제 Codex 호출은 0회**다. 전체 기존 테스트와 브라우저 smoke는 반복 실행하지 않았다. JavaScript 구문과 Python 구문, UI element 참조도 확인했다. 이전 Phase 1·2 회귀 fixture는 기존 저장 방식의 Work를 직접 구성하도록 조정하여 legacy 회귀와 새 저장소 흐름을 구분했다.

## 남은 문제 / 제한

- 실제 Finder/폴더 선택 dialog의 데스크톱 동작, 실제 Codex 및 새 위치에서의 Git Sandbox는 이번 최소 검증 범위에 포함하지 않았다. 실제 Runtime 성공까지 검증한 것으로 해석하면 안 된다.
- Runtime 입력 snapshot과 아직 Publish하지 않은 후보는 시스템 임시 경로에 남는다. OS가 임시 파일을 제거하면 해당 snapshot을 사용하는 Retry/복구가 실패할 수 있다. 사용자 파일을 보존하는 범위에서 자동 보존 기간·정리 정책은 추가하지 않았다.
- 파일 작업과 DB commit은 하나의 transaction이 아니다. 문서/Workspace 생성 또는 Publish 중 프로세스가 종료되면 DB에 연결되지 않은 파일이 남을 수 있다. 기존 파일을 자동 삭제하는 복구 정책은 추가하지 않았다.
- 기존 Work/Data/Publication을 새 구조로 일괄 정리하는 기능은 추가하지 않았다. 기존 저장 경로는 호환 대상으로 유지하며 사용자가 Work별 연결을 명시적으로 변경할 수 있다.
