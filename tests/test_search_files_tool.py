import os
import time

import pytest

from common.utils import expand_path
from agent.tools.search_files.search_files import SearchFiles, REGEX_MATCH_TIMEOUT_SECONDS


def _make_tool(tmp_path, **config_overrides):
    # 大多数测试使用的默认工具。强制进入纯Python后端，所以
    # python 层安全保证（ReDoS 超时、超大文件跳过、
    # CRLF 处理、凭证修剪中途）是实际得到的
    # 锻炼——那些只存在于Python后端。跨后端
    # 行为奇偶校验由下面的 `backend` 固定装置单独覆盖。
    config = {"cwd": str(tmp_path)}
    config.update(config_overrides)
    tool = SearchFiles(config)
    tool._pick_backend = lambda: tool._backend_python
    return tool


def _available_backends():
    """Backend method names this platform would actually use (python always).

    Mirrors SearchFiles._pick_backend's platform gating so we only assert parity for
    backends the tool can really pick here: grep is Unix-only in the tool (the
    Windows grep from Git Bash mishandles UTF-8), and PowerShell is Windows-only.
    """
    import shutil
    import sys
    is_win = sys.platform == "win32"
    names = ["_backend_python"]
    if shutil.which("rg"):
        names.append("_backend_rg")
    if not is_win and shutil.which("grep"):
        names.append("_backend_grep")
    if is_win and (shutil.which("powershell") or shutil.which("pwsh")):
        names.append("_backend_powershell")
    return names


@pytest.fixture(params=_available_backends())
def backend_tool(request, tmp_path):
    """A tool pinned to one specific backend, parametrized over every backend
    installed on this machine, so behavior-contract tests assert cross-backend
    parity rather than only exercising whichever binary happens to be present."""
    tool = SearchFiles({"cwd": str(tmp_path)})
    name = request.param
    tool._pick_backend = lambda: getattr(tool, name)
    tool._backend_name = name
    return tool


def _write(tmp_path, relpath, content):
    path = tmp_path / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _matches(result):
    return result.result["matches"]


def test_appears_with_a_summary_in_the_system_prompt_tooling_section():
    # 每个同级文件工具（读/写/编辑/ls）都有一行摘要
    # 系统提示的“工具”部分实际上是模型读取的；
    # 没有摘要的条目（“- grep”，后面什么都没有）
    # 与所有其他工具不一致并默默地降低工具的性能
    # 选择质量。只检查积分点，不检查
    # 函数的更广泛的行为（没有事先测试 builder.py
    # 存在于此处扩展）。
    from agent.prompt.builder import _build_tooling_section

    fake_tool = type("FakeTool", (), {"name": "search_files"})()
    for language in ("en", "zh"):
        lines = _build_tooling_section([fake_tool], language)
        tooling_line = next(l for l in lines if l.startswith("- search_files"))
        assert tooling_line != "- search_files", f"missing summary for language={language}"


def test_configured_timeout_survives_the_real_tool_manager_wiring(tmp_path, monkeypatch):
    # 调用真正的 AgentInitializer._load_tools() — 它只涉及
    # self.agent_bridge 里面的 env_config 特例，其中 search_files
    # 没有命中，所以bridge=None/agent_bridge=None足以行使
    # 实际的合并逻辑，而不是在这里手动复制。
    from config import conf
    from bridge.agent_initializer import AgentInitializer

    monkeypatch.setitem(conf(), "tools", {"search_files": {"timeout": 5}})

    initializer = AgentInitializer(bridge=None, agent_bridge=None)
    tools = initializer._load_tools(
        workspace_root=str(tmp_path), memory_manager=None, memory_tools=[], session_id="test-session"
    )
    tool = next(t for t in tools if t.name == "search_files")
    assert tool.timeout == 5


# ---输入验证-------------------------------------------------

def test_pattern_required_returns_error(tmp_path):
    tool = _make_tool(tmp_path)
    result = tool.execute({})
    assert result.status == "error"
    assert "pattern" in str(result.result).lower()


def test_invalid_regex_returns_error(tmp_path):
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "("})
    assert result.status == "error"
    assert "regex" in str(result.result).lower()


