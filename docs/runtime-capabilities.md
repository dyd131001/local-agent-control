# Runtime Capabilities

> 검증일: 2026-09-28, Asia/Seoul. macOS 로컬 환경에서 실제 SDK/App Server를 실행한 결과다.
> Phase 1 기능 구현 완료를 의미하지 않는다. 아래에서 실측, 인터페이스 확인, 미검증을 구분한다.

## 1. 결론

**공식 `openai-codex` Python SDK → 로컬 Codex App Server를 기본 Runtime으로 채택한다.** 기존 ChatGPT 인증 재사용, 초기화, Model/Reasoning 조회, Thread 생성, Turn 실행, Streaming, Steer, Interrupt, 프로세스 재생성 후 Resume가 실측으로 성공했다. `codex exec`는 사용하지 않았고 fallback 필요성도 발견하지 못했다.

설계에 직접 영향을 주는 결과:

- 서로 다른 Thread의 Turn 2개는 같은 App Server에서 동시에 실행됐다.
- 같은 Thread의 두 번째 `turn/start`는 새 Turn을 만들지 않고 **기존 Turn ID를 반환하여 추가 입력을 합쳤다**. 애플리케이션에서 Thread별 잠금이 필요하다.
- apply_patch는 `fileChange` item을 생성했지만, Shell redirect로 만든 파일에는 해당 item이 없었다. 파일 시스템 검사가 필수다.
- Interrupt ACK는 `{}`이고, 이후 `turn/completed.status=interrupted`가 도착했다. ACK와 취소 확정을 분리해야 한다.
- 실행 중 SDK/App Server를 닫으면 reader가 `TransportClosedError`를 받았다. 새 인스턴스에서 이전 Turn의 `interrupted` 기록과 Thread를 복구할 수 있었다. 전체 Backend crash 복구를 검증한 것은 아니다.
- 모델이 `DONE`이라고 답했지만 요청한 명령/파일 생성이 전혀 없었던 테스트도 있었다. 모델의 완료 문구를 실행·Artifact 증거로 사용하면 안 된다.

확정 설계는 [architecture.md](architecture.md)에 기록했다.

## 2. 입력 문서와 공식 조사

요청된 `docs/phase1-requirements-v2.md`는 저장소에 없었다. SDK/App Server 중심 요구사항이 들어 있는 [phase1-requirements.md](phase1-requirements.md)를 읽고 기준으로 사용했다. 기존 architecture와 runtime-capabilities는 대부분 TBD 템플릿이었다.

공식 문서에서 Python SDK가 로컬 App Server JSON-RPC를 제어하고 Python 3.10 이상과 고정된 Runtime dependency를 사용함을 확인했다. App Server 문서의 인증, Thread/Turn, Steer/Interrupt, notification 인터페이스를 설치된 SDK와 대조했다.

