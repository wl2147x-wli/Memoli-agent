"""Editing workspace files from the preview panel (web console and desktop)."""

import json
import os
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.protocol.artifact import EDITABLE_KINDS
from agent.workspace.service import (
    MAX_TEXT_BYTES,
    WorkspaceConflictError,
    WorkspaceService,
)


def _service(tmp_path):
    return WorkspaceService(str(tmp_path))


def _write(path, text):
    """Write LF-only bytes; Path.write_text would translate to CRLF on Windows."""
    path.write_bytes(text.encode("utf-8"))
    return path


# ----------------------------------------------------------------------
# WorkspaceService.write_text
# ----------------------------------------------------------------------
def test_write_text_overwrites_and_reports_fresh_metadata(tmp_path):
    target = _write(tmp_path / "notes.md", "old\n")
    svc = _service(tmp_path)

    result = svc.write_text("notes.md", "# new\nbody\n")

    assert target.read_text(encoding="utf-8") == "# new\nbody\n"
    assert result["path"] == "notes.md"
    assert result["size"] == target.stat().st_size
    assert result["mtime"] == pytest.approx(target.stat().st_mtime)


def test_write_text_round_trips_through_read_text(tmp_path):
    _write(tmp_path / "a.py", "print(1)\n")
    svc = _service(tmp_path)

    loaded = svc.read_text("a.py")
    assert loaded["editable"] is True
    assert loaded["truncated"] is False

    svc.write_text("a.py", loaded["content"] + "print(2)\n",
                   expected_mtime=loaded["mtime"])
    assert svc.read_text("a.py")["content"] == "print(1)\nprint(2)\n"


def test_write_text_rejects_stale_mtime(tmp_path):
    target = _write(tmp_path / "notes.md", "original\n")
    svc = _service(tmp_path)
    stale = svc.read_text("notes.md")["mtime"]

    os.utime(target, (stale + 60, stale + 60))

    with pytest.raises(WorkspaceConflictError):
        svc.write_text("notes.md", "mine\n", expected_mtime=stale)
    # 冲突的内容必须在失败的尝试中幸存下来。
    assert target.read_text(encoding="utf-8") == "original\n"

    # 如果没有基线，写入将被显式覆盖并完成。
    svc.write_text("notes.md", "mine\n")
    assert target.read_text(encoding="utf-8") == "mine\n"


def test_write_text_refuses_binary_kinds(tmp_path):
    (tmp_path / "chart.png").write_bytes(b"\x89PNG\r\n")
    svc = _service(tmp_path)

    with pytest.raises(ValueError):
        svc.write_text("chart.png", "not an image")
    assert (tmp_path / "chart.png").read_bytes() == b"\x89PNG\r\n"


def test_write_text_refuses_to_create_missing_file(tmp_path):
    svc = _service(tmp_path)

    with pytest.raises(FileNotFoundError):
        svc.write_text("does-not-exist.md", "hello")
    assert not (tmp_path / "does-not-exist.md").exists()


def test_write_text_rejects_path_escaping_the_workspace(tmp_path):
    outside = tmp_path.parent / "outside.md"
    _write(outside, "secret\n")
    root = tmp_path / "root"
    root.mkdir()
    svc = _service(root)

    with pytest.raises(ValueError):
        svc.write_text("../outside.md", "tampered\n")
    assert outside.read_text(encoding="utf-8") == "secret\n"


def test_write_text_rejects_oversized_content(tmp_path):
    _write(tmp_path / "big.txt", "x")
    svc = _service(tmp_path)

    with pytest.raises(ValueError):
        svc.write_text("big.txt", "y" * (MAX_TEXT_BYTES + 1))
    assert (tmp_path / "big.txt").read_text(encoding="utf-8") == "x"


def test_write_text_keeps_crlf_line_endings(tmp_path):
    target = tmp_path / "win.txt"
    target.write_bytes(b"one\r\ntwo\r\n")
    svc = _service(tmp_path)

    # 即使对于 CRLF 文件，浏览器也会返回仅 LF 文本。
    svc.write_text("win.txt", "one\ntwo\nthree\n")

    assert target.read_bytes() == b"one\r\ntwo\r\nthree\r\n"


def test_write_text_leaves_lf_files_alone(tmp_path):
    target = tmp_path / "unix.txt"
    target.write_bytes(b"one\ntwo\n")

    _service(tmp_path).write_text("unix.txt", "one\r\ntwo\r\n")

    assert target.read_bytes() == b"one\ntwo\n"


def test_read_text_marks_non_utf8_file_uneditable(tmp_path):
    """A GBK document previews with replacement chars; saving would destroy it."""
    (tmp_path / "gbk.txt").write_bytes("运动训练计划\n".encode("gbk"))

    loaded = _service(tmp_path).read_text("gbk.txt")

    assert loaded["lossy"] is True
    assert loaded["editable"] is False


