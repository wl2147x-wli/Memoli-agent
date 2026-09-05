"""Safe configuration and core-file management for agent workspaces."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

from agent import team
from agent.registry import AgentProfile, AgentRegistry
from common.log import logger
from common.utils import expand_path


CORE_FILES = ("AGENT.md", "USER.md", "RULE.md", "MEMORY.md", "BOOTSTRAP.md")
MAX_CORE_FILE_BYTES = 1024 * 1024

# 克隆时保留的是代理如何行事，而不是它知道了什么。
# MEMORY.md 被排除在外，因为那记录的是源代理对用户的了解。
# .env、会话数据库和共享资产目录也被排除：复制它们会
# 分叉凭证、把某个代理的对话交给另一个代理，还会把技能库
# 复制到多处、彼此漂移。
CLONED_FILES = ("AGENT.md", "USER.md", "RULE.md", "BOOTSTRAP.md")

# 这些是本服务所负责的配置键。设置中的其余内容
# 归另一个控制台页面管理，本服务永远不会写入。
ROSTER_KEYS = team.TEAM_KEYS
_UNSET = object()


class AgentAdminError(ValueError):
    pass


class StaleAgentFileError(AgentAdminError):
    pass


class StaleRosterError(AgentAdminError):
    """Raised when the roster changed between the caller's read and its write."""