def test_nonexistent_path_returns_error(tmp_path):
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "x", "path": "does_not_exist"})
    assert result.status == "error"
    assert "not found" in str(result.result).lower()


def test_path_may_target_a_single_file(tmp_path):
    # 与原始的仅目录工具不同，现在接受文件路径并
    # 将搜索范围限定为该一个文件（与 rg/grep 匹配，它很高兴地采用
    # 文件参数）。这是有意的能力增益，而不是倒退。
    _write(tmp_path, "file.txt", "hello world\nno match here\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "hello", "path": "file.txt"})
    assert result.status == "success"
    assert [m["file"] for m in _matches(result)] == ["file.txt"]
    assert _matches(result)[0]["line"] == 1


def test_invalid_max_results_returns_error(tmp_path):
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "x", "max_results": 0})
    assert result.status == "error"

    result = tool.execute({"pattern": "x", "max_results": "not-a-number"})
    assert result.status == "error"

    # 必须彻底拒绝小数浮点数，而不是默默地截断
    # 通过 int() （int(3.7) == 3 否则会掩盖格式错误的参数）。
    result = tool.execute({"pattern": "x", "max_results": 3.7})
    assert result.status == "error"


def test_integer_valued_float_max_results_is_accepted(tmp_path):
    # 3.0 没有分数（与上面的 3.7 不同）并且必须接受，而不是
    # 被捕获真实分数的相同 is_integer() 检查拒绝。
    for i in range(5):
        _write(tmp_path, f"file_{i}.txt", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET", "max_results": 3.0})
    assert result.status == "success"
    assert len(_matches(result)) == 3


def test_file_glob_must_be_a_string(tmp_path):
    # 以前来自 fnmatch.fnmatch() 的未处理的 TypeError，被吞没
    # base_tool.py 的裸 `except Exception: logger.error(e)` （无返回）进入
    # 然后调用者会在一个裸露的 None 上崩溃——而不是一个干净的 ToolResult.fail。
    _write(tmp_path, "a.txt", "hello\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "hello", "file_glob": 42})
    assert result.status == "error"
    assert "file_glob" in str(result.result)


# ---安全和限制---------------------------------------------------

def test_max_results_above_hard_cap_is_capped_not_rejected(tmp_path, monkeypatch):
    import agent.tools.search_files.search_files as sf_module
    monkeypatch.setattr(sf_module, "MAX_RESULTS_CAP", 3)

    for i in range(5):
        _write(tmp_path, f"file_{i}.txt", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET", "max_results": 100000})
    assert result.status == "success"
    assert len(_matches(result)) == 3
    # 当 3 已经是硬上限时，不得建议“使用 max_results=3” —
    # 这只会回显相同的数字并读取为无操作建议。
    assert "hard maximum" in result.result["notice"]
    assert "max_results=3 " not in result.result["notice"]
    assert "max_results=6" not in result.result["notice"]
    assert "3 result limit reached" in result.result["notice"]


def test_credential_directory_is_blocked(tmp_path):
    # 匹配 read.py 的 test_security_read_env_bypass.py 约定：
    # 直接 _is_credential_path 检查和 execute() 端到端检查
    # （在任何文件系统遍历发生之前必须拒绝，并且不会
    # 取决于 ~/.cow 实际存在）生活在同一个测试中。
    tool = _make_tool(tmp_path)
    cow_dir = expand_path("~/.cow")
    assert tool._is_credential_path(cow_dir) is True
    assert tool._is_credential_path(cow_dir + "/some/nested/file.db") is True
    assert tool._is_credential_path(str(tmp_path)) is False

    result = tool.execute({"pattern": ".", "path": cow_dir})
    assert result.status == "error"
    assert "Access denied" in str(result.result)


def test_credential_directory_is_pruned_mid_walk(tmp_path, monkeypatch):
    # 植根于 ~/.cow 之上的广泛搜索（不是直接针对它）必须
    # 在遍历过程中仍然对其进行修剪，而不是走进它。积分
    # Expand_path("~/.cow") 在 tmp_path 下的假目录中，所以这个练习
    # 真正的 _is_credential_path 逻辑，而不触及真正的主目录。
    import agent.tools.search_files.search_files as sf_module
    fake_cow = tmp_path / ".cow"
    fake_cow.mkdir()
    (fake_cow / "secret.env").write_text("API_KEY=leaked\n", encoding="utf-8")
    monkeypatch.setattr(sf_module, "expand_path", lambda p: str(fake_cow) if p == "~/.cow" else p)

    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "API_KEY"})
    assert result.status == "success"
    assert result.result["matches"] == []


def test_proc_environ_paths_are_blocked(tmp_path):
    # 镜像 read.py 自己对问题 #2913 的测试：纯路径字符串检查，
    # 不需要真正的 /proc 访问，因为 _is_credential_path 仅模式匹配。
    tool = _make_tool(tmp_path)
    assert tool._is_credential_path("/proc/self/environ") is True
    assert tool._is_credential_path("/proc/thread-self/environ") is True
    assert tool._is_credential_path(f"/proc/{os.getpid()}/environ") is True
    assert tool._is_credential_path("/proc/self/status") is False
    assert tool._is_credential_path("/proc/1/cmdline") is False


def test_symlink_to_credential_file_is_skipped_not_opened(tmp_path, monkeypatch):
    # 这个防范的错误：_is_credential_path 只被调用过
    # 在目录（遍历修剪）和根 `path` 参数上 - 从不
    # 在实际要打开的文件上。搜索内的符号链接
    # 指向凭证文件的树径直穿过，因为
    # open() 遵循符号链接。还验证修复是否是静默的每个文件
    # 跳过（匹配该文件的 == []，整体状态保持“成功”），
    # 不是中止整个搜索的错误 - 广泛的搜索不应该
    # 仅仅因为它偶然跨越了一个错误的符号链接就爆炸了。
    import agent.tools.search_files.search_files as sf_module
    fake_cow = tmp_path / "fake_cow"
    fake_cow.mkdir()
    (fake_cow / "secret.env").write_text("API_KEY=super-secret-value\n", encoding="utf-8")
    monkeypatch.setattr(sf_module, "expand_path", lambda p: str(fake_cow) if p == "~/.cow" else p)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "decoy.txt").symlink_to(fake_cow / "secret.env")
    (workspace / "real.txt").write_text("API_KEY=this one is fine\n", encoding="utf-8")

    tool = _make_tool(workspace)
    result = tool.execute({"pattern": "API_KEY"})
    assert result.status == "success"
    files = {m["file"] for m in _matches(result)}
    assert "decoy.txt" not in files
    assert "real.txt" in files