def test_write_text_refuses_to_overwrite_a_non_utf8_file(tmp_path):
    original = "运动训练计划\n".encode("gbk")
    (tmp_path / "gbk.txt").write_bytes(original)

    with pytest.raises(ValueError):
        _service(tmp_path).write_text("gbk.txt", "\ufffd\ufffd\n")
    assert (tmp_path / "gbk.txt").read_bytes() == original


def test_write_text_refuses_a_file_too_large_to_have_been_read_whole(tmp_path):
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * (MAX_TEXT_BYTES + 10))

    with pytest.raises(ValueError):
        _service(tmp_path).write_text("big.txt", "truncated")
    assert big.stat().st_size == MAX_TEXT_BYTES + 10


def test_read_text_reports_clean_utf8_as_lossless(tmp_path):
    _write(tmp_path / "zh.md", "# 运动训练计划\n")

    loaded = _service(tmp_path).read_text("zh.md")

    assert loaded["lossy"] is False
    assert loaded["editable"] is True
    assert loaded["content"] == "# 运动训练计划\n"


def test_read_text_marks_truncated_file_uneditable(tmp_path):
    _write(tmp_path / "huge.txt", "z" * 4096)

    loaded = _service(tmp_path).read_text("huge.txt", max_bytes=1024)

    assert loaded["truncated"] is True
    assert loaded["editable"] is False


def test_dispatch_stays_read_only():
    """Remote transports forward action strings straight into dispatch."""
    result = WorkspaceService(".").dispatch("write", {"path": "a.md", "content": "x"})

    assert result["code"] == 400
    assert "unknown action" in result["message"]


# ----------------------------------------------------------------------
# HTTP 处理程序
# ----------------------------------------------------------------------
def _post(handler_cls, body):
    from channel.web import web_channel

    with patch.object(web_channel, "_require_auth"), \
         patch.object(web_channel.web, "header"), \
         patch.object(web_channel.web, "data", return_value=json.dumps(body).encode()):
        return json.loads(handler_cls().POST())


def _get(handler_cls, params):
    from channel.web import web_channel

    with patch.object(web_channel, "_require_auth"), \
         patch.object(web_channel.web, "header"), \
         patch.object(web_channel.web, "input", return_value=web_channel.web.storage(**params)):
        return json.loads(handler_cls().GET())


def test_read_handler_returns_content_and_baseline(tmp_path):
    from channel.web.web_channel import WorkspaceReadHandler

    _write(tmp_path / "notes.md", "hello\n")

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)), \
         patch("common.state_dir.state_root_str", return_value=str(tmp_path)):
        response = _get(WorkspaceReadHandler, {"path": "notes.md", "session": "s1", "agent": ""})

    assert response["status"] == "success"
    assert response["content"] == "hello\n"
    assert response["editable"] is True
    assert response["mtime"] == pytest.approx((tmp_path / "notes.md").stat().st_mtime)


def test_write_handler_saves_file(tmp_path):
    from channel.web.web_channel import WorkspaceWriteHandler

    target = _write(tmp_path / "notes.md", "hello\n")

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)), \
         patch("common.state_dir.state_root_str", return_value=str(tmp_path)):
        response = _post(WorkspaceWriteHandler, {
            "path": str(target),
            "content": "goodbye\n",
            "session": "s1",
            "expected_mtime": target.stat().st_mtime,
        })

    assert response["status"] == "success"
    assert target.read_text(encoding="utf-8") == "goodbye\n"


def test_write_handler_reports_conflict_code(tmp_path):
    from channel.web.web_channel import WorkspaceWriteHandler

    target = _write(tmp_path / "notes.md", "hello\n")

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)), \
         patch("common.state_dir.state_root_str", return_value=str(tmp_path)):
        response = _post(WorkspaceWriteHandler, {
            "path": "notes.md",
            "content": "mine\n",
            "expected_mtime": target.stat().st_mtime - 60,
        })

    assert response["status"] == "error"
    assert response["code"] == "conflict"
    assert target.read_text(encoding="utf-8") == "hello\n"


def test_write_handler_rejects_non_string_content(tmp_path):
    from channel.web.web_channel import WorkspaceWriteHandler

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)):
        response = _post(WorkspaceWriteHandler, {"path": "notes.md", "content": None})

    assert response["status"] == "error"
    assert "content" in response["message"]


def test_write_handler_rejects_path_outside_workspace(tmp_path):
    from channel.web.web_channel import WorkspaceWriteHandler

    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "elsewhere.md"
    _write(outside, "secret\n")

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(project)), \
         patch("common.state_dir.state_root_str", return_value=str(project)):
        response = _post(WorkspaceWriteHandler, {
            "path": str(outside),
            "content": "tampered\n",
        })

    assert response["status"] == "error"
    assert outside.read_text(encoding="utf-8") == "secret\n"


