"""Bounded subprocess execution for the trusted Git executable."""

import asyncio
import os
import signal
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

_windows_process_group_flag = subprocess.__dict__.get("CREATE_NEW_PROCESS_GROUP", 0)
WINDOWS_PROCESS_GROUP_FLAG = (
    _windows_process_group_flag if isinstance(_windows_process_group_flag, int) else 0
)


class ProcessTimedOut(Exception):
    """Raised when a child process exceeds its deadline."""


class ProcessSizeLimitExceeded(Exception):
    """Raised when a child process grows its workspace beyond the limit."""


@dataclass(frozen=True, slots=True)
class ProcessRequest:
    """A shell-free process invocation with resource constraints."""

    arguments: tuple[str, ...]
    cwd: Path
    environment: dict[str, str]
    timeout_seconds: float
    size_limit_path: Path
    max_size_bytes: int


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """The non-sensitive result of a child process."""

    return_code: int


class ProcessRunner(Protocol):
    """Run one trusted executable without exposing output."""

    async def run(self, request: ProcessRequest) -> ProcessResult:
        """Execute the request or raise a bounded process failure."""
        ...


def directory_size(path: Path) -> int:
    """Measure regular files and links without following symbolic links."""
    if not path.exists():
        return 0

    total = 0
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        entry_stat = entry.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        continue
                    if stat.S_ISDIR(entry_stat.st_mode):
                        pending.append(Path(entry.path))
                    else:
                        total += entry_stat.st_size
        except FileNotFoundError:
            continue
    return total


class SubprocessRunner:
    """Run Git with no shell, no captured output, and bounded resources."""

    poll_interval_seconds = 0.1
    termination_grace_seconds = 1.0

    async def run(self, request: ProcessRequest) -> ProcessResult:
        """Execute a request while monitoring time and workspace growth."""
        process = await asyncio.create_subprocess_exec(
            *request.arguments,
            cwd=request.cwd,
            env=request.environment,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=os.name == "posix",
            creationflags=WINDOWS_PROCESS_GROUP_FLAG if os.name == "nt" else 0,
        )
        communication = asyncio.create_task(process.communicate())
        loop = asyncio.get_running_loop()
        deadline = loop.time() + request.timeout_seconds

        try:
            while not communication.done():
                if directory_size(request.size_limit_path) > request.max_size_bytes:
                    await self._terminate(process)
                    raise ProcessSizeLimitExceeded
                remaining = deadline - loop.time()
                if remaining <= 0:
                    await self._terminate(process)
                    raise ProcessTimedOut
                try:
                    await asyncio.wait_for(
                        asyncio.shield(communication),
                        timeout=min(self.poll_interval_seconds, remaining),
                    )
                except TimeoutError:
                    continue
            await communication
        except BaseException:
            await self._terminate(process)
            if not communication.done():
                await communication
            raise

        if directory_size(request.size_limit_path) > request.max_size_bytes:
            raise ProcessSizeLimitExceeded
        return ProcessResult(return_code=process.returncode or 0)

    async def _terminate(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            if os.name == "posix":
                kill_process_group = cast(
                    Callable[[int, int], None],
                    os.__dict__["killpg"],
                )
                kill_process_group(process.pid, signal.SIGTERM)
            else:
                try:
                    ctrl_break_event = cast(int, signal.__dict__["CTRL_BREAK_EVENT"])
                    os.kill(process.pid, ctrl_break_event)
                except (OSError, ValueError):
                    process.terminate()
        except (ProcessLookupError, PermissionError):
            return
        parent_stopped = False
        try:
            await asyncio.wait_for(process.wait(), timeout=self.termination_grace_seconds)
            parent_stopped = True
        except TimeoutError:
            parent_stopped = False
        if os.name == "posix":
            try:
                kill_process_group = cast(
                    Callable[[int, int], None],
                    os.__dict__["killpg"],
                )
                kill_process_group(
                    process.pid,
                    getattr(signal, "SIGKILL", signal.SIGTERM),
                )
            except ProcessLookupError:
                pass
            if process.returncode is None:
                await process.wait()
            return
        if parent_stopped:
            return
        try:
            process.kill()
        except ProcessLookupError:
            return
        await process.wait()