def test_symlinked_directory_pointing_at_credential_dir_is_pruned(tmp_path, monkeypatch):
    # os.walk 的默认 followlinks=False 已经拒绝下降到
    # 符号链接目录不管我们自己检查，所以这种情况是
    # 双重保护——但这正是为什么值得用一个
    # 测试：它确认 _search() 中的 dirnames-pruning 分支做了什么
    # 它的评论声称，而不是仅仅依赖 os.walk 默认值
    # 这段代码不控制。
    import agent.tools.search_files.search_files as sf_module
    fake_cow = tmp_path / "fake_cow"
    fake_cow.mkdir()
    (fake_cow / "secret.env").write_text("API_KEY=super-secret-value\n", encoding="utf-8")
    monkeypatch.setattr(sf_module, "expand_path", lambda p: str(fake_cow) if p == "~/.cow" else p)

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "decoy_dir").symlink_to(fake_cow, target_is_directory=True)

    tool = _make_tool(workspace)
    result = tool.execute({"pattern": "API_KEY"})
    assert result.status == "success"
    assert result.result["matches"] == []


def test_catastrophic_backtracking_pattern_is_preempted(tmp_path):
    # (a|aa)+$ 真正击败了 `regex` 包自己的回溯
    # 优化（与更简单的嵌套量词模式不同，它解决了
    # 立即）——根据经验验证，可以触发其本机每次调用超时。
    # stdlib re 已经在这个精确输入上花费了大约 2 秒并且呈指数增长
    # 从那里开始（40 个字符的行需要大约 22 秒），所以它没有这样的限制。
    _write(tmp_path, "evil.txt", "a" * 35 + "!\n")
    tool = _make_tool(tmp_path)

    start = time.monotonic()
    result = tool.execute({"pattern": r"(a|aa)+$"})
    elapsed = time.monotonic() - start

    assert result.status == "success"
    assert elapsed < REGEX_MATCH_TIMEOUT_SECONDS + 5
    assert "took longer than" in result.result["notice"]