def test_write_handler_falls_back_to_state_root_for_system_assets(tmp_path):
    """Memory files stay in the state root even while a project is open."""
    from channel.web.web_channel import WorkspaceWriteHandler

    state_root = tmp_path / "cow"
    (state_root / "memory").mkdir(parents=True)
    memory_file = _write(state_root / "memory" / "MEMORY.md", "old\n")
    project = tmp_path / "project"
    project.mkdir()

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(project)), \
         patch("common.state_dir.state_root_str", return_value=str(state_root)):
        response = _post(WorkspaceWriteHandler, {
            "path": "memory/MEMORY.md",
            "content": "new\n",
            "session": "s1",
        })

    assert response["status"] == "success"
    assert memory_file.read_text(encoding="utf-8") == "new\n"


# ----------------------------------------------------------------------
# 前端合约
# ----------------------------------------------------------------------
def test_web_console_editor_contract():
    root = Path(__file__).parents[1]
    html = (root / "channel/web/chat.html").read_text(encoding="utf-8")
    js = (root / "channel/web/static/js/workspace.js").read_text(encoding="utf-8")
    css = (root / "channel/web/static/css/console.css").read_text(encoding="utf-8")
    console = (root / "channel/web/static/js/console.js").read_text(encoding="utf-8")

    assert 'id="ws-btn-edit"' in html
    assert 'id="ws-btn-save"' in html
    assert 'id="ws-btn-edit-cancel"' in html
    assert "onclick=\"startPreviewEdit()\"" in html
    assert "onclick=\"savePreviewEdit()\"" in html
    assert "onclick=\"cancelPreviewEdit()\"" in html

    assert "async function startPreviewEdit(" in js
    assert "async function savePreviewEdit(" in js
    assert "function cancelPreviewEdit(" in js
    assert "function wsGuardUnsaved(" in js
    # 文本区域将其值中的 CRLF 标准化为 LF，因此脏基线具有
    # 来自已安装的元素而不是来自原始响应文本 -
    # 否则，每个 CRLF 文件在打开时看起来都已编辑过。
    assert "wsEditBaseline = wsMountEditor(body, data.content).value;" in js
    # 守卫在重试之前清除编辑标志，因此必须丢弃
    # 通过 wsExitEdit 重试；通过cancelPreviewEdit重试会击中
    # 拥有 `if (!wsEditing) return` 并将编辑器留在屏幕上。
    assert "wsGuardUnsaved(wsExitEdit)" in js
    assert "/api/workspace/read?path=" in js
    assert "fetch('/api/workspace/write'" in js
    assert "expected_mtime:" in js
    assert "data.code === 'conflict'" in js

    assert ".ws-editor" in css
    # 编辑器显示的每个字符串都必须存在于所有三个区域设置中。
    for key in ("ws_edit", "ws_edit_save", "ws_edit_cancel", "ws_edit_saved",
                "ws_edit_save_failed", "ws_edit_load_failed", "ws_edit_too_large",
                "ws_edit_unsupported", "ws_edit_encoding", "ws_edit_conflict_title",
                "ws_edit_conflict_msg", "ws_edit_overwrite", "ws_edit_discard_title",
                "ws_edit_discard_msg", "ws_edit_discard_ok"):
        assert console.count(f"{key}:") == 3, key

    # 未更改的文件一定不能被重写，并且 Ctrl+S 一定不能
    # 将第二个写入与第一个写入的 mtime 进行竞赛。
    assert "if (!force && !wsEditorDirty())" in js
    assert "if (wsSaving) return;" in js

    # 切换会话或开始新的聊天会重置面板，因此两者都必须
    # 在提交之前解决一个开放的编辑器，而不是默默地放弃它。
    assert "!wsGuardUnsaved(() => switchSession(newSessionId))" in console
    assert "!wsGuardUnsaved(() => newChat(optimistic, inherit))" in console


def _desktop(rel):
    return (Path(__file__).parents[1] / "desktop/src/renderer/src" / rel).read_text(encoding="utf-8")


def test_desktop_editable_kinds_match_backend():
    """The Edit button is offered client-side; a drifted list would offer it for
    files the backend then refuses to save."""
    src = _desktop("lib/fileKind.ts")
    body = re.search(r"EDITABLE_KINDS[^[]*\[(.*?)\]", src, re.S).group(1)
    assert set(re.findall(r"'([^']+)'", body)) == EDITABLE_KINDS


