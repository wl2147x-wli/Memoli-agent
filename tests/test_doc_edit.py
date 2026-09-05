"""Viewing and editing memory files and skill definitions in the web console."""

import json
import re
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.workspace.service import WorkspaceConflictError, WorkspaceService

SKILL_MD = """---
name: {name}
description: {desc}
---

# {name}

Instructions.
"""


def _write(path, text):
    """Write LF-only bytes; Path.write_text would translate to CRLF on Windows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def _memory(root):
    from agent.memory.service import MemoryService

    return MemoryService(str(root))


def _skill_dir(root, name, desc="does a thing"):
    _write(root / name / "SKILL.md", SKILL_MD.format(name=name, desc=desc))
    return root / name / "SKILL.md"


def _skills(builtin, custom):
    from agent.skills.manager import SkillManager
    from agent.skills.service import SkillService

    builtin.mkdir(parents=True, exist_ok=True)
    custom.mkdir(parents=True, exist_ok=True)
    return SkillService(SkillManager(builtin_dir=str(builtin), custom_dir=str(custom)))


# ----------------------------------------------------------------------
# 内存：编辑器需要的相对路径
# ----------------------------------------------------------------------
def test_memory_content_reports_the_path_under_the_workspace(tmp_path):
    _write(tmp_path / "MEMORY.md", "# global\n")
    _write(tmp_path / "memory" / "2026-08-26.md", "# daily\n")
    svc = _memory(tmp_path)

    assert svc.get_content("MEMORY.md")["rel_path"] == "MEMORY.md"
    assert svc.get_content("2026-08-26.md")["rel_path"] == "memory/2026-08-26.md"


def test_memory_content_reports_the_path_of_a_dream_and_an_evolution_file(tmp_path):
    _write(tmp_path / "memory" / "dreams" / "2026-08-26.md", "# dreamt\n")
    _write(tmp_path / "memory" / "evolution" / "2026-08-26.md", "# learned\n")
    svc = _memory(tmp_path)

    assert svc.get_content("2026-08-26.md", category="dream")["rel_path"] \
        == "memory/dreams/2026-08-26.md"
    assert svc.get_content("2026-08-26.md", category="evolution")["rel_path"] \
        == "memory/evolution/2026-08-26.md"


def test_memory_rel_path_is_what_the_workspace_editor_can_open(tmp_path):
    """The console hands this path straight to the workspace read/write API, so
    the two views of the same file have to agree."""
    _write(tmp_path / "memory" / "dreams" / "2026-08-26.md", "# dreamt\n")

    loaded = _memory(tmp_path).get_content("2026-08-26.md", category="dream")
    ws = WorkspaceService(str(tmp_path))

    assert ws.read_text(loaded["rel_path"])["content"] == loaded["content"]
    ws.write_text(loaded["rel_path"], "# edited\n")
    assert _memory(tmp_path).get_content("2026-08-26.md", category="dream")["content"] \
        == "# edited\n"


# ----------------------------------------------------------------------
# 技能：阅读
# ----------------------------------------------------------------------
def test_read_content_returns_a_workspace_skill_as_editable(tmp_path):
    _skill_dir(tmp_path / "custom", "note-taker")
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    result = svc.read_content("note-taker")

    assert result["source"] == "custom"
    assert result["editable"] is True
    assert result["ships_with_install"] is False
    assert result["filename"] == "SKILL.md"
    assert "# note-taker" in result["content"]
    assert result["mtime"] > 0


def test_read_content_marks_a_builtin_skill_read_only(tmp_path):
    """Its file ships with the installation, so an upgrade would drop the edit."""
    _skill_dir(tmp_path / "builtin", "image-maker")
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    result = svc.read_content("image-maker")

    assert result["source"] == "builtin"
    assert result["editable"] is False
    assert result["ships_with_install"] is True
    # 仍然可读：重点是能够了解技能的含义
    # 代理办事，是否可以在这里更改。
    assert "# image-maker" in result["content"]


def test_read_content_rejects_an_unknown_skill(tmp_path):
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    with pytest.raises(FileNotFoundError):
        svc.read_content("no-such-skill")


def test_read_content_requires_a_name(tmp_path):
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    with pytest.raises(ValueError):
        svc.read_content("   ")


# ----------------------------------------------------------------------
# 技能：写作
# ----------------------------------------------------------------------
def test_write_content_saves_a_workspace_skill(tmp_path):
    target = _skill_dir(tmp_path / "custom", "note-taker")
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")
    loaded = svc.read_content("note-taker")

    result = svc.write_content(
        "note-taker",
        loaded["content"] + "\nOne more rule.\n",
        expected_mtime=loaded["mtime"],
    )

    assert target.read_text(encoding="utf-8").endswith("One more rule.\n")
    assert result["size"] == target.stat().st_size


def test_write_content_refuses_a_builtin_skill(tmp_path):
    target = _skill_dir(tmp_path / "builtin", "image-maker")
    original = target.read_bytes()
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    with pytest.raises(ValueError):
        svc.write_content("image-maker", "rewritten\n")
    assert target.read_bytes() == original


def test_write_content_reports_a_mid_edit_rewrite(tmp_path):
    """The agent can rewrite a skill while it is open in the editor."""
    import os

    target = _skill_dir(tmp_path / "custom", "note-taker")
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")
    stale = svc.read_content("note-taker")["mtime"]
    os.utime(target, (stale + 60, stale + 60))

    with pytest.raises(WorkspaceConflictError):
        svc.write_content("note-taker", "mine\n", expected_mtime=stale)
    assert "# note-taker" in target.read_text(encoding="utf-8")

    # 如果没有基线，保存就会被故意覆盖并完成。
    svc.write_content("note-taker", "mine\n")
    assert target.read_text(encoding="utf-8") == "mine\n"


def test_write_content_cannot_escape_the_skills_directory(tmp_path):
    outside = _write(tmp_path / "outside.md", "secret\n")
    _skill_dir(tmp_path / "custom", "note-taker")
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    # 名称只能通过加载器的索引来解析，因此
    # 从未发现没有文件可指向。
    for name in ("../outside.md", "note-taker/../../outside.md", str(outside)):
        with pytest.raises((FileNotFoundError, ValueError)):
            svc.write_content(name, "tampered\n")
    assert outside.read_text(encoding="utf-8") == "secret\n"


def test_a_workspace_copy_of_a_builtin_skill_is_still_read_only(tmp_path):
    """Startup deletes and re-copies every builtin skill directory into the
    workspace (`_sync_builtin_skills` in app.py). The copy the loader resolves is
    therefore a `custom` one that the next restart replaces regardless, so
    `source` alone is the wrong thing to gate the editor on: an edit accepted
    here would vanish with nothing to say so."""
    _skill_dir(tmp_path / "builtin", "helper", desc="the shipped one")
    custom = _skill_dir(tmp_path / "custom", "helper", desc="the local one")
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    loaded = svc.read_content("helper")
    assert loaded["source"] == "custom"
    assert loaded["editable"] is False
    # `source` 在这里说 `custom`，所以它不可能是控制台解释的
    # 拒绝 - 因此有单独的标志。
    assert loaded["ships_with_install"] is True

    with pytest.raises(ValueError):
        svc.write_content("helper", SKILL_MD.format(name="helper", desc="edited"))
    assert "the local one" in custom.read_text(encoding="utf-8")


def test_write_content_refreshes_what_the_skill_list_shows(tmp_path):
    """Name and description come from the frontmatter the editor just changed."""
    _skill_dir(tmp_path / "custom", "note-taker", desc="old summary")
    svc = _skills(tmp_path / "builtin", tmp_path / "custom")

    svc.write_content("note-taker", SKILL_MD.format(name="note-taker", desc="new summary"))

    listed = {s["name"]: s for s in svc.query()}
    assert listed["note-taker"]["description"] == "new summary"


# ----------------------------------------------------------------------
# HTTP 处理程序
# ----------------------------------------------------------------------
def _get(handler_cls, params):
    from channel.web import web_channel

    with patch.object(web_channel, "_require_auth"), \
         patch.object(web_channel.web, "header"), \
         patch.object(web_channel.web, "input", return_value=web_channel.web.storage(**params)):
        return json.loads(handler_cls().GET())


def _post(handler_cls, body):
    from channel.web import web_channel

    with patch.object(web_channel, "_require_auth"), \
         patch.object(web_channel.web, "header"), \
         patch.object(web_channel.web, "data", return_value=json.dumps(body).encode()):
        return json.loads(handler_cls().POST())


def test_skill_content_handler_serves_and_saves(tmp_path):
    from channel.web.web_channel import SkillContentHandler

    target = _skill_dir(tmp_path / "skills", "console-editable")

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)):
        loaded = _get(SkillContentHandler, {"name": "console-editable"})
        assert loaded["status"] == "success"
        assert loaded["editable"] is True

        saved = _post(SkillContentHandler, {
            "name": "console-editable",
            "content": "# rewritten\n",
            "expected_mtime": loaded["mtime"],
        })

    assert saved["status"] == "success"
    assert target.read_text(encoding="utf-8") == "# rewritten\n"


def test_skill_content_handler_reports_a_conflict_code(tmp_path):
    from channel.web.web_channel import SkillContentHandler

    target = _skill_dir(tmp_path / "skills", "console-editable")
    original = target.read_text(encoding="utf-8")

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)):
        response = _post(SkillContentHandler, {
            "name": "console-editable",
            "content": "mine\n",
            "expected_mtime": target.stat().st_mtime - 60,
        })

    assert response["code"] == "conflict"
    assert target.read_text(encoding="utf-8") == original


def test_skill_content_handler_requires_a_name_and_string_content(tmp_path):
    from channel.web.web_channel import SkillContentHandler

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)):
        assert _get(SkillContentHandler, {"name": ""})["status"] == "error"
        assert _post(SkillContentHandler, {"name": "x", "content": None})["status"] == "error"


def test_memory_content_handler_includes_the_editable_path(tmp_path):
    from channel.web.web_channel import MemoryContentHandler

    _write(tmp_path / "MEMORY.md", "# global\n")

    with patch("channel.web.web_channel._get_workspace_root", return_value=str(tmp_path)):
        response = _get(MemoryContentHandler, {"filename": "MEMORY.md", "category": "memory"})

    assert response["status"] == "success"
    assert response["rel_path"] == "MEMORY.md"


# ----------------------------------------------------------------------
# 前端合约
# ----------------------------------------------------------------------
def _read(rel):
    return (Path(__file__).parents[1] / rel).read_text(encoding="utf-8")


def _web(rel):
    return _read(f"channel/web/{rel}")


def test_document_editor_is_loaded_before_its_users():
    """console.js builds both editors at load time, so the factory has to exist
    by then; `defer` keeps the scripts in document order."""
    html = _web("chat.html")

    assert html.index("assets/js/doc-editor.js") < html.index("assets/js/console.js")
    # 旧页面的缓存副本将要求提供一个脚本，该脚本已被
    # 重命名，因此新文件也必须位于缓存清除列表中。
    assert "js/doc-editor.js" in _read("channel/web/web_channel.py")


def test_document_editor_contract():
    editor = _web("static/js/doc-editor.js")

    assert "function createDocEditor(" in editor
    # 文本区域将其值中的 CRLF 标准化为 LF，因此脏基线具有
    # 来自已安装的元素而不是响应文本 - 否则
    # CRLF 文档在打开时看起来已被编辑。
    assert "baseline = mount(body, data.content).value;" in editor
    # 守卫在重试之前清除编辑标志，因此必须丢弃
    # 通过 exit() 重试；通过 cancel() 重试会遇到自己的问题
    # `if (!editing) return` 并将文本区域保留在屏幕上。
    assert "if (!guard(exit)) return;" in editor
    # 未触及的文档一定不能被重写，并且 Ctrl+S 一定不能
    # 使第二个写入与第一个写入的 mtime 竞争。
    assert "if (saving) return;" in editor
    assert "if (!force && !isDirty())" in editor
    assert "data.code === 'conflict'" in editor
    # 最后读取的内容是编辑器重绘的内容，或者保存显示的内容
    # 代理重写之前的副本。
    assert "target.content = data.content;" in editor


def test_memory_and_skill_editor_wiring():
    html = _web("chat.html")
    console = _web("static/js/console.js")
    css = _web("static/css/console.css")

    for ident in ("memory-btn-edit", "memory-btn-save", "memory-btn-cancel",
                  "skills-panel-viewer", "skill-viewer-content", "skill-viewer-title",
                  "skill-viewer-readonly", "skill-btn-edit", "skill-btn-save",
                  "skill-btn-cancel"):
        assert f'id="{ident}"' in html, ident
    assert 'onclick="memoryEditor.start()"' in html
    assert 'onclick="skillEditor.start()"' in html
    assert 'onclick="closeSkillViewer()"' in html

    assert "const memoryEditor = createDocEditor({" in console
    assert "const skillEditor = createDocEditor({" in console
    assert "textarea.doc-editor" in css

    # 内存文件保留在代理的状态根中。通过聊天会话
    # 将在该会话的任何项目中解析相同的相对路径
    # 已打开，并编辑或创建了错误的文件。
    for fn in ("docReadFile", "docWriteFile"):
        body = re.search(rf"async function {fn}\(.*?\n\}}", console, re.S).group(0)
        assert "session" not in body, fn

    # 技能通过名称来寻址：名称解析为哪个文件
    # 装载机的业务，而内置的则位于工作区之外。
    assert "/api/skills/content?name=" in console
    assert "fetch('/api/skills/content'" in console

    # 显示只读技能的原因来自服务器的标志。的
    # 内置函数的工作区副本读回为 `custom`，因此关闭 `source`
    # 会将这些（常见情况）解释为不受支持的文件类型。
    reason = re.search(r"function skillReadonlyReason\(.*?\n\}", console, re.S).group(0)
    assert "data.ships_with_install" in reason
    assert "data.source" not in reason

    # 离开页面、返回列表或关闭选项卡都会丢弃
    # 打开编辑器，所以每个人都必须先问。
    assert "if (!docGuardUnsaved(() => navigateTo(viewId))) return;" in console
    assert "if (!memoryEditor.guard(closeMemoryViewer)) return;" in console
    assert "if (!skillEditor.guard(closeSkillViewer)) return;" in console
    assert "if (!memoryEditor.isDirty() && !skillEditor.isDirty()) return;" in console

    # 这些视图显示的每个字符串都必须存在于所有三个区域设置中。
    for key in ("skill_back", "skill_open_hint", "skill_load_failed",
                "skill_builtin_readonly"):
        assert console.count(f"{key}:") == 3, key


# ----------------------------------------------------------------------
# 桌面客户端
# ----------------------------------------------------------------------
def _desktop(rel):
    return _read(f"desktop/src/renderer/src/{rel}")


def test_desktop_doc_editor_shares_one_implementation():
    """Memory and skills differ only in how a document is addressed, so the
    editing rules live in one factory rather than a copy per page."""
    store = _desktop("store/docEditorStore.ts")

    # 工作区面板和 Web 控制台也具有相同的保护措施。
    assert "if (res.code === 'conflict') {" in store
    assert "if (!force && !edit.dirty) {" in store
    assert "if (!edit || edit.saving) return" in store
    # 文本区域将 CRLF 报告为 LF，因此基线必须标准化或
    # 每个 CRLF 文件在打开时看起来都经过编辑。
    assert r"res.content.replace(/\r\n/g, '\n')" in store
    # 对用户已经留下的文档的响应不得覆盖
    # 屏幕上有什么。
    assert "if (mine !== seq) return" in store

    # 在模块范围内构建：未保存的编辑必须比其页面存在的时间长
    # 通过改变路线卸载，这也是让守卫找到它的原因。
    for rel in ("pages/MemoryPage.tsx", "pages/SkillsPage.tsx"):
        src = _desktop(rel)
        assert re.search(r"^const \w+Editor = createDocEditorStore", src, re.M), rel


def test_desktop_memory_editing_stays_in_the_state_root():
    """Memory files are anchored to the agent's state root. Passing a session
    would resolve the same relative path inside whatever project that session has
    open, and edit or create the wrong file."""
    page = _desktop("pages/MemoryPage.tsx")
    client = _desktop("api/client.ts")

    factory = re.search(r"createDocEditorStore<MemoryRef.*?\n\}\)", page, re.S).group(0)
    assert "workspaceRead(doc.relPath)" in factory
    assert "path: doc.relPath" in factory
    assert "session" not in factory

    # 路径必须来自后端：列表只知道文件名
    # 和类别，而读取和写入端点则采用路径。
    assert "async getMemoryDoc(" in client
    assert "meta.rel_path" in page


def test_desktop_skill_editing_is_addressed_by_name():
    """Which file a skill name resolves to is the loader's business, and a
    builtin skill's file sits outside the workspace."""
    page = _desktop("pages/SkillsPage.tsx")
    client = _desktop("api/client.ts")

    assert "/api/skills/content?name=" in client
    assert "this.request('/api/skills/content'" in client
    assert "expected_mtime: args.expectedMtime ?? null," in client

    # 显示只读技能的原因来自服务器的标志：
    # 内置函数的工作区副本读回为 `custom`，因此关闭 `source`
    # 会将这些（常见情况）解释为不受支持的文件类型。
    factory = re.search(r"createDocEditorStore<SkillRef.*?\n\}\)", page, re.S).group(0)
    assert "data.ships_with_install" in factory
    assert "data.source" not in factory

    # 返回列表必须重新阅读：保存的编辑可以更改名称
    # 以及卡片显示的描述，位于文件的前面。
    assert "void loadData()" in page


