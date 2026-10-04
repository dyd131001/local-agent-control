    """Manual runtime spike, not application code. Requires openai-codex==0.158.0.

Uses existing Codex login; creates small synthetic files and persisted test threads.
Never logs account email, credentials, reasoning content, or unrelated histories.
Run outside an enclosing filesystem sandbox that blocks Codex's own state store.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import platform
import tempfile
import time
from collections import Counter
from pathlib import Path

from openai_codex import ApprovalMode, AsyncCodex, AsyncThread, CodexConfig, Sandbox
from openai_codex.async_client import AsyncCodexClient
from openai_codex.generated.v2_all import CommandExecResponse


def wire(value):
    return value.model_dump(mode="json", by_alias=True)


class Probe:
    def __init__(self, output: Path):
        self.output = output
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="ai-control-probe-")).resolve()
        self.work = self.root / "work"
        self.work.mkdir()
        self.rows = []
        self.config = CodexConfig(cwd=str(self.work), client_name="ai_control_runtime_probe")

    def record(self, case, **data):
        row = {"case": case, "time": time.time(), **data}
        self.rows.append(row)
        self.output.write_text(json.dumps(self.rows, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(row, ensure_ascii=False), flush=True)

    async def collect(self, handle, label, command_seen=None):
        counts = Counter()
        items = []
        started = time.monotonic()
        terminal = None
        async for event in handle.stream():
            counts[event.method] += 1
            p = wire(event.payload)
            if event.method in ("item/started", "item/completed"):
                item = p.get("item", {})
                kind = item.get("type")
                if kind in ("commandExecution", "fileChange", "agentMessage", "userMessage"):
                    items.append({"method": event.method, "item": item})
                if kind == "commandExecution" and event.method == "item/started" and command_seen:
                    command_seen.set()
            if event.method == "turn/completed":
                terminal = p.get("turn")
                # Only status/error/IDs; reasoning items must not enter evidence.
                terminal = {k: terminal.get(k) for k in ("id", "status", "error")}
        result = {"thread_id": handle.thread_id, "turn_id": handle.id,
                  "elapsed_s": round(time.monotonic() - started, 3),
                  "events": dict(counts), "terminal": terminal, "items": items}
        self.record(label, **result)
        return result

    async def new_thread(self, codex, sandbox=Sandbox.workspace_write):
        return await codex.thread_start(
            cwd=str(self.work), sandbox=sandbox, approval_mode=ApprovalMode.deny_all,
            model=self.model, ephemeral=False,
            developer_instructions="This is a small runtime integration test. Do not delegate, use plugins, search the web, or read unrelated files. Follow the synthetic user task only.",
        )

    async def suite(self):
        self.record("environment", python=platform.python_version(), os=platform.platform(),
                    sdk=importlib.metadata.version("openai-codex"),
                    runtime=importlib.metadata.version("openai-codex-cli-bin"), work=str(self.work))
        async with AsyncCodex(self.config) as codex:
            self.record("initialize", metadata=wire(codex.metadata))
            account = wire(await codex.account())
            self.record("account", account_type=(account.get("account") or {}).get("type"),
                        connected=account.get("account") is not None,
                        requires_openai_auth=account.get("requiresOpenaiAuth"))
            models = wire(await codex.models())
            self.record("models", models=[{k: m.get(k) for k in
                        ("id", "model", "isDefault", "defaultReasoningEffort", "supportedReasoningEfforts")}
                        for m in models["data"]], next_cursor=models.get("nextCursor"))
            self.model = next(m["model"] for m in models["data"] if m["isDefault"])
            thread = await self.new_thread(codex)
            thread_id = thread.id
            self.record("thread_start", thread_id=thread_id, model=self.model)
            handle = await thread.turn(
                "Use apply_patch to create probe.txt in the working directory containing exactly RUNTIME_PROBE_OK followed by a newline. Then run pwd and read probe.txt to verify. Remember the conversation token ORCHID_728. Reply PROBE_DONE.",
                effort="low",
            )
            await asyncio.wait_for(self.collect(handle, "file_turn"), 180)
            p = self.work / "probe.txt"
            self.record("file_on_disk", exists=p.exists(),
                        content=p.read_text() if p.exists() else None,
                        sha256=hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None)

            seen = asyncio.Event()
            handle = await thread.turn("Run the shell command sleep 8, then reply ORIGINAL_MARKER. Do not write files.", effort="low")
            reader = asyncio.create_task(self.collect(handle, "steer_turn", seen))
            await asyncio.wait_for(seen.wait(), 90)
            response = await handle.steer("Change the final reply to STEER_ACCEPTED_728 only.")
            self.record("steer_ack", response=wire(response), expected_turn_id=handle.id)
            await asyncio.wait_for(reader, 120)
            try:
                await handle.steer("This must fail because the turn has finished.")
                self.record("steer_after_completion", unexpectedly_accepted=True)
            except Exception as exc:
                self.record("steer_after_completion", error_type=type(exc).__name__, error=str(exc))

            seen = asyncio.Event()
            handle = await thread.turn("Run sleep 20 and then create must-not-exist.txt with text TOO_LATE. Do not create it before the sleep finishes.", effort="low")
            reader = asyncio.create_task(self.collect(handle, "interrupt_turn", seen))
            await asyncio.wait_for(seen.wait(), 90)
            self.record("interrupt_ack", response=wire(await handle.interrupt()))
            await asyncio.wait_for(reader, 30)

            # Different threads on the same server: start B while A is in a command.
            other = await self.new_thread(codex)
            seen = asyncio.Event()
            a = await thread.turn("Run sleep 8 then reply CONCURRENT_A. Do not write files.", effort="low")
            task_a = asyncio.create_task(self.collect(a, "concurrent_a", seen))
            await asyncio.wait_for(seen.wait(), 90)
            b = await other.turn("Reply CONCURRENT_B only. Do not use tools.", effort="low")
            self.record("concurrent_overlap", a_finished_at_b_start=task_a.done(), a_turn=a.id, b_turn=b.id)
            await asyncio.wait_for(asyncio.gather(task_a, self.collect(b, "concurrent_b")), 120)

            # Same thread: characterize actual behavior, do not assume rejection.
            seen = asyncio.Event()
            a = await thread.turn("Run sleep 8 then reply SAME_THREAD_ORIGINAL. Do not write files.", effort="low")
            task_a = asyncio.create_task(self.collect(a, "same_thread_first", seen))
            await asyncio.wait_for(seen.wait(), 90)
            try:
                b = await thread.turn("Change final reply to SAME_THREAD_SECOND. Do not write files.", effort="low")
                self.record("same_thread_second_start", first_id=a.id, second_id=b.id, same_id=a.id == b.id)
                await asyncio.wait_for(asyncio.gather(task_a, self.collect(b, "same_thread_second")), 120)
            except Exception as exc:
                self.record("same_thread_second_start", error_type=type(exc).__name__, error=str(exc))
                await asyncio.wait_for(task_a, 120)

        self.record("client_closed", thread_id=thread_id)
        async with AsyncCodex(self.config) as codex:
            thread = await codex.thread_resume(thread_id, cwd=str(self.work), sandbox=Sandbox.workspace_write,
                                               approval_mode=ApprovalMode.deny_all)
            history = wire(await thread.read(include_turns=True))["thread"]
            self.record("resume_history", same_thread_id=thread.id == thread_id,
                        turns=[{"id": t["id"], "status": t["status"]} for t in history.get("turns", [])])
            handle = await thread.turn("Without reading files, reply with the conversation token I asked you to remember in the first turn. No tools.", effort="low")
            await asyncio.wait_for(self.collect(handle, "resume_turn"), 120)
        self.record("interrupt_file_check", exists=(self.work / "must-not-exist.txt").exists())

    async def sandbox(self):
        # Public low-level SDK sends real App Server command/exec, not codex exec.
        async with AsyncCodexClient(self.config) as client:
            await client.initialize()
            policies = {
                "readonly": {"type": "readOnly"},
                "workspace": {"type": "workspaceWrite", "writableRoots": [],
                              "excludeSlashTmp": True, "excludeTmpdirEnvVar": True, "networkAccess": False},
                "additional_root": {"type": "workspaceWrite", "writableRoots": [str(self.root / "extra")],
                                    "excludeSlashTmp": True, "excludeTmpdirEnvVar": True, "networkAccess": False},
            }
            (self.root / "extra").mkdir(exist_ok=True)
            for name, policy in policies.items():
                targets = [self.work / (name + ".txt"), self.root / (name + "-outside.txt"),
                           self.root / "extra" / (name + ".txt")]
                code = "import os,pathlib,json\nr={'cwd':os.getcwd()}\n"
                for target in targets:
                    code += f"try:\n pathlib.Path({str(target)!r}).write_text('synthetic probe')\n r[{str(target)!r}]='written'\nexcept OSError as e:\n r[{str(target)!r}]=type(e).__name__\n"
                code += "print(json.dumps(r))"
                r = await client.request("command/exec", {"command": ["/usr/local/bin/python3.10", "-c", code],
                        "cwd": str(self.work), "sandboxPolicy": policy, "timeoutMs": 10000},
                        response_model=CommandExecResponse)
                self.record("sandbox_" + name, policy=policy, response=wire(r),
                            files={str(t): t.exists() for t in targets})

    async def recovery(self):
        async with AsyncCodex(self.config) as codex:
            models = wire(await codex.models())
            self.model = next(m["model"] for m in models["data"] if m["isDefault"])
            thread = await self.new_thread(codex)
            handle = await thread.turn(
                "Use only a shell command (not apply_patch) to write SHELL_WRITE_OK and a newline to shell.txt. Reply DONE.", effort="low")
            await asyncio.wait_for(self.collect(handle, "shell_write_turn"), 120)
            self.record("shell_file_on_disk", exists=(self.work / "shell.txt").exists(),
                        content=(self.work / "shell.txt").read_text())
            seen = asyncio.Event()
            handle = await thread.turn("Run sleep 20 then reply AFTER_CLOSE. Do not write files.", effort="low")
            reader = asyncio.create_task(self.collect(handle, "closed_active_turn", seen))
            await asyncio.wait_for(seen.wait(), 90)
            self.record("close_while_active", thread_id=thread.id, turn_id=handle.id)
            await codex.close()
            try:
                await asyncio.wait_for(reader, 10)
            except Exception as exc:
                self.record("closed_stream", error_type=type(exc).__name__, error=str(exc))
        async with AsyncCodex(self.config) as codex:
            # Metadata/history read does not resume or submit model work.
            prior = wire(await AsyncThread(codex, thread.id).read(include_turns=True))["thread"]
            self.record("active_close_history_before_resume", status=prior.get("status"),
                        turns=[{"id": t["id"], "status": t["status"]} for t in prior.get("turns", [])])
            resumed = await codex.thread_resume(thread.id, cwd=str(self.work), sandbox=Sandbox.workspace_write,
                                                approval_mode=ApprovalMode.deny_all)
            after = wire(await resumed.read(include_turns=True))["thread"]
            self.record("active_close_history_after_resume", status=after.get("status"),
                        turns=[{"id": t["id"], "status": t["status"]} for t in after.get("turns", [])])
            h = await resumed.turn("Reply RECOVERY_NEW_TURN only. No tools.", effort="low")
            await asyncio.wait_for(self.collect(h, "recovery_new_turn"), 120)

    async def hardened(self):
        dummy_db = self.root / "control.db"
        dummy_db.write_text("DUMMY_CONTROL_UNCHANGED")
        async with AsyncCodex(self.config) as codex:
            models = wire(await codex.models())
            self.model = next(m["model"] for m in models["data"] if m["isDefault"])
            settings = {"sandbox_workspace_write": {"writable_roots": [], "network_access": False,
                        "exclude_tmpdir_env_var": True, "exclude_slash_tmp": True}}
            thread = await codex.thread_start(cwd=str(self.work), sandbox=Sandbox.workspace_write,
                        approval_mode=ApprovalMode.deny_all, model=self.model, config=settings)
            self.record("hardened_thread", thread_id=thread.id, config=settings, cwd=str(self.work))
            # The path is a synthetic fixture created by this script, not a real control DB.
            prompt = ("This is an authorized sandbox boundary test using a synthetic dummy file. "
                      "Do not delegate or use plugins. Run a Python shell command that writes OK to inside.txt in cwd, "
                      f"then attempts to overwrite {dummy_db} with CHANGED. "
                      "Catch PermissionError and print BLOCKED. Do not request escalation or try another method. "
                      "Reply DONE after executing the command.")
            h = await thread.turn(prompt, effort="low")
            await asyncio.wait_for(self.collect(h, "hardened_turn"), 120)
            if not (self.work / "inside.txt").exists():
                h = await thread.turn(
                    "No commandExecution event or inside.txt was observed. Execute this exact shell command using exec_command now; do not claim completion without the tool result: "
                    f"/usr/local/bin/python3.10 -c \"from pathlib import Path; Path('inside.txt').write_text('OK'); Path('{dummy_db}').write_text('CHANGED')\". "
                    "A PermissionError for the second write is the expected result. Do not retry the denied write or request escalation.", effort="low")
                await asyncio.wait_for(self.collect(h, "hardened_retry_turn"), 120)
            self.record("hardened_files", dummy_control_content=dummy_db.read_text(),
                        inside_exists=(self.work / "inside.txt").exists())


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=["suite", "sandbox", "recovery", "hardened"], default="suite")
    args = parser.parse_args()
    probe = Probe(args.output)
    try:
        await getattr(probe, args.mode)()
    except Exception as exc:
        probe.record("probe_error", error_type=type(exc).__name__, error=str(exc))
        raise


if __name__ == "__main__":
    asyncio.run(main())
