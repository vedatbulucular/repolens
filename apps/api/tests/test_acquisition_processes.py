"""Tests for shell-free process timeout and workspace monitoring."""

import asyncio
import sys
from pathlib import Path
from time import monotonic
from typing import cast

import pytest

from repolens_api.acquisition.processes import (
    ProcessRequest,
    ProcessSizeLimitExceeded,
    ProcessTimedOut,
    SubprocessRunner,
)


class CompletedProcess:
    """Minimal completed asyncio process used to inspect spawn options."""

    returncode: int | None = 0
    pid = 123

    async def communicate(self) -> tuple[bytes, bytes]:
        return b"", b""

    async def wait(self) -> int:
        return 0


def test_process_runner_uses_exec_without_a_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_arguments: tuple[str, ...] = ()
    captured_options: dict[str, object] = {}

    async def fake_create_subprocess_exec(
        *arguments: str,
        **options: object,
    ) -> asyncio.subprocess.Process:
        nonlocal captured_arguments, captured_options
        captured_arguments = arguments
        captured_options = options
        return cast(asyncio.subprocess.Process, CompletedProcess())

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    request = ProcessRequest(
        arguments=("git", "--version"),
        cwd=tmp_path,
        environment={},
        timeout_seconds=1,
        size_limit_path=tmp_path,
        max_size_bytes=100,
    )

    result = asyncio.run(SubprocessRunner().run(request))

    assert result.return_code == 0
    assert captured_arguments == ("git", "--version")
    assert "shell" not in captured_options
    assert captured_options["stdout"] is asyncio.subprocess.DEVNULL
    assert captured_options["stderr"] is asyncio.subprocess.DEVNULL


def test_process_runner_times_out_without_waiting_for_real_limit(tmp_path: Path) -> None:
    request = ProcessRequest(
        arguments=(sys.executable, "-c", "import time; time.sleep(5)"),
        cwd=tmp_path,
        environment={},
        timeout_seconds=0.05,
        size_limit_path=tmp_path,
        max_size_bytes=100,
    )

    with pytest.raises(ProcessTimedOut):
        asyncio.run(SubprocessRunner().run(request))


@pytest.mark.parametrize(("size", "should_fail"), [(1, False), (2, False), (3, True)])
def test_process_runner_enforces_workspace_size_boundaries(
    tmp_path: Path,
    size: int,
    should_fail: bool,
) -> None:
    (tmp_path / "workspace-data").write_bytes(b"x" * size)
    request = ProcessRequest(
        arguments=(sys.executable, "-c", "pass"),
        cwd=tmp_path,
        environment={},
        timeout_seconds=1,
        size_limit_path=tmp_path,
        max_size_bytes=2,
    )

    if should_fail:
        with pytest.raises(ProcessSizeLimitExceeded):
            asyncio.run(SubprocessRunner().run(request))
    else:
        assert asyncio.run(SubprocessRunner().run(request)).return_code == 0


def test_workspace_size_overage_terminates_a_running_process(tmp_path: Path) -> None:
    (tmp_path / "oversized").write_bytes(b"xx")
    request = ProcessRequest(
        arguments=(sys.executable, "-c", "import time; time.sleep(5)"),
        cwd=tmp_path,
        environment={},
        timeout_seconds=2,
        size_limit_path=tmp_path,
        max_size_bytes=1,
    )

    started = monotonic()
    with pytest.raises(ProcessSizeLimitExceeded):
        asyncio.run(SubprocessRunner().run(request))
    assert monotonic() - started < 1


def test_cancellation_terminates_a_running_process(tmp_path: Path) -> None:
    request = ProcessRequest(
        arguments=(sys.executable, "-c", "import time; time.sleep(5)"),
        cwd=tmp_path,
        environment={},
        timeout_seconds=2,
        size_limit_path=tmp_path,
        max_size_bytes=100,
    )

    async def exercise() -> None:
        task = asyncio.create_task(SubprocessRunner().run(request))
        await asyncio.sleep(0.05)
        task.cancel()
        await task

    started = monotonic()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(exercise())
    assert monotonic() - started < 1