def test_pattern_leading_trailing_whitespace_is_not_stripped(tmp_path):
    # `pattern` 中的前导/尾随空格对于正则表达式有意义
    # （“^”仅匹配以文字空格开头的行）并且不能
    # 按照此代码库中其他地方类似路径的参数的方式进行修剪。
    _write(tmp_path, "a.txt", " leading_space_line\nno_leading_space_line\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "^ "})
    assert result.status == "success"
    assert result.result["match_count"] == 1
    assert "leading_space_line" in _matches(result)[0]["match"]


def test_search_stops_at_timeout_and_reports_partial_results(tmp_path):
    for i in range(3):
        _write(tmp_path, f"file_{i}.txt", "TARGET\n")
    # 截止日期已经过去，强制执行第一次每个文件检查
    # 在 _search() 中，在打开任何文件之前立即跳闸。
    tool = _make_tool(tmp_path, timeout=-1)
    result = tool.execute({"pattern": "TARGET"})
    assert result.status == "success"
    assert result.result["match_count"] == 0
    assert "stopped after" in result.result["notice"]


def test_deadline_is_also_checked_inside_a_single_large_file(tmp_path, monkeypatch):
    # 请参阅 _search_single_file 的文档字符串了解此检查存在的原因。假货
    # time.monotonic() 确定性地前进而不是休眠，所以
    # 这保持很快并且不依赖于机器速度。
    import agent.tools.search_files.search_files as sf_module

    _write(tmp_path, "big.txt", "\n".join(f"line {i}" for i in range(20)) + "\n")
    tool = _make_tool(tmp_path, timeout=1)

    fake_now = [0.0]

    def fake_monotonic():
        fake_now[0] += 0.2
        return fake_now[0]

    monkeypatch.setattr(sf_module.time, "monotonic", fake_monotonic)

    result = tool.execute({"pattern": "nonexistent"})
    assert result.status == "success"
    assert "stopped after" in result.result["notice"]


def test_traversal_order_is_deterministic(tmp_path):
    for name in ("zzz.txt", "aaa.txt", "mmm.txt"):
        _write(tmp_path, name, "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET", "max_results": 2})
    assert result.status == "success"
    files = [m["file"] for m in _matches(result)]
    assert files == ["aaa.txt", "mmm.txt"]


# ---幸福之路-----------------------------------------------------------

def test_finds_matches_with_file_and_line(tmp_path):
    _write(tmp_path, "a.py", 'def f():\n    return "TARGET_MATCH here"\n')
    _write(tmp_path, "sub/b.py", "# another TARGET_MATCH in a subdirectory\nx = 1\n")
    _write(tmp_path, "notes.txt", "irrelevant, no target word\n")

    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET_MATCH"})
    assert result.status == "success"
    assert result.result["match_count"] == 2
    assert "notice" not in result.result

    files = {m["file"] for m in _matches(result)}
    assert files == {"a.py", "sub/b.py"}

    a_match = next(m for m in _matches(result) if m["file"] == "a.py")
    assert a_match["line"] == 2
    assert "TARGET_MATCH" in a_match["match"]


