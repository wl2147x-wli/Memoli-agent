"""
Write tool - Write file content
Creates or overwrites files, automatically creates parent directories
"""

import os
from typing import Dict, Any
from pathlib import Path

from agent.tools.base_tool import BaseTool, ToolResult
from agent.tools.utils.credentials import is_credential_path
from agent.tools.utils.diff import looks_like_line_numbered_block
from agent.tools.utils.file_state import note_write, staleness_warning
from agent.tools.utils.syntax_check import review as syntax_review
from common.utils import expand_path


class Write(BaseTool):
    """Tool for writing file content"""
    
    name: str = "write"
    description: str = "Write content to a file, overwriting the existing file if there is one at the path. Creates parent directories automatically. Prefer the edit tool for modifying an existing file - it only sends the text being changed. Only use write to create new files or for complete rewrites."
    
    params: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to write (relative or absolute)"
            },
            "content": {
                "type": "string",
                "description": "Content to write to the file"
            }
        },
        "required": ["path", "content"]
    }
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())
        self.memory_manager = self.config.get("memory_manager", None)
    
    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """
        Execute file write operation
        
        :param args: Contains file path and content
        :return: Operation result
        """
        path = args.get("path", "").strip()
        content = args.get("content", "")
        
        if not path:
            return ToolResult.fail("Error: path parameter is required")

        # write 替换整个文件，因此在此处回显 read 的编号输出
        # 会立即损坏每一行。
        if looks_like_line_numbered_block(content):
            return ToolResult.fail(
                f"Error: content looks like read tool output ('12|content'), not file "
                f"content. Those line-number prefixes are display only - strip them "
                f"before writing {path}."
            )
        
        try:
            # 解析路径（可能会引发受保护位置的 PermissionError）
            absolute_path = self._resolve_path(path)

            # 创建父目录（如果需要）
            parent_dir = os.path.dirname(absolute_path)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            
            # 写入前检查 - 我们自己的写入会重置 mtime。
            warning = staleness_warning(absolute_path)

            previous = None
            if os.path.isfile(absolute_path):
                try:
                    with open(absolute_path, 'r', encoding='utf-8') as f:
                        previous = f.read()
                except (OSError, UnicodeDecodeError):
                    previous = None
            blocking, syntax_warning = syntax_review(absolute_path, previous, content)
            if blocking:
                return ToolResult.fail(f"Error: {blocking}")

            # 写入文件
            with open(absolute_path, 'w', encoding='utf-8') as f:
                f.write(content)
            note_write(absolute_path)
            
            # 获取写入的字节数
            bytes_written = len(content.encode('utf-8'))
            
            # 如果这是内存文件，则自动同步到内存数据库
            if self.memory_manager and 'memory/' in path:
                self.memory_manager.mark_dirty()
            
            result = {
                "message": f"Successfully wrote {bytes_written} bytes to {path}",
                "path": path,
                "bytes_written": bytes_written
            }
            warnings = [w for w in (warning, syntax_warning) if w]
            if warnings:
                result["warning"] = " ".join(warnings)
            
            return ToolResult.success(result)
            
        except PermissionError as e:
            return ToolResult.fail(f"Error: {str(e) or f'Permission denied writing to {path}'}")
        except Exception as e:
            return ToolResult.fail(f"Error writing file: {str(e)}")
    
    def _resolve_path(self, path: str) -> str:
        """
        Resolve path to absolute path

        :param path: Relative or absolute path
        :return: Absolute path
        :raises PermissionError: if the path targets a protected location
        """
        # 展开 ~ 到用户主目录
        path = expand_path(path)
        if os.path.isabs(path):
            absolute = path
        else:
            absolute = os.path.abspath(os.path.join(self.cwd, path))

        real = os.path.realpath(absolute)

        # 始终阻止凭据文件，镜像 bash 工具的防护。
        # 后缀规则还涵盖非 home .cow/.env 文件；共享守卫
        # 添加符号链接解析和 /proc 环境别名。
        if real.endswith(os.path.join(".cow", ".env")) or is_credential_path(absolute):
            raise PermissionError("writing to ~/.cow/.env is not allowed")

        # 可选的工作空间限制。默认关闭以保留现有的
        # 行为；通过 config.json tools.write.restrict_to_workspace 启用。
        if self.config.get("restrict_to_workspace"):
            ws = os.path.realpath(self.cwd)
            if os.path.commonpath([ws, real]) != ws:
                raise PermissionError(
                    f"writing outside the workspace is not allowed: {path}"
                )

        return absolute
