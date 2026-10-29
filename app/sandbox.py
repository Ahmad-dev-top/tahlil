"""Runs agent-written analysis code.

docker mode (default): throwaway container with no network, read-only rootfs, dropped
capabilities, non-root user, memory/CPU/PID limits and a hard timeout.
local mode: plain subprocess for development only. It is NOT isolated."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .config import settings

RUNNER = Path(__file__).resolve().parent.parent / "sandbox" / "runner.py"


@dataclass
class SandboxResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    stats: dict = field(default_factory=dict)  # last JSON object printed by the code
    charts: list[Path] = field(default_factory=list)


def _parse_stats(stdout: str) -> dict:
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                val = json.loads(line)
                return val if isinstance(val, dict) else {}
            except json.JSONDecodeError:
                continue
    return {}


def run_analysis(code: str, df: pd.DataFrame, keep_dir: Path) -> SandboxResult:
    """Runs `code` with `df` preloaded. Charts are copied into keep_dir."""
    with tempfile.TemporaryDirectory(prefix="tahlil-", dir=settings.sandbox_work_dir) as tmp:
        work = Path(tmp)
        (work / "out").mkdir()
        df.to_csv(work / "result.csv", index=False)
        (work / "analysis.py").write_text(code)
        # sandbox user (uid 10001) must be able to write charts
        work.chmod(0o777)
        (work / "out").chmod(0o777)

        if settings.sandbox_mode == "docker":
            name = f"tahlil-run-{uuid.uuid4().hex[:8]}"
            cmd = [
                "docker", "run", "--rm", "--name", name,
                "--network", "none", "--read-only", "--tmpfs", "/tmp:size=64m",
                "--memory", settings.sandbox_memory, "--cpus", "1", "--pids-limit", "128",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--user", "10001:10001",
                "-e", "WORK_DIR=/work", "-e", "MPLCONFIGDIR=/tmp",
                "-v", f"{work}:/work",
                settings.sandbox_image, "python", "/sandbox/runner.py",
            ]
        else:
            name = None
            cmd = [sys.executable, str(RUNNER)]

        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=settings.sandbox_timeout_s,
                env=None if name else {"WORK_DIR": str(work), "MPLCONFIGDIR": str(work), "PATH": "/usr/bin:/bin"},
            )
        except subprocess.TimeoutExpired:
            if name:
                subprocess.run(["docker", "kill", name], capture_output=True)
            return SandboxResult(ok=False, stderr=f"Timed out after {settings.sandbox_timeout_s}s")
        except FileNotFoundError as e:
            return SandboxResult(ok=False, stderr=f"Sandbox unavailable: {e}")

        keep_dir.mkdir(parents=True, exist_ok=True)
        charts = []
        for i, png in enumerate(sorted((work / "out").glob("*.png"))[:5], start=1):
            dest = keep_dir / f"chart_{i}.png"  # normalised names; the API only serves these
            shutil.copy(png, dest)
            charts.append(dest)

        return SandboxResult(
            ok=proc.returncode == 0,
            stdout=proc.stdout[-8000:],
            stderr=proc.stderr[-4000:],
            stats=_parse_stats(proc.stdout),
            charts=charts,
        )
