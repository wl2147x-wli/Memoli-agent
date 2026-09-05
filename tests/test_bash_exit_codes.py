"""Non-zero exit codes that are not failures.

grep exiting 1 on no matches, or find exiting 1 on an unreadable directory,
used to come back as a failed tool call: misleading on its own, and counted
towards the consecutive-failure circuit breaker.
"""

import pytest

from agent.tools.bash.bash import Bash
from agent.tools.bash.exit_codes import interpret

posix_only = pytest.mark.skipif(Bash._IS_WIN, reason="POSIX shell command")


@pytest.mark.parametrize("command, note", [
    ("grep foo file.txt", "No matches found"),
    ("rg foo", "No matches found"),
    ("find . -name x", "Some directories were inaccessible"),
    ("diff a b", "Files differ"),
    ("test -f missing", "Condition is false"),
])
def test_informational_exit_1_is_not_a_failure(command, note):
    assert interpret(command, 1) == (False, note)


@pytest.mark.parametrize("command", ["cat missing", "python3 x.py", "ls /nope"])
def test_other_commands_still_fail_on_exit_1(command):
    assert interpret(command, 1) == (True, None)


def test_exit_2_is_a_real_error_even_for_grep():
    assert interpret("grep foo file.txt", 2) == (True, None)


def test_exit_code_comes_from_the_last_command_in_the_chain():
    # 报告的情况：链以 find 结束，在 a 上退出 1
    # 即使 stderr 被静音，目录也不可读。
    chain = 'find / -iname "*x*" 2>/dev/null; echo "---"; find ~ -iname "*y*" 2>/dev/null'
    assert interpret(chain, 1)[0] is False
    # 管道将退出代码传递给最后阶段，没有特殊情况。
    assert interpret("find . -name x | head -20", 1) == (True, None)


def test_separators_inside_quotes_do_not_split_the_command():
    assert interpret('echo "a; b" && grep x f', 1) == (False, "No matches found")


def test_env_assignment_prefix_is_skipped():
    assert interpret("VAR=1 grep x f", 1) == (False, "No matches found")


@posix_only
def test_grep_without_matches_reports_success(tmp_path):
    tool = Bash({"cwd": str(tmp_path)})
    (tmp_path / "f.txt").write_text("hello\n")

    result = tool.execute({"command": "grep zzzz f.txt"})

    assert result.status == "success"
    assert result.result["exit_code"] == 1
    assert "No matches found" in result.result["output"]


@posix_only
def test_a_real_failure_is_still_reported(tmp_path):
    tool = Bash({"cwd": str(tmp_path)})

    result = tool.execute({"command": "cat definitely-missing.txt"})

    assert result.status == "error"
