"""参照 GenericAgent 行为重写的文件与代码工具。

GenericAgent: https://github.com/lsdefine/GenericAgent （MIT License）。
本模块只采用公开 schema 与行为思想，不依赖其反射分发和前端状态。
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memoli_agent.agent.tools.base import ToolResult
from memoli_agent.agent.tools.execution import WorkspacePathResolver, bound_text


@dataclass(frozen=True, slots=True)
class FileReadTool:
    """按行读取 workspace 内的 UTF-8 文件。"""

    workspace: Path
    max_lines: int = 2_000
    max_output_chars: int = 15_000
    name: str = "file_read"
    description: str = (
        "读取文件。修改前先读取以获得最新内容和行号；支持按一基行号分页。"
    )
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "workspace 内文件路径。"},
                "start": {
                    "type": "integer",
                    "description": "一基起始行。",
                    "default": 1,
                },
                "count": {
                    "type": "integer",
                    "description": "读取行数。",
                    "default": 200,
                },
                "show_linenos": {
                    "type": "boolean",
                    "description": "是否显示行号。",
                    "default": True,
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            target = WorkspacePathResolver(self.workspace).existing_file(
                str(arguments.get("path", ""))
            )
            start = int(arguments.get("start", 1))
            count = int(arguments.get("count", 200))
            if start < 1 or count < 1:
                raise ValueError("start 和 count 必须为正整数。")
            count = min(count, self.max_lines)
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeError, ValueError) as exc:
            return _failure(self.name, exc)

        lines = text.splitlines(keepends=True)
        selected = lines[start - 1 : start - 1 + count]
        show_linenos = bool(arguments.get("show_linenos", True))
        raw = "".join(
            f"{number}|{line}" if show_linenos else line
            for number, line in enumerate(selected, start=start)
        )
        visible, truncated = bound_text(raw, self.max_output_chars)
        return ToolResult(
            visible,
            raw_content=raw,
            metadata={
                "tool": self.name,
                "path": str(target),
                "start": start,
                "line_count": len(selected),
                "truncated": truncated,
            },
        )


@dataclass(frozen=True, slots=True)
class FilePatchTool:
    """用唯一精确匹配修改文件。"""

    workspace: Path
    name: str = "file_patch"
    description: str = (
        "精确替换唯一 old_content。空白和缩进必须完全一致；失败后重新 file_read。"
    )
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "workspace 内文件路径。"},
                "old_content": {"type": "string", "description": "必须唯一的原文本。"},
                "new_content": {"type": "string", "description": "替换后的文本。"},
            },
            "required": ["path", "old_content", "new_content"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        old = arguments.get("old_content")
        new = arguments.get("new_content")
        if not isinstance(old, str) or not old:
            return _failure(self.name, ValueError("old_content 不能为空。"))
        if not isinstance(new, str):
            return _failure(self.name, ValueError("new_content 必须是字符串。"))
        try:
            target = WorkspacePathResolver(self.workspace).existing_file(
                str(arguments.get("path", ""))
            )
            content = target.read_text(encoding="utf-8")
            matches = content.count(old)
            if matches != 1:
                raise ValueError(
                    f"old_content 必须唯一匹配，实际匹配 {matches} 次；请重新读取文件。"
                )
            updated = content.replace(old, new, 1)
            target.write_text(updated, encoding="utf-8", newline="")
        except (OSError, UnicodeError, ValueError) as exc:
            return _failure(self.name, exc)
        result = json.dumps(
            {"status": "success", "path": str(target), "replacements": 1},
            ensure_ascii=False,
        )
        return ToolResult(result, raw_content=result, metadata={"tool": self.name})


@dataclass(frozen=True, slots=True)
class FileWriteTool:
    """显式创建、覆盖、追加或前插文件内容。"""

    workspace: Path
    name: str = "file_write"
    description: str = (
        "创建、覆盖、追加或前插文件。content 必须显式提供；小修改优先 file_patch。"
    )
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "workspace 内文件路径。"},
                "content": {"type": "string", "description": "要写入的完整文本。"},
                "mode": {
                    "type": "string",
                    "enum": ["overwrite", "append", "prepend"],
                    "default": "overwrite",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        }
    )

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        content = arguments.get("content")
        mode = str(arguments.get("mode", "overwrite"))
        if not isinstance(content, str):
            return _failure(self.name, ValueError("content 必须显式提供字符串。"))
        if mode not in {"overwrite", "append", "prepend"}:
            return _failure(self.name, ValueError(f"不支持的写入模式：{mode}"))
        try:
            target = WorkspacePathResolver(self.workspace).writable_file(
                str(arguments.get("path", ""))
            )
            if mode == "append":
                with target.open("a", encoding="utf-8", newline="") as file:
                    file.write(content)
            elif mode == "prepend":
                old = target.read_text(encoding="utf-8") if target.exists() else ""
                target.write_text(content + old, encoding="utf-8", newline="")
            else:
                target.write_text(content, encoding="utf-8", newline="")
        except (OSError, UnicodeError, ValueError) as exc:
            return _failure(self.name, exc)
        result = json.dumps(
            {
                "status": "success",
                "path": str(target),
                "mode": mode,
                "written_bytes": len(content.encode("utf-8")),
            },
            ensure_ascii=False,
        )
        return ToolResult(result, raw_content=result, metadata={"tool": self.name})


@dataclass(frozen=True, slots=True)
class CodeRunTool:
    """通过容器或显式可信宿主 profile 执行代码。"""

    workspace: Path
    default_timeout_seconds: int = 60
    max_output_chars: int = 10_000
    runner: str = "container"
    container_cli: str = "docker"
    container_image: str = "memoli-code-runner@sha256:" + "0" * 64
    python_executable: str = ""
    allow_network: bool = False
    memory_mb: int = 256
    cpus: float = 0.5
    pids_limit: int = 64
    name: str = "code_run"
    description: str = (
        "代码执行器。优先 Python；脚本只在子进程执行，适合计算、搜索和批处理。"
    )
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "要执行的代码。"},
                "type": {
                    "type": "string",
                    "enum": ["python", "powershell"],
                    "default": "python",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数。",
                    "default": 60,
                },
                "cwd": {"type": "string", "description": "workspace 内工作目录。"},
            },
            "required": ["script"],
            "additionalProperties": False,
        }
    )

    def __post_init__(self) -> None:
        if self.runner not in {"container", "trusted-host", "disabled"}:
            raise ValueError("未知 code runner。")
        if self.runner == "container" and not re.search(
            r"@sha256:[0-9a-f]{64}$", self.container_image
        ):
            raise ValueError("容器镜像必须固定到 sha256 digest。")
        if self.runner == "trusted-host":
            executable = Path(self.python_executable)
            if not executable.is_absolute() or not executable.is_file():
                raise ValueError("trusted-host Python 必须是存在的绝对路径。")
        if self.memory_mb <= 0 or self.cpus <= 0 or self.pids_limit <= 0:
            raise ValueError("code runner 资源限制必须大于 0。")

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        script = arguments.get("script")
        code_type = str(arguments.get("type", "python"))
        if not isinstance(script, str) or not script:
            return _failure(self.name, ValueError("script 必须显式提供。"))
        if self.runner == "disabled":
            return _failure(self.name, PermissionError("代码执行器已禁用。"))
        if not self.allow_network and _looks_like_network_access(script):
            return _failure(
                self.name, PermissionError("当前执行 profile 禁止网络访问。")
            )
        try:
            timeout = int(arguments.get("timeout", self.default_timeout_seconds))
            if timeout <= 0:
                raise ValueError("timeout 必须大于 0。")
            raw_cwd = str(arguments.get("cwd") or ".")
            cwd = WorkspacePathResolver(self.workspace).resolve(
                raw_cwd, must_exist=True
            )
            if not cwd.is_dir():
                raise ValueError("cwd 不是目录。")
            command = self._command(code_type, script, cwd)
        except (OSError, ValueError) as exc:
            return _failure(self.name, exc)

        process: asyncio.subprocess.Process | None = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except TimeoutError:
            assert process is not None
            process.kill()
            await process.wait()
            raw = json.dumps({"status": "timeout", "timeout": timeout})
            return ToolResult(
                raw,
                success=False,
                raw_content=raw,
                status="timeout",
                metadata={"tool": self.name, "error": "TimeoutError"},
            )
        except OSError as exc:
            return _failure(self.name, exc)

        payload = {
            "status": "success" if process.returncode == 0 else "error",
            "exit_code": process.returncode,
            "stdout": stdout_bytes.decode("utf-8", errors="replace"),
            "stderr": stderr_bytes.decode("utf-8", errors="replace"),
        }
        raw = json.dumps(payload, ensure_ascii=False)
        visible, truncated = bound_text(raw, self.max_output_chars)
        success = process.returncode == 0
        return ToolResult(
            visible,
            success=success,
            raw_content=raw,
            status="success" if success else "error",
            metadata={
                "tool": self.name,
                "exit_code": process.returncode,
                "truncated": truncated,
                "error": None if success else "NonZeroExit",
            },
        )

    def _command(self, code_type: str, script: str, cwd: Path) -> list[str]:
        if self.runner == "trusted-host":
            return _trusted_code_command(
                code_type, script, python_executable=self.python_executable
            )
        if code_type != "python":
            raise ValueError("容器 code runner 第一版只支持 Python。")
        workspace = self.workspace.resolve()
        relative_cwd = cwd.resolve().relative_to(workspace).as_posix()
        container_cwd = "/workspace"
        if relative_cwd != ".":
            container_cwd += f"/{relative_cwd}"
        command = [
            self.container_cli,
            "run",
            "--rm",
            "-i",
            "--read-only",
            "--user",
            "65532:65532",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--pids-limit",
            str(self.pids_limit),
            "--memory",
            f"{self.memory_mb}m",
            "--memory-swap",
            f"{self.memory_mb}m",
            "--cpus",
            str(self.cpus),
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--mount",
            f"type=bind,src={workspace},dst=/workspace",
            "--workdir",
            container_cwd,
        ]
        if not self.allow_network:
            command.extend(("--network", "none"))
        command.extend((self.container_image, "python", "-c", script))
        return command


def _trusted_code_command(
    code_type: str, script: str, *, python_executable: str
) -> list[str]:
    if code_type == "python":
        return [python_executable, "-c", script]
    if code_type == "powershell":
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if executable is None:
            raise OSError("当前平台没有可用的 PowerShell。")
        return [executable, "-NoProfile", "-NonInteractive", "-Command", script]
    raise ValueError(f"不支持的代码类型：{code_type}")


_NETWORK_PATTERN = re.compile(
    r"(?i)(?:\b(?:socket|requests|urllib|httpx|aiohttp|ftplib|smtplib)\b|"
    r"invoke-webrequest|invoke-restmethod|start-bitstransfer|\bcurl(?:\.exe)?\b|"
    r"\bwget(?:\.exe)?\b|new-object\s+net\.webclient)"
)


def _looks_like_network_access(script: str) -> bool:
    """拒绝内置执行器中的常见网络原语；OS 沙箱仍由更高层提供。"""

    return _NETWORK_PATTERN.search(script) is not None


def _failure(tool: str, exc: Exception) -> ToolResult:
    error = type(exc).__name__
    content = json.dumps(
        {"status": "error", "error": error, "message": str(exc)},
        ensure_ascii=False,
    )
    return ToolResult(
        content,
        success=False,
        raw_content=content,
        status="error",
        metadata={"tool": tool, "error": error},
    )