def test_desktop_doc_editors_are_guarded_on_the_way_out():
    """Leaving the page unmounts the text area, so every exit has to ask first -
    and ask *before* it commits, or declining cannot call it off."""
    assert "if (!(await guardDocEditors())) return" in _desktop("layout/NavRail.tsx")
    assert "if (!(await guardDocEditors())) return" in _desktop("App.tsx")

    # 返回列表，并切换内存选项卡，两者也会删除编辑器。
    assert "memoryEditor.getState().close()" in _desktop("pages/MemoryPage.tsx")
    assert "if (!(await memoryEditor.getState().guard())) return" in _desktop("pages/MemoryPage.tsx")
    assert "skillEditor.getState().close()" in _desktop("pages/SkillsPage.tsx")


def test_desktop_doc_editor_seeds_declaratively():
    """An imperative `el.value =` in a mount-only effect is not reliable under
    StrictMode's double invoke, and writing '' for a missing text area would
    empty the file."""
    editor = _desktop("components/DocEditor.tsx")

    assert "defaultValue={edit.loaded}" in editor
    assert "autoFocus" in editor
    assert "stashText(el.value)" in editor
    # 当文本区域丢失时，保存会恢复为空，而不是保存
    # '' - 这会在用户的内容上写入一个空文件。
    assert "if (el) void save(el.value)" in editor
    assert "save(ref.current?.value ?? '')" not in editor

    # 这些页面显示的每个字符串都必须存在于两个语言环境中。
    i18n = _desktop("i18n.ts")
    for key in ("doc_edit", "doc_edit_save", "skill_back", "skill_open_hint",
                "skill_builtin_readonly"):
        assert i18n.count(f"{key}:") == 2, key