def test_no_matches_returns_empty_success_not_error(tmp_path):
    _write(tmp_path, "a.txt", "nothing interesting here\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "NOPE_NOT_PRESENT"})
    assert result.status == "success"
    assert result.result["matches"] == []
    assert result.result["match_count"] == 0


def test_file_glob_filters_results(tmp_path):
    _write(tmp_path, "match.py", "TARGET\n")
    _write(tmp_path, "match.txt", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET", "file_glob": "*.py"})
    assert result.status == "success"
    assert {m["file"] for m in _matches(result)} == {"match.py"}


def test_empty_file_glob_matches_everything_like_the_default(tmp_path):
    # `file_glob = args.get("file_glob", "*") or "*"` — 空字符串是
    # falsy，因此它会退回到“*”，与完全省略 arg 相同。
    _write(tmp_path, "match.py", "TARGET\n")
    _write(tmp_path, "match.txt", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET", "file_glob": ""})
    assert result.status == "success"
    assert {m["file"] for m in _matches(result)} == {"match.py", "match.txt"}


def test_max_results_caps_output_and_surfaces_notice_to_model(tmp_path):
    for i in range(10):
        _write(tmp_path, f"file_{i}.txt", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET", "max_results": 3})
    assert result.status == "success"
    assert len(_matches(result)) == 3
    assert result.result["match_count"] == 3
    # 该通知必须位于 `result.result` — `agent_stream.py` 的内部
    # `_execute_tool` 仅将 `status`/`result` 转发给模型，因此
    # `ToolResult.ext_data` 上的任何内容都将永远无法达到法学硕士。
    assert result.result["notice"] == "3 result limit reached. Use max_results=6 to see more."


def test_binary_files_are_skipped(tmp_path):
    (tmp_path / "binary.bin").write_bytes(bytes(range(256)))
    _write(tmp_path, "text.txt", "hello\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "."})
    assert result.status == "success"
    files = {m["file"] for m in _matches(result)}
    assert "binary.bin" not in files
    assert "text.txt" in files


def test_oversized_file_is_skipped_silently_with_no_count_exposed(tmp_path, monkeypatch):
    # 记录当前（接受）的行为：排除超大文件
    # 就像二进制/不可读的一样，在任何地方都没有出现跳过计数
    # 结果。不是错误——只是锁定已经描述的内容
    # 承诺（“自动......超大文件跳过”）所以未来的改变
    # 在这里增加可见性是一个深思熟虑的决定，而不是无声的倒退。
    import agent.tools.search_files.search_files as sf_module
    monkeypatch.setattr(sf_module, "MAX_FILE_BYTES", 10)

    _write(tmp_path, "huge.txt", "TARGET " * 20)
    _write(tmp_path, "small.txt", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET"})
    assert result.status == "success"
    assert result.result["match_count"] == 1
    assert _matches(result)[0]["file"] == "small.txt"
    assert "skipped" not in str(result.result).lower()


def test_utf8_bom_does_not_break_line_start_anchored_patterns(tmp_path):
    # UTF-8 BOM（常见于 Windows 编写的文件中）将解码为
    # 普通“utf-8”下第 1 行之前的文字 U+FEFF 字符，静默
    # 打破任何固定在行首的模式。火柴
    # read.py 出于同样的原因选择“utf-8-sig”。
    path = tmp_path / "bom.py"
    with open(path, "wb") as f:
        f.write(b"\xef\xbb\xbf")
        f.write("import os\n".encode("utf-8"))

    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "^import"})
    assert result.status == "success"
    assert result.result["match_count"] == 1


def test_crlf_line_endings_do_not_leak_into_matches_or_break_dollar_anchors(tmp_path):
    # content.split("\n") 单独在 a 的每一行留下尾随 \r
    # Windows 编写的 (CRLF) 文件 — 打破 $ 锚定模式并离开
    # 返回的匹配文本中不可见的杂散字符。
    with open(tmp_path / "windows.txt", "wb") as f:
        f.write(b"hello world\r\nfoo\r\n")

    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "world$"})
    assert result.status == "success"
    assert result.result["match_count"] == 1
    assert _matches(result)[0]["match"] == "hello world"


def test_skips_conventional_ignored_directories(tmp_path):
    _write(tmp_path, ".git/config", "TARGET\n")
    _write(tmp_path, "node_modules/pkg/index.js", "TARGET\n")
    _write(tmp_path, "src/app.py", "TARGET\n")

    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET"})
    assert result.status == "success"
    assert {m["file"] for m in _matches(result)} == {"src/app.py"}
    # 搜索回答了问题，所以排除是不值一提的。
    assert "notice" not in result.result


def test_no_notice_when_no_pruned_directory_exists(tmp_path):
    # 普通文档工作区中的常见情况：没有什么可跳过的，因此
    # 模型不得被告知任何有关 node_modules 的信息。
    _write(tmp_path, "src/app.py", "hello\n")

    result = _make_tool(tmp_path).execute({"pattern": "NOTHING"})
    assert result.status == "success"
    assert result.result["match_count"] == 0
    assert "notice" not in result.result


def test_no_ignore_reaches_into_pruned_directories(tmp_path):
    _write(tmp_path, "node_modules/pkg/index.js", "TARGET\n")

    tool = _make_tool(tmp_path)
    assert tool.execute({"pattern": "TARGET"}).result["match_count"] == 0

    result = tool.execute({"pattern": "TARGET", "no_ignore": True})
    assert result.status == "success"
    assert {m["file"] for m in _matches(result)} == {"node_modules/pkg/index.js"}
    assert "notice" not in result.result


def test_zero_matches_because_the_only_hit_was_in_a_pruned_directory(tmp_path):
    # 通知存在的确切场景： match_count == 0 这里不是
    # “真的什么都没有”——它是“唯一的匹配是在node_modules内部并且
    # 被修剪了”——只有通知才能区分这两种情况。
    _write(tmp_path, "node_modules/pkg/index.js", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET"})
    assert result.status == "success"
    assert result.result["match_count"] == 0
    notice = result.result["notice"]
    assert "node_modules" in notice        # 列出实际跳过的内容
    assert "no_ignore" in notice           # 以及如何达到这个目标


def test_no_skip_list_notice_when_nothing_was_pruned(tmp_path):
    _write(tmp_path, "src/app.py", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET"})
    assert result.status == "success"
    assert "notice" not in result.result


# --- 路径解析（符合 read/ls 约定）----------------------

def test_relative_path_resolves_under_workspace_cwd(tmp_path):
    _write(tmp_path, "sub/deep.txt", "TARGET\n")
    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "TARGET", "path": "sub"})
    assert result.status == "success"
    assert _matches(result)[0]["file"] == "deep.txt"


def test_absolute_path_outside_workspace_is_honored(tmp_path, tmp_path_factory):
    # 匹配现有的 read/ls 约定：允许绝对路径
    # 指向配置的工作空间 `cwd` 之外。使用 tmp_path_factory
    # （不是 tmp_path.parent，它是共享基目录，其他测试也可能
    # touch），因此在并行测试执行下保持隔离。
    outside = tmp_path_factory.mktemp("grep_outside")
    (outside / "f.txt").write_text("TARGET\n", encoding="utf-8")

    tool = _make_tool(tmp_path / "unrelated_workspace")
    (tmp_path / "unrelated_workspace").mkdir()
    result = tool.execute({"pattern": "TARGET", "path": str(outside)})
    assert result.status == "success"
    assert _matches(result)[0]["file"] == "f.txt"


# ---跨后端奇偶校验----------------------------------------------
# 4 层后端设计的要点是交换后端必须
# 不交换结果。这些对每个安装的后端运行相同的装置
# 在机器（rg/grep/python）上通过 `backend_tool` 夹具和断言
# 相同的输出 - 捕获 grep -c ":0" 分歧的守卫。

def _fixture_tree(tmp_path):
    _write(tmp_path, "a.py", "def handle():\n    MATCH = 1\n    return MATCH\n")
    _write(tmp_path, "sub/b.py", "# MATCH in a comment\nMATCH = 2\n")
    _write(tmp_path, "sub/c.txt", "MATCH here too\n")
    _write(tmp_path, "node_modules/pkg/index.js", "MATCH should be skipped\n")
    _write(tmp_path, "中文.py", "变量 MATCH 出现\n归属感 MATCH\n")


def test_backend_parity_files_mode(backend_tool, tmp_path):
    _fixture_tree(tmp_path)
    result = backend_tool.execute({"pattern": "MATCH", "output_mode": "files"})
    assert result.status == "success"
    files = set(result.result["files"])
    # 每个后端都排除node_modules；存在的所有其他文件。
    assert files == {"a.py", "sub/b.py", "sub/c.txt", "中文.py"}


def test_backend_parity_count_mode(backend_tool, tmp_path):
    _fixture_tree(tmp_path)
    result = backend_tool.execute({"pattern": "MATCH", "output_mode": "count"})
    assert result.status == "success"
    counts = {c["file"]: c["count"] for c in result.result["counts"]}
    # 否：0行，没有node_modules；跨后端的计数相同。
    assert counts == {"a.py": 2, "sub/b.py": 2, "sub/c.txt": 1, "中文.py": 2}


def test_backend_parity_content_mode_alternation(backend_tool, tmp_path):
    _fixture_tree(tmp_path)
    result = backend_tool.execute({"pattern": "归属感|变量", "output_mode": "content"})
    assert result.status == "success"
    hits = {(m["file"], m["line"]) for m in result.result["matches"]}
    assert hits == {("中文.py", 1), ("中文.py", 2)}


def test_backend_parity_glob_filter(backend_tool, tmp_path):
    _fixture_tree(tmp_path)
    result = backend_tool.execute({"pattern": "MATCH", "file_glob": "*.py", "output_mode": "files"})
    assert result.status == "success"
    assert set(result.result["files"]) == {"a.py", "sub/b.py", "中文.py"}


# --------------------------------------------------------------- 目标=文件
# 按 NAME 查找文件与在文件内搜索是不同的问题，
# 并且内容搜索无法回答它：grepping for "report.md" 只能找到
# 提及该字符串的文件，而不是文件本身。


def test_finds_file_by_glob(tmp_path):
    _write(tmp_path, "websites/ai-news-report.md", "body\n")
    _write(tmp_path, "notes.txt", "body\n")

    result = _make_tool(tmp_path).execute({"pattern": "*.md", "target": "files"})
    assert result.status == "success"
    assert result.result["files"] == ["websites/ai-news-report.md"]


def test_bare_word_is_treated_as_a_contains_match(tmp_path):
    # 该模式存在的现实世界失败：模型知道部分
    # 名称，否则不会从完全匹配的 glob 中得到任何结果。
    _write(tmp_path, "websites/ai-news-report.md", "body\n")

    result = _make_tool(tmp_path).execute({"pattern": "ai-news", "target": "files"})
    assert result.result["files"] == ["websites/ai-news-report.md"]


def test_content_search_for_a_filename_finds_nothing(tmp_path):
    # 记录为什么需要 target='files' 。
    _write(tmp_path, "websites/ai-news-report.md", "body\n")

    result = _make_tool(tmp_path).execute({"pattern": "ai-news-report", "output_mode": "files"})
    assert result.result["match_count"] == 0


def test_results_are_newest_first(tmp_path):
    import os
    old = _write(tmp_path, "old-report.md", "a\n")
    new = _write(tmp_path, "new-report.md", "b\n")
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))

    result = _make_tool(tmp_path).execute({"pattern": "*report*", "target": "files"})
    assert result.result["files"] == ["new-report.md", "old-report.md"]