def _revision(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _roster_revision(settings: Mapping) -> str:
    """Revision over the Agent-owned slice of the config only.

    Scoped rather than whole-file so that saving an unrelated setting from
    another page does not invalidate an Agents page that is merely open, while
    two concurrent roster edits still conflict.
    """
    scoped = {key: settings.get(key) for key in ROSTER_KEYS}
    return _revision(
        json.dumps(scoped, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    )


def _is_strictly_within(inner: Path, outer: Path) -> bool:
    if inner == outer:
        return False
    try:
        inner.relative_to(outer)
    except ValueError:
        return False
    return True


class AgentAdminService:
    """Manage profiles without ever deleting an agent workspace implicitly."""

    def __init__(self, config_path: str, settings: Optional[Mapping] = None):
        self.config_path = Path(config_path)
        self._settings = dict(settings) if settings is not None else None
        self._lock = threading.RLock()

    def _load(self) -> Dict:
        """Deployment settings with the roster overlaid on top.

        Callers want one mapping to hand to ``AgentRegistry.from_config``, and
        should not have to know that the two halves come from different files.
        """
        if self._settings is not None:
            return team.resolve(self._settings)
        if not self.config_path.exists():
            return {}
        with self.config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            raise AgentAdminError("config root must be an object")
        return team.resolve(data)

    def _write(self, settings: Dict) -> None:
        """Persist the roster. ``config.json`` is not touched beyond retiring it.

        Only the roster keys are ever ours to write (``_commit`` enforces it),
        so the rest of ``settings`` is here to say where the file goes.
        """
        stored = dict(settings)
        if stored.get("agents"):
            stored["agents"] = team.compact(
                stored["agents"], settings, stored.get("default_agent_id") or ""
            )
        team.write(settings, stored)
        team.retire_legacy(self.config_path if self._settings is None else None)
        if self._settings is not None:
            self._settings = {
                key: value
                for key, value in settings.items()
                if key not in team.TEAM_KEYS
            }

    def _commit(self, updates: Mapping, revision: Optional[str] = None) -> Dict:
        """Apply the roster keys onto whatever is stored right now.

        Writing back a whole snapshot taken before the edit would drop any
        change another page made in between, so only the owned keys are written,
        and they are applied to a fresh read rather than to that snapshot.
        """
        current = self._load()
        if revision is not None and _roster_revision(current) != revision:
            raise StaleRosterError(
                "the Agent list changed since it was loaded; refresh before saving"
            )
        for key in updates:
            if key not in ROSTER_KEYS:
                raise AgentAdminError(f"refusing to write unowned config key: {key}")
        merged = dict(current)
        merged.update(updates)
        self._write(merged)
        return merged

    @staticmethod
    def _registry(settings: Mapping) -> AgentRegistry:
        return AgentRegistry.from_config(settings)

    @staticmethod
    def _explicit_profiles(settings: Dict, registry: AgentRegistry) -> list:
        raw_agents = settings.get("agents")
        if raw_agents:
            return [dict(item) for item in raw_agents]
        return [registry.get().to_dict()]

    @staticmethod
    def _instance_root(settings: Mapping) -> Path:
        return Path(
            AgentAdminService._normalise_workspace(
                settings.get("agent_workspace") or "~/cow"
            )
        )

    def snapshot(self) -> Dict:
        with self._lock:
            settings = self._load()
            registry = self._registry(settings)
            default_id = registry.default_agent_id
            agents = []
            for profile in registry.list():
                data = profile.to_dict()
                # 该代理读的是共享知识库还是自己的知识库，
                # 由工作区中的实际情况推导而来，以便 UI 显示切换状态。
                data["knowledge_mode"] = self._knowledge_mode_of(profile, default_id)
                agents.append(data)
            return {
                "default_agent_id": default_id,
                "agents": agents,
                "channel_instances": list(settings.get("channel_instances") or []),
                "revision": _roster_revision(settings),
            }

    @staticmethod
    def _knowledge_mode_of(profile: AgentProfile, default_id: str) -> str:
        if profile.id == default_id:
            return "shared"
        kdir = profile.workspace_path / "knowledge"
        if kdir.is_dir() and not kdir.is_symlink():
            return "own"
        return "shared"

    @staticmethod
    def _normalise_workspace(workspace: str) -> str:
        if not isinstance(workspace, str) or not workspace.strip():
            raise AgentAdminError("workspace is required")
        return str(Path(expand_path(workspace.strip())).resolve(strict=False))

    @staticmethod
    def _bootstrap_workspace(workspace: str) -> None:
        """Create only what belongs to this Agent alone.

        Deliberately does not create ``skills/`` or ``knowledge/``: an Agent opts
        out of the shared copy by *having* that directory, so creating them empty
        would cut every new Agent off from all installed skills and knowledge.
        ``ensure_workspace`` already scaffolds those through ``state_dir``, which
        lands them on the shared copy.
        """
        from agent.prompt import ensure_workspace
        from common import state_dir

        ensure_workspace(workspace, create_templates=True)
        state_dir.scheduler_file(base=workspace).parent.mkdir(
            parents=True, exist_ok=True
        )

    @staticmethod
    def _seed_name(workspace: str, name: str) -> None:
        """Write the given name into the Agent's own AGENT.md.

        The template leaves the name as an instruction to fill in later, which
        is right for the first Agent — it is named in conversation. But an Agent
        created from the console was named in the form, and an Agent that cannot
        read its own name does not recognise being addressed by it.

        Only the placeholder is replaced, so a cloned or hand-written persona
        that already states a name is left alone.
        """
        path = Path(workspace) / "AGENT.md"
        try:
            original = path.read_text(encoding="utf-8")
        except OSError:
            return
        updated = re.sub(
            r"^(- \*\*(?:名字|Name)\*\*:).*$",
            lambda m: f"{m.group(1)} {name}",
            original,
            count=1,
            flags=re.MULTILINE,
        )
        if updated == original:
            return
        try:
            path.write_text(updated, encoding="utf-8")
        except OSError as e:
            logger.warning(f"[AgentAdmin] Could not seed name into {path}: {e}")

    @staticmethod
    def _seed_user_profile(registry: AgentRegistry, destination: Path, *, cloned: bool) -> None:
        """Carry the operator profile (USER.md) into a new Agent.

        USER.md is a fact about the person running the instance, not about the
        persona, so a fresh Agent should start knowing it rather than blank. If a
        persona template was cloned it already brought its own USER.md, so this
        only fills the gap for an Agent created without a template.
        """
        target = destination / "USER.md"
        if cloned and target.is_file():
            return
        try:
            default_ws = registry.get(require_enabled=False).workspace_path
        except Exception:
            return
        src = default_ws / "USER.md"
        if src.is_file() and src.resolve() != target.resolve():
            try:
                shutil.copy2(src, target)
            except OSError as e:
                logger.warning(f"[AgentAdmin] Could not seed USER.md into {target}: {e}")

    @staticmethod
    def _make_own_knowledge(destination: Path) -> None:
        """Give a brand-new Agent its own knowledge base (opt out of shared)."""
        kdir = destination / "knowledge"
        try:
            kdir.mkdir(parents=True, exist_ok=True)
            index = kdir / "index.md"
            if not index.exists():
                index.write_text("# Knowledge Index\n", encoding="utf-8")
        except OSError as e:
            logger.warning(f"[AgentAdmin] Could not create own knowledge for {destination}: {e}")

    @staticmethod
    def _clone_persona(source: Path, destination: Path) -> None:
        """Copy how an Agent behaves, and nothing else.

        A whole-tree copy is wrong in every direction here: the default Agent's
        workspace is the instance root, so it contains every other Agent's
        workspace and the shared asset library, and copying it into a directory
        beneath itself recurses until the filesystem refuses the path length.
        """
        for filename in CLONED_FILES:
            candidate = source / filename
            if candidate.is_file():
                shutil.copy2(candidate, destination / filename)

    def _reject_overlapping_workspace(
        self, workspace: Path, registry: AgentRegistry, sanctioned: Path
    ) -> None:
        """Refuse a workspace nested in another Agent's, or containing one.

        The one nesting that is fine is the layout the registry itself derives,
        ``<instance root>/agents/<id>``, which necessarily sits inside the
        default Agent's workspace. Anything else makes one Agent's files
        reachable from another's root, so recursive work such as backup, clone
        or a workspace file listing would treat two Agents as one.
        """
        if workspace == sanctioned:
            return
        for profile in registry.list():
            other = Path(profile.workspace)
            if _is_strictly_within(workspace, other):
                raise AgentAdminError(
                    f"workspace sits inside agent '{profile.id}' workspace; "
                    f"use {sanctioned} or a path outside it"
                )
            if _is_strictly_within(other, workspace):
                raise AgentAdminError(
                    f"workspace contains agent '{profile.id}' workspace; "
                    f"use {sanctioned} or a path outside it"
                )

    @staticmethod
    def _asset_list(value, field: str) -> Optional[List[str]]:
        if value is None:
            return None
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise AgentAdminError(f"{field} must be a list of strings")
        return [x.strip() for x in value if x.strip()]

    def create_agent(
        self,
        agent_id: str,
        name: str,
        workspace: str = None,
        clone_from: str = None,
        description: str = None,
        avatar: str = None,
        skills: Optional[Iterable[str]] = None,
        knowledge: Optional[Iterable[str]] = None,
        knowledge_mode: str = None,
        revision: str = None,
    ) -> Dict:
        if knowledge_mode not in (None, "shared", "own"):
            raise AgentAdminError("knowledge mode must be 'shared' or 'own'")
        with self._lock:
            settings = self._load()
            registry = self._registry(settings)

            try:
                registry.get(agent_id, require_enabled=False)
            except KeyError:
                pass
            else:
                raise AgentAdminError(f"agent '{agent_id}' already exists")


            # 省略工作区是常见情况：新代理需要的是
            # 名称和角色，因此控制台不会询问路径。
            sanctioned = self._instance_root(settings) / "agents" / agent_id
            workspace = (
                self._normalise_workspace(workspace)
                if workspace
                else str(sanctioned)
            )
            destination = Path(workspace)
            self._reject_overlapping_workspace(destination, registry, sanctioned)

            if destination.exists() and any(destination.iterdir()):
                raise AgentAdminError("workspace must be empty for a new agent")

            source: Optional[Path] = None
            if clone_from:
                source = registry.get(clone_from).workspace_path
                if not source.is_dir():
                    raise AgentAdminError(
                        f"source workspace for '{clone_from}' does not exist"
                    )

            created_destination = not destination.exists()
            try:
                self._bootstrap_workspace(workspace)
                if source is not None:
                    self._clone_persona(source, destination)
                # USER.md 描述的是运行该实例的操作者，而不是角色本身，
                # 因此需要为每个新建代理复制一份默认代理的 USER.md
                # （除非所选模板已自带），让操作者档案得以延续，
                # 而不是从空白开始。
                self._seed_user_profile(registry, destination, cloned=source is not None)
                self._seed_name(workspace, name)
                if knowledge_mode == "own":
                    self._make_own_knowledge(destination)

                profile = AgentProfile(
                    id=agent_id,
                    name=name,
                    workspace=workspace,
                    description=(description or "").strip() or None,
                    avatar=(avatar or None),
                    skills=(
                        None if skills is None else tuple(self._asset_list(list(skills), "skills"))
                    ),
                    knowledge=(
                        None
                        if knowledge is None
                        else tuple(self._asset_list(list(knowledge), "knowledge"))
                    ),
                )
                registry.upsert(profile)
                profiles = self._explicit_profiles(settings, self._registry(settings))
                profiles.append(profile.to_dict())
                candidate = dict(settings)
                candidate["agents"] = profiles
                candidate["default_agent_id"] = registry.default_agent_id
                self._registry(candidate)
                self._commit(
                    {
                        "agents": profiles,
                        "default_agent_id": registry.default_agent_id,
                    },
                    revision,
                )
            except Exception:
                if created_destination and destination.exists():
                    shutil.rmtree(destination, ignore_errors=True)
                raise
            return profile.to_dict()

    def update_agent(
        self,
        agent_id: str,
        *,
        name: str = None,
        enabled: bool = None,
        make_default: bool = False,
        description: str = None,
        avatar: str = None,
        model: str = None,
        bot_type: str = None,
        skills=_UNSET,
        knowledge=_UNSET,
        revision: str = None,
    ) -> Dict:
        with self._lock:
            settings = self._load()
            registry = self._registry(settings)
            current = registry.get(agent_id, require_enabled=False)
            new_enabled = current.enabled if enabled is None else enabled
            if not isinstance(new_enabled, bool):
                raise AgentAdminError("enabled must be a boolean")
            new_name = current.name if name is None else name.strip()
            if not new_name:
                raise AgentAdminError("name must be a non-empty string")
            # 空字符串会清除该字段；省略它则意味着“保持不变”，
            # 因此控制台可以发送局部更新，而不会清掉它未提到的内容。
            new_avatar = current.avatar if avatar is None else (avatar.strip() or None)
            new_description = (
                current.description if description is None else (description.strip() or None)
            )
            new_model = current.model if model is None else (model.strip() or None)
            # 未指定供应商的模型会交由全局配置决定用哪个供应商，
            # 所以两者要一起变更、保持一致。
            new_bot_type = current.bot_type if bot_type is None else (bot_type.strip() or None)
            if not new_model:
                new_bot_type = None
            # 默认代理就是控制台“模型”设置所作用的那个代理。若这里
            # 再有第二个答案，就会有两个地方都能改它，却无法判断
            # 哪个说了算，所以晋升为默认代理时需放弃它自带的设置。
            becomes_default = make_default or agent_id == registry.default_agent_id
            if new_model and becomes_default:
                if make_default:
                    new_model = new_bot_type = None
                else:
                    raise AgentAdminError(
                        "the default agent follows the configured model; "
                        "change it in settings instead"
                    )
            # ``None`` 是一个有意义的取值（表示“使用全部共享技能”），
            # 与省略该字段不同。只有当请求显式给出了该字段时，
            # 处理程序才会传入对应参数。
            new_skills = (
                current.skills
                if skills is _UNSET
                else (
                    None
                    if skills is None
                    else tuple(self._asset_list(list(skills), "skills"))
                )
            )
            new_knowledge = (
                current.knowledge
                if knowledge is _UNSET
                else (
                    None
                    if knowledge is None
                    else tuple(self._asset_list(list(knowledge), "knowledge"))
                )
            )
            updated = AgentProfile(
                id=current.id,
                name=new_name,
                workspace=current.workspace,
                description=new_description,
                enabled=new_enabled,
                model=new_model,
                bot_type=new_bot_type,
                avatar=new_avatar,
                skills=new_skills,
                knowledge=new_knowledge,
            )
            registry.upsert(updated)
            if not new_enabled:
                registry.set_enabled(agent_id, False)
            if make_default:
                registry.set_default(agent_id)

            profiles = [
                updated.to_dict() if item.id == agent_id else item.to_dict()
                for item in registry.list()
            ]
            candidate = dict(settings)
            candidate["agents"] = profiles
            candidate["default_agent_id"] = registry.default_agent_id
            self._commit(
                {"agents": profiles, "default_agent_id": registry.default_agent_id},
                revision,
            )
            return updated.to_dict()

    def archive_agent(self, agent_id: str, revision: str = None) -> Dict:
        return self.update_agent(agent_id, enabled=False, revision=revision)

    def delete_agent(self, agent_id: str, revision: str = None) -> Dict:
        """Remove an Agent from the roster for good, files and all.

        The default Agent is the instance itself — its workspace is the
        instance root, holding every other Agent and the shared library — so it
        can never be deleted. For anyone else we drop the roster entry, unbind
        any channel instances that pointed at them (so those channels fall back
        to the default Agent rather than routing into the void), and delete
        their own workspace, but only when it is the layout we created
        (``<instance root>/agents/<id>``): a hand-picked path could be anywhere,
        and we will not recursively erase a directory we did not make.
        """
        with self._lock:
            settings = self._load()
            registry = self._registry(settings)
            profile = registry.get(agent_id, require_enabled=False)
            if agent_id == registry.default_agent_id:
                raise AgentAdminError("the default agent cannot be deleted")

            profiles = [
                item.to_dict()
                for item in registry.list()
                if item.id != agent_id
            ]
            # 仍绑定到已删除代理的通道实例会把消息路由进虚空，
            # 因此要清除这些绑定（通道保持运行，并回退到默认代理）。
            instances = []
            for item in (settings.get("channel_instances") or []):
                inst = dict(item)
                if (inst.get("agent_id") or "") == agent_id:
                    inst["agent_id"] = ""
                instances.append(inst)
            candidate = dict(settings)
            candidate["agents"] = profiles
            candidate["channel_instances"] = instances
            candidate["default_agent_id"] = registry.default_agent_id
            # 在写入任何内容之前先校验最终生成的名册。
            self._registry(candidate)
            self._commit(
                {
                    "agents": profiles,
                    "channel_instances": instances,
                    "default_agent_id": registry.default_agent_id,
                },
                revision,
            )

            sanctioned = self._instance_root(settings) / "agents" / agent_id
            workspace = profile.workspace_path
            if workspace == sanctioned and workspace.is_dir():
                shutil.rmtree(workspace, ignore_errors=True)

            # 清理会话偏好存储中仍指向已删除代理的内容：
            # 它自己残留的孤立会话覆盖，以及仍停留在其他会话
            # 团队成员名单中的 ID。这里只做尽力而为——此处的
            # 失败不能撤销已经提交的删除。
            try:
                from agent.workspace import session_prefs

                session_prefs.forget_agent(agent_id)
            except Exception as e:
                logger.warning(f"[AgentAdmin] session prefs cleanup after delete failed: {e}")

            return {"id": agent_id, "deleted": True}

    def knowledge_mode(self, agent_id: str) -> str:
        """Whether this Agent reads the shared knowledge base or its own.

        Derived from the filesystem, not a stored flag, so it can never drift
        from reality (the same "opt out by presence" rule the shared assets use):
        a real ``knowledge/`` directory in the Agent's workspace means "own"; a
        symlink to the shared copy, or nothing at all, means "shared".

        The default Agent owns the instance root, so its ``knowledge/`` *is* the
        shared one — it is always reported as shared and cannot be switched.
        """
        with self._lock:
            settings = self._load()
            registry = self._registry(settings)
            profile = registry.get(agent_id, require_enabled=False)
            return self._knowledge_mode_of(profile, registry.default_agent_id)

    def set_knowledge_mode(self, agent_id: str, mode: str) -> Dict:
        """Switch an Agent between the shared knowledge base and its own.

        ``own``   → give the Agent a real ``knowledge/`` directory so its reads
                    and writes stay private: the base it set aside earlier if
                    there is one, else a fresh one seeded with an empty index.
        ``shared``→ point ``knowledge/`` at the shared copy via a symlink so the
                    Agent both sees and contributes to the common base. Shared is
                    only a reference, so the switch is always allowed: an own
                    base that holds content is set aside (``knowledge.own``)
                    rather than deleted, and comes back on the next switch to
                    ``own``. We never delete a knowledge base implicitly.

        Returns ``{"id", "mode", "changed"}``.
        """
        if mode not in ("shared", "own"):
            raise AgentAdminError("knowledge mode must be 'shared' or 'own'")
        from common import state_dir

        with self._lock:
            settings = self._load()
            registry = self._registry(settings)
            profile = registry.get(agent_id, require_enabled=False)
            if agent_id == registry.default_agent_id:
                raise AgentAdminError(
                    "the default Agent owns the shared knowledge base"
                )
            workspace = profile.workspace_path
            kdir = workspace / "knowledge"
            # 当代理处于“共享”模式时，它自己的知识库被暂存在这里。
            stash = workspace / "knowledge.own"
            # 共享知识库其实就是默认代理的 knowledge/。这里直接定位它，
            # 而不是经由该代理自己的 knowledge/——后者在“own”模式下
            # 指向的正是我们即将删除的那个目录。
            shared = state_dir.shared_root() / "knowledge"

            if mode == "own":
                if kdir.is_dir() and not kdir.is_symlink():
                    return {"id": agent_id, "mode": "own", "changed": False}
                if kdir.is_symlink():
                    kdir.unlink()
                if stash.is_dir():
                    # 这是该代理处于共享模式时暂存下来的自有知识库：
                    # 原样取回，而不是重新从空开始。
                    stash.rename(kdir)
                    return {"id": agent_id, "mode": "own", "changed": True}
                kdir.mkdir(parents=True, exist_ok=True)
                index = kdir / "index.md"
                if not index.exists():
                    index.write_text("# Knowledge Index\n", encoding="utf-8")
                return {"id": agent_id, "mode": "own", "changed": True}

            # 模式为“shared”
            if kdir.is_symlink() or not kdir.exists():
                # 已经共享（或从未建立过）：（重新）把符号链接指向共享库。
                if kdir.is_symlink():
                    kdir.unlink()
                self._link_shared_knowledge(kdir, shared)
                return {"id": agent_id, "mode": "shared", "changed": bool(kdir.exists())}
            # 这里遇到的是一个真实目录，里面放着代理自己的知识库。共享
            # 只是一个引用，所以这个切换总是允许的——但我们绝不会隐式地
            # 删除一个知识库。只有当它没有容纳用户放进去的任何内容时才丢弃
            # （即为空目录，或只有我们建库时写入的索引）；否则把它
            # 暂存到一边，以便切回“own”时能够恢复。
            if self._own_knowledge_is_discardable(kdir):
                shutil.rmtree(kdir)
            else:
                if stash.exists():
                    # 这是从未被取回的暂存目录（说明有人手工重建了
                    # knowledge/）。两者都保留：较旧的那个改名为带
                    # 时间戳的名称，而不是被丢弃。
                    stash.rename(workspace / f"knowledge.own.{int(time.time())}")
                kdir.rename(stash)
            self._link_shared_knowledge(kdir, shared)
            return {"id": agent_id, "mode": "shared", "changed": True}

    @staticmethod
    def _own_knowledge_is_discardable(kdir: Path) -> bool:
        """True when the Agent's own knowledge dir holds nothing worth keeping:
        empty, or only the auto-seeded ``index.md`` left at its seed content."""
        entries = list(kdir.iterdir())
        if not entries:
            return True
        if entries == [kdir / "index.md"]:
            try:
                return kdir.joinpath("index.md").read_text(encoding="utf-8").strip() in (
                    "",
                    "# Knowledge Index",
                )
            except OSError:
                return False
        return False

    @staticmethod
    def _link_shared_knowledge(link_path: Path, shared: Path) -> None:
        """Point an Agent's ``knowledge/`` at the shared base via a symlink so
        cwd-relative reads/writes and the vector scan all land on the shared
        copy. Falls back to leaving nothing (pure fallback resolution) if the
        platform refuses symlinks."""
        try:
            shared.mkdir(parents=True, exist_ok=True)
            link_path.parent.mkdir(parents=True, exist_ok=True)
            link_path.symlink_to(shared, target_is_directory=True)
        except (OSError, NotImplementedError):
            # 若无法建立符号链接，代理仍可经由 Web 控制台中
            # state_dir 的解析回退来读取共享知识库；只是相对 cwd 的
            # 运行时写入会有所不同，这在无符号链接的平台上可以接受。
            pass

    def prune_skill(self, skill_name: str) -> bool:
        """Drop an uninstalled skill's name from every Agent's selection.

        A per-Agent ``skills`` list references shared skills by name. When a
        skill is uninstalled that name becomes dead weight in team.json; this
        removes it so the file self-heals. An Agent that used "all" (no list)
        is untouched, and one whose list empties out keeps an empty list
        (a deliberate "none"), never silently reverting to "all".

        :return: True if any Agent's selection changed.
        """
        if not skill_name:
            return False
        with self._lock:
            settings = self._load()
            raw_agents = settings.get("agents")
            if not raw_agents:
                return False
            changed = False
            new_agents = []
            for item in raw_agents:
                entry = dict(item)
                sel = entry.get("skills")
                if isinstance(sel, list) and skill_name in sel:
                    entry["skills"] = [s for s in sel if s != skill_name]
                    changed = True
                new_agents.append(entry)
            if changed:
                self._commit({"agents": new_agents})
            return changed

    # ------------------------------------------------------------------
    # 核心文件读写
    # ------------------------------------------------------------------
    def _core_path(self, agent_id: str, filename: str) -> Path:
        if filename not in CORE_FILES:
            raise AgentAdminError(f"unsupported core file: {filename}")
        from common import state_dir

        registry = self._registry(self._load())
        workspace = registry.get(agent_id, require_enabled=False).workspace_path.resolve()
        # 用 state_dir 解析而非直接 join，这样即使 MEMORY.md
        # 被移动到每个用户各自的目录下，控制台编辑的也是
        # 代理实际读取的那一份。
        if filename == "MEMORY.md":
            path = Path(state_dir.memory_file(base=workspace)).resolve()
        else:
            path = (workspace / filename).resolve()
        if path != workspace / filename and not _is_strictly_within(path, workspace):
            raise AgentAdminError("core file escapes the agent workspace")
        return path

    def read_core_file(self, agent_id: str, filename: str) -> Dict:
        with self._lock:
            path = self._core_path(agent_id, filename)
            raw = path.read_bytes() if path.exists() else b""
            return {
                "filename": filename,
                "content": raw.decode("utf-8"),
                "revision": _revision(raw),
                "exists": path.exists(),
            }

    def write_core_file(
        self, agent_id: str, filename: str, content: str, revision: str
    ) -> Dict:
        if not isinstance(content, str):
            raise AgentAdminError("content must be a string")
        raw = content.encode("utf-8")
        if len(raw) > MAX_CORE_FILE_BYTES:
            raise AgentAdminError("core file exceeds 1 MiB")
        with self._lock:
            path = self._core_path(agent_id, filename)
            current = path.read_bytes() if path.exists() else b""
            current_revision = _revision(current)
            if revision != current_revision:
                raise StaleAgentFileError(
                    "core file changed since it was loaded; refresh before saving"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{filename}.", suffix=".tmp", dir=str(path.parent)
            )
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, path)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
            return {
                "filename": filename,
                "content": content,
                "revision": _revision(raw),
                "exists": True,
            }


def get_agent_admin_service() -> "AgentAdminService":
    """Build a service pointed at the instance's standard config location.

    A single helper so callers outside the web layer (the CLI plugin, cloud
    client, …) don't each re-derive the ``config.json`` path.
    """
    from config import get_data_root

    return AgentAdminService(os.path.join(get_data_root(), "config.json"))
