"""
Ls tool - List directory contents
"""

import os
from typing import Dict, Any

from agent.tools.base_tool import BaseTool, ToolResult
from agent.tools.utils.truncate import truncate_head, format_size, DEFAULT_MAX_BYTES
from common.utils import expand_path


DEFAULT_LIMIT = 500


class Ls(BaseTool):
    """Tool for listing directory contents"""
    
    name: str = "ls"
    description: str = f"List directory contents. Returns entries sorted alphabetically, with '/' suffix for directories. Includes dotfiles. Output is truncated to {DEFAULT_LIMIT} entries or {DEFAULT_MAX_BYTES // 1024}KB (whichever is hit first)."
    
    params: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory to list. IMPORTANT: Relative paths are based on workspace directory. To access directories outside workspace, use absolute paths starting with ~ or /."
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum number of entries to return (default: {DEFAULT_LIMIT})"
            }
        },
        "required": []
    }
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())
    
    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """
        Execute directory listing
        
        :param args: Listing parameters
        :return: Directory contents or error
        """
        path = args.get("path", ".").strip()
        limit = args.get("limit", DEFAULT_LIMIT)
        
        # 解析路径
        absolute_path = self._resolve_path(path)
        
        # 安全检查：防止访问敏感配置目录
        env_config_dir = expand_path("~/.cow")
        if os.path.abspath(absolute_path) == os.path.abspath(env_config_dir):
            return ToolResult.fail(
                "Error: Access denied. API keys and credentials must be accessed through the env_config tool only."
            )
        
        if not os.path.exists(absolute_path):
            # 相对路径找不到时，额外给一条有用的提示
            if not os.path.isabs(path) and not path.startswith('~'):
                return ToolResult.fail(
                    f"Error: Path not found: {path}\n"
                    f"Resolved to: {absolute_path}\n"
                    f"Hint: Relative paths are based on workspace ({self.cwd}). For files outside workspace, use absolute paths."
                )
            return ToolResult.fail(f"Error: Path not found: {path}")
        
        if not os.path.isdir(absolute_path):
            return ToolResult.fail(f"Error: Not a directory: {path}")
        
        try:
            # 读取目录条目
            entries = os.listdir(absolute_path)
            
            # 按字母顺序排序（不区分大小写）
            entries.sort(key=lambda x: x.lower())
            
            # 使用目录指示符格式化条目
            results = []
            entry_limit_reached = False
            
            for entry in entries:
                if len(results) >= limit:
                    entry_limit_reached = True
                    break
                
                full_path = os.path.join(absolute_path, entry)
                
                try:
                    if os.path.isdir(full_path):
                        results.append(entry + '/')
                    else:
                        results.append(entry)
                except Exception:
                    # 跳过我们无法统计的条目
                    continue
            
            if not results:
                return ToolResult.success({"message": "(empty directory)", "entries": []})
            
            # 格式化输出
            raw_output = '\n'.join(results)
            truncation = truncate_head(raw_output, max_lines=999999)  # 只受字节上限约束
            
            output = truncation.content
            details = {}
            notices = []
            
            if entry_limit_reached:
                notices.append(f"{limit} entries limit reached. Use limit={limit * 2} for more")
                details["entry_limit_reached"] = limit
            
            if truncation.truncated:
                notices.append(f"{format_size(DEFAULT_MAX_BYTES)} limit reached")
                details["truncation"] = truncation.to_dict()
            
            if notices:
                output += f"\n\n[{'. '.join(notices)}]"
            
            return ToolResult.success({
                "output": output,
                "entry_count": len(results),
                "details": details if details else None
            })
            
        except PermissionError:
            return ToolResult.fail(f"Error: Permission denied reading directory: {path}")
        except Exception as e:
            return ToolResult.fail(f"Error listing directory: {str(e)}")
    
    def _resolve_path(self, path: str) -> str:
        """Resolve path to absolute path"""
        # 展开 ~ 到用户主目录
        path = expand_path(path)
        if os.path.isabs(path):
            return path
        return os.path.abspath(os.path.join(self.cwd, path))