- [공식 Codex SDK 문서](https://learn.chatgpt.com/docs/codex-sdk)
- [공식 Codex App Server 문서](https://learn.chatgpt.com/docs/app-server)

문서만으로 지원 판정을 내리지 않았다. 설치된 `openai_codex`의 `api.py`, `async_client.py`, `client.py`, `_sandbox.py`, `_approval_mode.py`, generated types를 읽었고, 설치된 CLI로 JSON Schema도 생성했다. CLI help는 App Server 명령을 experimental로 표시했다. 따라서 현재 버전에서 검증된 로컬 통합으로 채택하며 버전 간 호환성을 무조건 보장하지 않는다.

## 3. 환경과 초기 제약

| 항목 | 확인 결과 |
| --- | --- |
| OS / CPU | macOS 14.7.8 (23H730), x86_64 |
| 기본 `python3` | 3.9.12 — SDK 최소 요구 버전 미달 |
| 사용 가능한 추가 Python | `/usr/local/bin/python3.10`, 3.10.2 |
| 검증 가상환경 | `/private/tmp/ai-control-runtime-venv` |
| 기존 CLI | `/Users/bagjeong-yong/.local/bin/codex`, `codex-cli 0.158.0` |
| 설치 SDK | `openai-codex==0.158.0` |
| SDK 동봉 Runtime | `openai-codex-cli-bin==0.158.0` |
| SDK 의존성 | pydantic 2.13.5, pydantic-core 2.46.5, packaging 26.3 등; 임시 venv에만 설치 |
| 인증 | `account.type=chatgpt`, 기존 로그인 재사용 |
| API Key | 테스트 프로세스에 `OPENAI_API_KEY`, `CODEX_API_KEY` 없음; 입력하지 않음 |
| CODEX_HOME | 환경변수 override 없음. 기존 사용자 Codex 저장소 사용 |
| 실제 모델 호출 | 조회 목록의 기본 모델 `gpt-6-astra`, effort `low` |
| 실행 파일/자료 | 새 임시 디렉터리의 synthetic 파일만 사용 |

처음 제한된 에이전트 샌드박스에서 PyPI 접근은 DNS/network 오류로 실패했다. 허용된 외부 실행에서 임시 venv 설치는 성공했다. 이를 패키지가 존재하지 않는다는 근거로 해석하지 않았다.

SDK 초기화도 처음에는 다음 오류로 실패했다.

```text
TransportClosedError: Codex process closed stdout
failed to initialize sqlite state runtime under /Users/bagjeong-yong/.codex
```

`~/.codex` 쓰기가 외부 샌드박스에서 차단된 것이 원인이었다. 권한을 허용한 실행에서는 동일한 기존 로그인으로 초기화·조회·Turn이 성공했다. App Server 프로세스의 상태 저장 권한과 모델 도구의 내부 Sandbox를 구분해야 한다. 사용자 인증 파일을 열어 토큰을 출력하거나 복사하지 않았다.

## 4. 기능별 실측 결과

| 확인 항목 | 판정 | 실제 증거 / 범위 |
| --- | --- | --- |
| 기존 로그인 재사용 | 성공 | `account()` → ChatGPT account, 이후 실제 모델 응답 성공; 새 로그인/API Key 없음 |
| Python SDK 초기화 | 성공, 실행 권한 조건 있음 | `async with AsyncCodex(...)`; metadata Runtime 0.158.0/macOS |
| Model / Reasoning 조회 | 성공 | `models()` → 7개 모델, supported/default effort; nextCursor=null |
| Thread 생성 | 성공 | `thread_start`, persisted Thread ID 반환 |
| Turn 실행 | 성공 | `thread.turn(..., effort="low")`, handle ID와 completed terminal |
| Streaming | 성공 | item/agentMessage delta, command events, diff, terminal 등 수신 |
| 실행 중 Steer | 성공 | sleep 명령 중 `handle.steer`; 동일 Turn에서 최종 답이 변경됨 |
| 종료 후 Steer | 정상 거절 | `InvalidRequestError`, JSON-RPC -32600, `no active turn to steer` |
| Interrupt / Cancel | 성공 | ACK 후 interrupted terminal, 지연 생성 예정 파일 미생성 |
| Thread Resume | 성공 | SDK/App Server 종료 후 새 인스턴스, 동일 Thread ID/기존 대화 token 복원, 새 Turn ID |
| 파일 변경 이벤트 | 부분 범위 확인 | apply_patch의 completed fileChange + 실제 hash 확인; Shell 쓰기는 fileChange 없음 |
| Working Directory | 성공 | 지정 cwd와 명령의 pwd/commandExecution.cwd 일치 |
| read-only Sandbox | 성공 | command/exec에서 cwd/외부/추가 root 후보 모두 쓰기 PermissionError |
| workspace-write Sandbox | 성공 | cwd 내부 쓰기 성공, 외부 쓰기 차단; 실제 모델 Turn에서도 dummy DB 보호 확인 |
| 추가 writableRoots | 성공, command/exec 범위 | 지정 추가 root만 쓰기 허용, 그 밖의 형제 경로는 차단 |
| 다른 Thread 동시 Turn | 성공 | 같은 App Server에서 A 실행 중 B 시작, B가 A보다 먼저 완료 |
| 같은 Thread 동시 Turn | 독립 실행 아님 | 두 번째 start가 첫 Turn ID 반환; 입력 병합 |
| 실행 중 App Server 종료 후 기록 | 성공, SDK close 범위 | stream 손실 후 새 인스턴스에서 interrupted history 조회/후속 실행 |
| 새 OAuth 로그인 | 미실행 | SDK login API 존재 확인만 함. 현재 세션을 logout하지 않음 |
| 실제 Backend 재시작/DB/SSE 복구 | 미검증 | Backend 자체를 구현하지 않았음 |

### 로그인 상태 해석

`account`가 존재하고 type이 chatgpt인 동시에 `requiresOpenaiAuth=true`였다. 이 boolean만으로 Disconnected를 판정하면 잘못된 UI가 된다. 계정 존재, Runtime 연결 상태, 실제 인증 오류를 함께 다뤄야 한다. 브라우저의 ChatGPT cookie를 추출하거나 임의 세션을 가져오는 테스트가 아니라 **이미 로그인된 Codex 인증 저장소의 재사용**이다.

### SDK 호출 형태

이번 테스트에서 실제 사용한 최소 형태:

```python
from openai_codex import AsyncCodex, ApprovalMode, Sandbox

async with AsyncCodex() as codex:
    account = await codex.account()
    models = await codex.models()
    thread = await codex.thread_start(
        cwd="/absolute/path/to/probe/work",
        model="gpt-6-astra",  # 테스트에서는 models()의 default를 선택
        sandbox=Sandbox.workspace_write,
        approval_mode=ApprovalMode.deny_all,
        ephemeral=False,
    )
    turn = await thread.turn("Reply OK only.", effort="low")
    async for event in turn.stream():
        # 실제 probe는 허용한 item만 기록하고 reasoning 본문은 제외한다.
        pass
```

`AsyncCodex` 초기화는 context 진입/첫 awaited 호출에 이루어진다. 설치 소스에서 SDK가 `app-server --listen stdio://`를 실행함을 확인했다. `codex exec` 호출이 아니다. SDK의 기본 approval mode는 `auto_review`라서 모든 테스트는 `deny_all`을 명시했다. 이 모드는 내부 Sandbox를 제거하지 않는다.

### Model / Reasoning 목록

아래는 **조회 결과**이며 전 모델을 실제 호출한 결과가 아니다.

| Model ID | 기본 effort | 광고된 지원 effort |
| --- | --- | --- |
| gpt-6-astra | low | low, medium, high, xhigh, max, ultra |
| gpt-6-sol | low | low, medium, high, xhigh, max, ultra |
| gpt-6-luna | medium | low, medium, high, xhigh, max |
| gpt-5.6-sol | low | low, medium, high, xhigh, max, ultra |
| gpt-5.6-terra | medium | low, medium, high, xhigh, max, ultra |
| gpt-5.6-luna | medium | low, medium, high, xhigh, max |
| gpt-5.5 | medium | low, medium, high, xhigh |

`gpt-6-astra`가 `isDefault=true`였다. 실제 호출은 이 모델의 low만 검증했다. SDK generated effort enum의 전체 값이 모델별 지원 목록을 대체하지 않는다. UI는 Runtime 조회값을 사용하고 이 표를 하드코딩하지 않는다.

### Thread / Turn / Steer / Interrupt

대표 Thread는 `01a0e86d-e0ae-7762-881d-38afd6a56337`이다. 첫 Turn에서 `ORCHID_728`을 기억하도록 하고 파일을 생성했다. SDK context 종료 후 새 context에서 같은 Thread를 Resume하여 파일을 읽지 않고 `ORCHID_728`을 응답받았다. Resume 후 Turn ID는 새 값이었다. 이전 completed/interrupted Turn도 history에 남았다.

Steer는 commandExecution started를 받은 뒤 보냈다. ACK의 Turn ID가 현재 handle ID와 같았고, 최종 답이 `ORIGINAL_MARKER`에서 `STEER_ACCEPTED_728`로 바뀌었다. 새 `turn/started`가 추가되지 않았다. Steer는 이미 실행된 명령의 rollback 기능이 아니다.

Interrupt는 `sleep 20` 시작 이벤트 후 요청했다. ACK는 빈 객체였고 terminal은 interrupted였다. 이후 다른 테스트가 충분히 진행된 뒤에도 `must-not-exist.txt`가 없었다. 이 결과는 테스트 명령 흐름의 중단 증거이며 임의 detached child process까지 모두 종료된다는 보장은 아니다. 중단 Turn에서는 command completed 이벤트가 생략됐다.

### 관측된 Streaming 형식

SDK Notification은 `method`와 typed `payload`를 갖는다. 다음 method를 실제 수신했다.

```text
turn/started
item/started
item/completed
item/agentMessage/delta
item/commandExecution/outputDelta
turn/diff/updated
thread/tokenUsage/updated
turn/completed
```

관측 item type은 userMessage, agentMessage, commandExecution, fileChange다. 테스트 evidence는 method 횟수와 허용한 item만 기록했다. 숨겨진 reasoning 본문이나 인증 전체 payload를 저장하지 않았다. evidence는 Raw protocol의 완전한 packet capture가 아니다.

첫 파일 Turn에서 agentMessage delta 16개, diff update 3개와 completed fileChange를 받았다. `probe.txt`의 실제 내용은 `RUNTIME_PROBE_OK\n`, SHA-256은 `948746e7bdabdcd8366fe3c95b301a23e7934c12efb838aed0e18143160a0a52`였다.

별도 Shell 쓰기 Turn은 `shell.txt`에 `SHELL_WRITE_OK\n`을 실제 생성했지만 fileChange와 diff update가 없었다. 따라서 fileChange는 완전한 파일 감시 서비스가 아니다.

### Sandbox와 cwd

공개 low-level `AsyncCodexClient.request("command/exec", ...)`로 App Server Sandbox를 직접 검사했다. 이것도 `codex exec` subprocess fallback이 아니다. 모델의 자연어 수행 여부와 별개로 쓰기 경계를 확인하기 위한 테스트다.

| 정책 | cwd 내부 | 형제 경로 | 지정 추가 root |
| --- | --- | --- | --- |
| readOnly | 차단 | 차단 | 차단 |
| workspaceWrite, 추가 root 없음 | 성공 | 차단 | 차단 |
| workspaceWrite, 추가 root 지정 | 성공 | 차단 | 성공 |

workspaceWrite 테스트는 `excludeSlashTmp=true`, `excludeTmpdirEnvVar=true`, `networkAccess=false`를 명시했다. networkAccess 설정값은 확인했지만 실제 외부 네트워크 차단 실험은 하지 않았다. full-access는 schema/SDK에 존재하지만 실행하지 않았다.

실제 모델 Turn에서도 thread_start의 다음 config와 `Sandbox.workspace_write`, `ApprovalMode.deny_all`을 사용했다. Turn에는 sandbox preset을 다시 덮어쓰지 않았다.

```json
{
  "sandbox_workspace_write": {
    "writable_roots": [],
    "network_access": false,
    "exclude_tmpdir_env_var": true,
    "exclude_slash_tmp": true
  }
}
```

첫 시도와 재실행의 첫 Turn에서는 모델이 DONE만 응답하고 명령을 실행하지 않았다. `inside.txt`가 없으므로 Sandbox 통과로 판정하지 않았다. 정확한 명령을 지정한 후속 Turn에서 내부 `inside.txt` 쓰기는 성공했고 cwd 밖의 **테스트용 dummy `control.db`** 쓰기는 PermissionError로 실패했다. 기존 dummy 내용은 `DUMMY_CONTROL_UNCHANGED`로 보존됐다. 실제 애플리케이션 DB나 사용자 파일을 수정한 테스트가 아니다.

이 후속 Turn은 command exitCode=1/failed지만 Turn 자체는 completed였다. 작업 성공 판정에는 Runtime terminal뿐 아니라 요구된 결과의 존재·내용 검사가 필요하다. workspace-write는 쓰기 경계이며 로컬 전체 파일의 읽기 기밀성 격리를 검증한 것은 아니다.

### 동시 실행과 복구 경계

서로 다른 Thread에서 A의 sleep 명령 중 B를 시작했다. B 시작 시 A reader는 종료되지 않았고 B와 A가 각각 고유 Turn ID로 완료됐다. 최대 처리량, 장기 부하, rate limit, 동시 쓰기 안전성은 측정하지 않았다.

같은 Thread에 두 번째 start를 보내면 두 handle ID가 `01a0e86e-aa6c-7970-81de-130e4d457de2`로 같았다. 최종 답은 두 번째 입력의 `SAME_THREAD_SECOND`였다. 따라서 제품의 새 Run 실행과 Steer를 구분하려면 Runtime 호출 전에 잠금이 필요하다.

별도 Thread에서 sleep 도중 `codex.close()`를 호출했다. reader는 TransportClosedError를 받았고 terminal notification을 수신하지 못했다. 새 SDK에서 Resume 전 read는 thread status `notLoaded`, 해당 Turn `interrupted`를 반환했다. Resume 뒤 thread는 `idle`; 새 Turn은 `RECOVERY_NEW_TURN`으로 완료됐다.

설치 SDK의 close는 App Server stdin을 닫고 process terminate를 호출한다. 이 실험을 SIGKILL/Backend 비정상 종료/OS 재부팅/daemon 재연결의 보장으로 확대하지 않는다. Runtime history에서 최종 상태를 복구할 수 있다는 근거로만 사용한다. 누락된 delta 전체가 재생되는지도 검증하지 않았다.

## 5. 재현 방법과 증거

스크립트: [scripts/probe_codex_runtime.py](../scripts/probe_codex_runtime.py). Phase 1 애플리케이션 코드가 아닌 수동 integration probe다. 기존 로그인으로 실제 모델 사용량이 발생하며 테스트 Thread와 임시 파일을 만든다. 모든 mode는 새 임시 cwd를 생성한다. `sandbox` mode는 모델을 호출하지 않는다. 재실행은 새 output 이름을 사용하여 기존 증거를 덮어쓰지 않는다.

```sh
python3.10 -m venv /private/tmp/ai-control-runtime-venv
/private/tmp/ai-control-runtime-venv/bin/python -m pip install --no-cache-dir openai-codex==0.158.0
/private/tmp/ai-control-runtime-venv/bin/python -u scripts/probe_codex_runtime.py --output /private/tmp/sdk-suite-new.json
/private/tmp/ai-control-runtime-venv/bin/python -u scripts/probe_codex_runtime.py --mode sandbox --output /private/tmp/sandbox-new.json
/private/tmp/ai-control-runtime-venv/bin/python -u scripts/probe_codex_runtime.py --mode recovery --output /private/tmp/recovery-new.json
/private/tmp/ai-control-runtime-venv/bin/python -u scripts/probe_codex_runtime.py --mode hardened --output /private/tmp/hardened-new.json
```

현재 probe의 명령 테스트는 이 기기의 `/usr/local/bin/python3.10` 경로를 사용한다. 다른 환경에서는 해당 interpreter 경로를 조정해야 한다. SDK의 상태 DB 쓰기와 네트워크를 허용한 로컬 실행이 필요하다. 테스트용 파일/Thread는 재현·추적을 위해 남겼으며 사용자 세션을 logout하거나 기존 대화를 수정하지 않았다.

| 증거 파일 | 실행 범위 / 판독할 case |
| --- | --- |
| [sdk-suite.json](runtime-evidence/sdk-suite.json) | 23:31–23:33 KST. environment, account, models, file_turn, steer_turn, interrupt_turn, concurrent_*, same_thread_*, resume_* |
| [sandbox.json](runtime-evidence/sandbox.json) | readOnly/workspaceWrite/추가 root의 실제 명령 결과 및 파일 존재 |
| [recovery.json](runtime-evidence/recovery.json) | shell_write_turn, closed_stream, active_close_history_*, recovery_new_turn |
| [hardened.json](runtime-evidence/hardened.json) | 첫 불확정 시도: 명령 이벤트 없음, inside_exists=false. 성공 증거 아님 |
| [hardened-retry.json](runtime-evidence/hardened-retry.json) | 후속 명시적 명령의 PermissionError, inside_exists=true, dummy DB 보존 |

CLI schema 생성 명령도 실행했다.

```sh
codex app-server generate-json-schema --out /private/tmp/ai-control-runtime-schema
```

Thread/Turn ID와 synthetic 작업 출력은 evidence에 포함된다. credential/email은 제외했다. 초기 설치/샌드박스 초기화 실패는 세션 command 출력으로 확인했으며 별도 evidence JSON에는 포함되지 않는다.

## 6. 남은 검증과 Architecture 결정

- 기본 Gateway는 AsyncCodex. 모델/effort와 ID를 동적으로 조회·저장한다.
- Phase 1은 단일 활성 Run 정책을 둔다. Runtime 병렬 처리 가능 여부와 제품의 병렬 실행 정책을 구분한다.
- Run terminal은 ACK가 아닌 실제 terminal/history로 판정한다. command 실패가 Turn 실패와 같다고 가정하지 않는다.
- 이벤트는 Backend DB에 commit한 뒤 SSE로 전달한다. Runtime history는 DB Event Store의 대체물이 아니다.
- 파일 이벤트 + 최종 파일 scan/hash로 Artifact를 확정한다. AI 완료 문구만으로 등록하지 않는다.
- Control DB/확정 Artifact/Context snapshot은 Run cwd 쓰기 영역 밖에 두고 tmp 예외도 제한한다.
- Manifest는 전달한 Context snapshot/프롬프트/설정과 Resume/Steer 관계를 기록한다. 모델의 실제 내부 Context 전체를 증명하지 않는다.
- Backend 재시작은 ID/manifest/event/파일 상태를 보존하고 Runtime history와 reconcile한다. Start 수락과 DB commit 사이의 결과 불명 구간을 자동 재시도로 덮지 않는다.

새 OAuth, 인증 만료, 사용량 한도, 전 모델·effort, 장시간 스트림, symlink/대용량 Artifact 처리, 실제 DB crash consistency, SSE replay, SIGKILL/orphan process는 미검증이다. 이 항목들은 [Architecture의 구현 Gate](architecture.md#12-구현-순서와-검증-gate)에 남겼다. 이번 결과로 Phase 1 전체 완료를 주장하지 않는다.


## 7. Execution Settings 계약 확인 (2026-09-29)

이번 확인은 설치된 `openai-codex==0.158.0`의 공개 SDK와 생성된 Runtime schema를 읽고,
FakeGateway 흐름 및 SDK 인자 spy로 전달 계약만 확인했다. App Server / 모델을 호출하지 않았다.
아래 SDK 지원 표시는 실제 모델 실행 실측을 의미하지 않는다.

| 설정 | 계약 / 구현 | 이번 확인 범위 |
|---|---|---|
| Model / Reasoning | `model/list` 카탈로그의 model, supportedReasoningEfforts를 공통 Resolver에서 검증 | Fake 카탈로그 → Run → Gateway |
| Personality | `Model.supports_personality`는 always false; Thread/Turn personality 선택은 deprecated | 생성 schema / 공개 API 읽기. 선택 비활성화, non-null 거절 |
| Permission | 공개 `Sandbox.read_only`, `workspace_write`, `full_access` preset을 사용 | Thread start / resume / fork의 인자 spy. Workspace Write의 기존 Git writable roots 유지 |
| Speed / Fast | 모델의 `serviceTiers` / `defaultServiceTier`를 보존하고 반환된 tier ID만 선택 가능 | Fake priority tier resolve / snapshot 전달. 실 계정별 지원 여부 미실측 |
| Standard | `TurnStartParams.serviceTierForTurn`은 `"default"`를 표준 속도 reset으로 문서화 | `AsyncThread.turn(turn_service_tier="default")` 인자 spy |
| Approval | 모든 Permission에서 `ApprovalMode.deny_all` 유지 | 공개 SDK 매핑 읽기 / 인자 전달 |

근거: 설치 SDK `generated/v2_all.py`의 `Model`, `ModelServiceTier`, `TurnStartParams`,
`api.py`의 AsyncCodex thread lifecycle 및 AsyncThread.turn,
`_sandbox.py` / `_approval_mode.py`의 공개 enum 및 wire 매핑.
실 카탈로그가 Fast 등급을 반환하지 않으면 해당 모델의 추가 Fast 선택지를 만들지 않는다.
Read Only는 모델 도구의 파일 쓰기를 허용하지 않으므로 파일 필수 산출물 계약과 조합하면 Task가 실패할 수 있다.
Full Access는 Runtime의 파일 쓰기 격리를 해제한다. 기존 Workspace Write dummy DB 차단 실측 결과를 Full Access에 적용하지 않는다.


## 8. Phase 3 앱 상태 전이 확인 (2026-09-29)

Approval Gate, Revision, 예약 / 반복 / misfire, Pause / Resume, Checkpoint, Delayed Resume와
재시작 복구는 애플리케이션 DB / Scheduler 기능이다. 새 Runtime capability나 별도 Codex 호출 경로를 만들지 않았다.
대표 확인은 `tests/test_phase3.py`의 임시 DB / FakeGateway로 수행했다.
성공 흐름에서 Fake Turn 7회(단일 실행, 원본 A, 수정 A, B/C/D, 지연 이어하기)와 Backend 재시작 2회를 사용했다.
예약 트리거는 새 WorkflowRun 생성까지만 확인하고 예약 테스트 중 enqueue를 차단했다.
실 Runtime / 실제 모델 호출은 0회이며 기존 capability 실측을 반복하지 않았다.

Full Access는 SDK preset으로 존재하지만 Phase 3의 제어 상태 보호 원칙 때문에 앱의 신규 실행과
queued Run dispatch에서 허용하지 않는다. READ ONLY / WORKSPACE WRITE와 deny_all을 사용한다.
이 제한은 과거 Run snapshot이나 저장 파일을 변환하지 않는다.
Personality 미지원과 실제 계정별 Fast 가용성 미실측은 기존 제한으로 남는다.

## 9. Phase 4 Gateway 계약 (2026-09-29)

실제 Codex / App Server 호출 없이 설치된 공개 SDK `0.158.0`과 generated schema를 읽고,
FakeGateway 대표 Conversation 흐름과 SDK 인자 spy로 앱 계약을 확인했다.
기존 VERIFIED Runtime 항목을 반복 실측하지 않았다. 아래 구현 표시는 새 기능의 실 Runtime VERIFIED 표시가 아니다.

| 기능 | 공개 SDK / 앱 계약 | 이번 확인 |
|---|---|---|
| Continue / Resume | 기존 `AsyncCodex.thread_resume` + `AsyncThread.turn` | 같은 Fake Thread와 새 Run 유지 |
| Fresh / Ephemeral | `thread_start(ephemeral=True)`; Query 기본 `Sandbox.read_only` | 공개 SDK 인자 spy, 독립 Fake Thread |
| Exact Fork | 기존 `thread_fork` 재사용 | Fake History 분기, 최신 terminal Turn guard. 임의 과거 Turn cutoff 미노출 |
| Compact | `AsyncThread.compact()` + 동일 App Server의 공개 Thread read | ACK 이후 새 contextCompaction / terminal 확인 계약을 spy로 확인 |
| Usage | `thread/tokenUsage/updated`의 last / total / modelContextWindow 정규화 | Fake Usage → ThreadRecord. 실제 Usage 이벤트는 이전 실측에서 관측됨 |
| Context Pack / Promotion / Handoff | Backend DB / 입력 스냅샷 / 기존 Artifact & Publish | Version, Scope, Dedup, Freshness, 예산, 짧은 결론 전달 |

Compact는 프롬프트 요약이나 새 Thread로 대체하지 않는다. completion이 공개 History에 나타나지 않거나
180초 안에 확인되지 않으면 UNKNOWN으로 차단하며 자동 반복 호출하지 않는다. Runtime이 contextCompaction
항목을 History에 어떻게 보존하는지와 실제 fork / ephemeral의 계정별 동작은 이번 작업에서 실측하지 않았다.
기존 resume / sandbox 실측 근거를 새로운 fork / ephemeral / manual compact의 성공 증거로 확대하지 않는다.

## 10. Phase 5 Status / Work Tools 계약 확인 (2026-09-29)

실제 Codex / App Server를 실행하지 않았다. 설치 SDK `0.158.0`의
`GetAccountRateLimitsResponse`, `RateLimitSnapshot`, `RateLimitWindow`와 공개 typed RPC를 읽고
metadata client spy로 전달 / 캐시 / 실패 상태를 확인했다.

- `account/rateLimits/read`: 공개 `AsyncCodexClient.request(..., response_model=GetAccountRateLimitsResponse)`.
  실제 RPC가 반환한 window / bucket / credits / ordinaryUsageAllowed만 정규화한다.
  unknown은 null, 이전 관측은 실패 시 STALE이며 관측 시각을 갱신하지 않는다.
- accountId, 업셀 배너, credential과 원시 protocol은 Dashboard 계약에 전달하지 않는다.
- 기존 `thread/tokenUsage/updated` → `CONTEXT_USAGE` Event / Thread 연결을 사용해 Run별 Usage를 반환한다.
  누적 Thread total을 계정 전체 비용으로 합산하지 않는다.
- Model / Reasoning / Permission은 기존 Run의 설정 snapshot을 표시한다. Runtime의 현재 내부 설정을
  새로 실측한 것으로 취급하지 않는다. terminal 미관측 상태는 null이다.
- Diff는 임시 Git 저장소에서 실제 Git 명령으로 확인했으며 모델 실행이 없다.
  AI Review는 기존 Run 실행기로 이어지는 FakeGateway 1회 흐름만 확인했다.
- Goal은 이번 단계에서 연결하지 않았다. 미지원 값을 Work 설명이나 목표 텍스트로 추정하지 않는다.

새 metadata RPC의 실제 계정별 제공 여부와 quota 갱신 / 인증 만료 동작은 미실측이다.
SDK schema / spy 지원을 새 Runtime VERIFIED 표시로 사용하지 않는다.