def test_file_mode_skips_denylisted_dirs_unless_no_ignore(tmp_path):
    _write(tmp_path, "node_modules/pkg/index.js", "x\n")

    tool = _make_tool(tmp_path)
    result = tool.execute({"pattern": "*.js", "target": "files"})
    assert result.result["files"] == []
    assert "node_modules" in result.result["notice"]

    result = tool.execute({"pattern": "*.js", "target": "files", "no_ignore": True})
    assert result.result["files"] == ["node_modules/pkg/index.js"]


def test_file_mode_does_not_reject_glob_as_bad_regex(tmp_path):
    # “*.py”是无效的正则表达式；它不能在这里被验证为一个。
    _write(tmp_path, "a.py", "x\n")

    result = _make_tool(tmp_path).execute({"pattern": "*.py", "target": "files"})
    assert result.status == "success"
    assert result.result["files"] == ["a.py"]


def test_file_mode_caps_results_and_says_so(tmp_path):
    for i in range(5):
        _write(tmp_path, f"f{i}.md", "x\n")

    result = _make_tool(tmp_path).execute(
        {"pattern": "*.md", "target": "files", "max_results": 2}
    )
    assert len(result.result["files"]) == 2
    assert "5 files matched" in result.result["notice"]


def test_invalid_target_is_rejected(tmp_path):
    result = _make_tool(tmp_path).execute({"pattern": "x", "target": "nope"})
    assert result.status == "error"
    assert "target must be" in str(result.result)
