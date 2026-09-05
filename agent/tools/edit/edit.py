"""
Edit tool - Precise file editing
Edit files through exact text replacement
"""

import os
from typing import Dict, Any

from agent.tools.base_tool import BaseTool, ToolResult
from common.utils import expand_path
from agent.tools.utils.credentials import DENIED_MESSAGE, is_credential_path
from agent.tools.utils.diff import (
    strip_bom,
    detect_line_ending,
    normalize_to_lf,
    restore_line_endings,
    find_match_spans,
    generate_diff_string,
    looks_like_line_numbered_block,
    reindent_replacement,
    strip_line_number_prefixes,
)
from agent.tools.utils.file_state import note_write, staleness_warning
from agent.tools.utils.syntax_check import review as syntax_review


class Edit(BaseTool):
    """Tool for precise file editing"""
    
    name: str = "edit"
    description: str = "Edit a file by replacing exact text, or append to end if oldText is empty. For append: use empty oldText. For replace: oldText must match exactly (including whitespace) and must be unique unless replaceAll is true. IMPORTANT: the read tool prefixes each line with `12|` for display only - never include those prefixes in oldText or newText."
    
    params: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to the file to edit (relative or absolute)"
            },
            "oldText": {
                "type": "string",
                "description": "Text to find and replace, copied from the file itself WITHOUT the `12|` line-number prefixes shown by the read tool. Use empty string to append to end of file. For replacement: must match exactly including whitespace."
            },
            "newText": {
                "type": "string",
                "description": "New text to replace the old text with (no line-number prefixes)"
            },
            "replaceAll": {
                "type": "boolean",
                "description": "Replace every occurrence of oldText instead of requiring it to be unique. Default false."
            }
        },
        "required": ["path", "oldText", "newText"]
    }
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.cwd = self.config.get("cwd", os.getcwd())
        self.memory_manager = self.config.get("memory_manager", None)
    
    def execute(self, args: Dict[str, Any]) -> ToolResult:
        """
        Execute file edit operation
        
        :param args: Contains file path, old text and new text
        :return: Operation result
        """
        path = args.get("path", "").strip()
        old_text = args.get("oldText", "")
        new_text = args.get("newText", "")
        replace_all = bool(args.get("replaceAll", False))
        replacements_made = 1
        
        if not path:
            return ToolResult.fail("Error: path parameter is required")
        
        # 解析路径
        absolute_path = self._resolve_path(path)

        # 读取工具采用了同样的防护。编辑本质上也是一种读取：一次成功的
        # 编辑会返回一个 diff，其上下文行同样可能泄露秘密。
        if is_credential_path(absolute_path):
            return ToolResult.fail(DENIED_MESSAGE)

        # 检查文件是否存在
        if not os.path.exists(absolute_path):
            return ToolResult.fail(f"Error: File not found: {path}")
        
        # 检查是否可读/可写
        if not os.access(absolute_path, os.R_OK | os.W_OK):
            return ToolResult.fail(f"Error: File is not readable/writable: {path}")
        
        try:
            # 读取文件
            with open(absolute_path, 'r', encoding='utf-8') as f:
                raw_content = f.read()
            
            # 删除 BOM（LLM 不会在 oldText 中包含不可见的 BOM）
            bom, content = strip_bom(raw_content)
            
            # 检测原始行结尾
            original_ending = detect_line_ending(content)
            
            # 归一化为 LF
            normalized_content = normalize_to_lf(content)
            normalized_old_text = normalize_to_lf(old_text)
            normalized_new_text = normalize_to_lf(new_text)
            
            # 特殊情况：空 oldText 表示追加到文件末尾
            if not old_text or not old_text.strip():
                # 追加模式：把 newText 追加到文件末尾
                # 若文件末尾没有换行符，则在 newText 之前补一个换行符
                if normalized_content and not normalized_content.endswith('\n'):
                    new_content = normalized_content + '\n' + normalized_new_text
                else:
                    new_content = normalized_content + normalized_new_text
                base_content = normalized_content  # 用于验证
            else:
                # 普通编辑模式：查找并替换。
                # 优先进行精确匹配；只有当完全一致的子串不存在时，
                # 才会进入模糊匹配（参见 find_match_spans）。
                spans, exact = find_match_spans(normalized_content, normalized_old_text)

                if not spans:
                    # 后备方案：模型可能把读取输出里的 `12|` 行号前缀一并
                    # 复制了过来，这里去掉前缀再重试一次。只有常规匹配
                    # 失败之后才会走到这一步，因此真正包含 `12|` 的
                    # 内容绝不会被误伤。
                    retry_old = strip_line_number_prefixes(normalized_old_text)
                    if retry_old:
                        spans, exact = find_match_spans(normalized_content, retry_old)
                        if spans:
                            normalized_old_text = retry_old
                            stripped_new = strip_line_number_prefixes(normalized_new_text)
                            if stripped_new:
                                normalized_new_text = stripped_new

                if not spans:
                    return ToolResult.fail(
                        f"Error: Could not find the exact text in {path}. "
                        "The old text must match exactly including all whitespace and newlines."
                    )

                if len(spans) > 1 and not replace_all:
                    return ToolResult.fail(
                        f"Error: Found {len(spans)} occurrences of the text in {path}. "
                        "The text must be unique. Please provide more context to make it unique, "
                        "or set replaceAll to true to replace all of them."
                    )

                # 围绕匹配的跨度从后到前重建文件，以便
                # 较早的偏移量仍然有效。
                base_content = normalized_content
                new_content = base_content
                for start, end in reversed(spans):
                    replacement = normalized_new_text
                    if not exact:
                        # 模糊匹配会吞掉文件原有的缩进；
                        # 这里把替换文本重新对齐到原文的缩进上，而不是
                        # 悄悄按模型发来的内容把各行重新缩进。
                        replacement = reindent_replacement(
                            base_content[start:end], normalized_old_text, replacement
                        )
                    new_content = new_content[:start] + replacement + new_content[end:]
                replacements_made = len(spans)
            
            # 这个检查放在上面的后备逻辑之后：即使 newText 里的行号前缀
            # 只是因为 oldText 已被剥离前缀才出现的，也照样会被拦下。
            if looks_like_line_numbered_block(normalized_new_text):
                return ToolResult.fail(
                    f"Error: newText looks like read tool output ('12|content'), not file "
                    f"content. Those line-number prefixes are display only - strip them "
                    f"before editing {path}."
                )

            # 验证替换实际更改的内容
            if base_content == new_content:
                return ToolResult.fail(
                    f"Error: No changes made to {path}. "
                    "The replacement produced identical content. "
                    "This might indicate an issue with special characters or the text not existing as expected."
                )
            
            # 恢复原始行结尾
            final_content = bom + restore_line_endings(new_content, original_ending)

            # 写入前检查 - 我们自己的写入会重置 mtime。
            warning = staleness_warning(absolute_path)

            blocking, syntax_warning = syntax_review(absolute_path, base_content, new_content)
            if blocking:
                return ToolResult.fail(f"Error: {blocking}")

            # 写入文件
            with open(absolute_path, 'w', encoding='utf-8') as f:
                f.write(final_content)
            note_write(absolute_path)
            
            # 生成差异
            diff_result = generate_diff_string(base_content, new_content)

            if replacements_made > 1:
                message = f"Successfully replaced {replacements_made} occurrences in {path}"
            else:
                message = f"Successfully replaced text in {path}"

            result = {
                "message": message,
                "path": path,
                "diff": diff_result['diff'],
                "first_changed_line": diff_result['first_changed_line']
            }
            if replacements_made > 1:
                result["replacements"] = replacements_made
            warnings = [w for w in (warning, syntax_warning) if w]
            if warnings:
                result["warning"] = " ".join(warnings)
            
            # 如果文件位于内存目录中，则通知内存管理器
            if self.memory_manager and "memory/" in path:
                try:
                    self.memory_manager.mark_dirty()
                except Exception as e:
                    # 如果内存通知失败，编辑不会失败
                    pass
            
            return ToolResult.success(result)
            
        except UnicodeDecodeError:
            return ToolResult.fail(f"Error: File is not a valid text file (encoding error): {path}")
        except PermissionError:
            return ToolResult.fail(f"Error: Permission denied accessing {path}")
        except Exception as e:
            return ToolResult.fail(f"Error editing file: {str(e)}")
    
    def _resolve_path(self, path: str) -> str:
        """
        Resolve path to absolute path
        
        :param path: Relative or absolute path
        :return: Absolute path
        """
        # 展开 ~ 到用户主目录
        path = expand_path(path)
        if os.path.isabs(path):
            return path
        return os.path.abspath(os.path.join(self.cwd, path))