def test_desktop_editor_contract():
    client = _desktop("api/client.ts")
    store = _desktop("store/workspaceStore.ts")
    editor = _desktop("components/FileEditor.tsx")
    panel = _desktop("components/WorkspacePanel.tsx")
    sessions = _desktop("store/sessionStore.ts")
    i18n = _desktop("i18n.ts")

    # 重用与 Web 控制台相同的端点，包括 mtime
    # 使代理的中期编辑重写可检测到。
    assert "async workspaceRead(" in client
    assert "/api/workspace/read?path=" in client
    assert "async workspaceWrite(" in client
    assert "this.request('/api/workspace/write'" in client
    assert "expected_mtime: args.expectedMtime ?? null," in client

    assert "startEdit: async () =>" in store
    assert "saveEdit: async (content, opts) =>" in store
    assert "guardUnsavedEdit: async () => {" in store
    assert "if (res.code === 'conflict') {" in store
    # 未更改的文件不得被重写，并且第二个 Ctrl+S 不得出现争用
    # 针对第一个的 mtime 进行写入。
    assert "if (!force && !edit.dirty) {" in store
    assert "if (!edit || edit.saving) return" in store
    # 文本区域将 CRLF 报告为 LF，因此基线必须标准化或
    # 每个 CRLF 文件在打开时看起来都经过编辑。
    assert r"res.content.replace(/\r\n/g, '\n')" in store
    # `current` 和 `edit.file` 都不能通过对象标识进行比较：
    # save 用一个相同但新的对象和一个身份替换该条目
    # 检查然后中止下一个编辑并使按钮看起来死了。
    assert "if (get().current?.path !== current.path) return" in store
    assert "if (get().edit?.file.path !== edit.file.path) return" in store

    # 关闭面板会卸载文本区域，因此必须首先询问；离开
    # 聊天路由也会卸载它，这就是文本被停放的原因。
    assert store.count("if (!(await get().guardUnsavedEdit())) return") >= 3
    assert "stashEditText(el.value)" in editor
    assert "!== edit.baseline" in editor
    assert "e.key === 'Escape'" in editor
    assert "e.key === 'Tab'" in editor
    assert "<FileEditor key={edit.file.path}" in panel
    # 声明式播种和聚焦：命令式 `el.value =`
    # 在 StrictMode 的双重调用下，仅挂载效果并不可靠。
    assert "defaultValue={edit.loaded}" in editor
    assert "autoFocus" in editor

    # 切换会话、开始新的聊天或重新绑定项目
    # 重新调整面板范围，因此每个人都必须在其*之前*设置一个打开的编辑器
    # 承诺 - 事后询问导致拒绝无法取消。
    assert "if (id !== get().activeId && !(await useWorkspaceStore.getState().guardUnsavedEdit())) return" in sessions
    for rel in ("pages/ChatPage.tsx", "layout/SessionList.tsx", "App.tsx",
                "components/WorkspaceSelector.tsx"):
        assert "if (!(await useWorkspaceStore.getState().guardUnsavedEdit())) return" in _desktop(rel), rel

    # 当文本区域丢失时写入 '' 将会清空文件。
    assert "?.value ?? ''" not in panel
    assert "saveEdit(ref.current?.value ?? '')" not in editor

    # 编辑器显示的每个字符串都必须存在于两种语言环境中。
    for key in ("ws_edit", "ws_edit_save", "ws_edit_cancel", "ws_edit_unsaved",
                "ws_edit_load_failed", "ws_edit_unsupported", "ws_edit_too_large",
                "ws_edit_encoding", "ws_edit_discard_title", "ws_edit_discard_msg",
                "ws_edit_discard_ok", "ws_edit_overwrite",
                "ws_edit_conflict_title", "ws_edit_conflict_msg"):
        assert i18n.count(f"{key}:") == 2, key


def test_desktop_editor_avoids_native_confirm():
    """Electron runs window.confirm synchronously on the renderer's own thread,
    where it swallows the answer and leaves the window without keyboard focus -
    the editor became unusable after the first discard prompt. Ask through the
    in-app dialog instead."""
    for rel in ("store/workspaceStore.ts", "store/confirmStore.ts",
                "store/docEditorStore.ts", "components/FileEditor.tsx",
                "components/DocEditor.tsx", "components/WorkspacePanel.tsx"):
        src = _desktop(rel)
        # 是呼唤，而不是词语：评论解释了为什么要避免它。
        assert "window.confirm(" not in src, rel
        assert "window.alert(" not in src, rel

    # 安装在应用程序级别，不在任何一页内：未保存的编辑器
    # 当用户在另一条路线上并且提出问题时，其页面将过期
    # 那么就没有任何东西可以渲染它并且会挂起它的调用者。
    assert "<ConfirmDialog />" in _desktop("App.tsx")
    assert "useConfirmStore" in _desktop("components/ConfirmDialog.tsx")
    # 第二个问题必须撤回第一个问题，否则等待它的人就会被绞死。
    assert "get().pending?.resolve(false)" in _desktop("store/confirmStore.ts")
