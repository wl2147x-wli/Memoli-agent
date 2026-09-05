import importlib
import importlib.util
import threading
from pathlib import Path
from typing import Dict, Any, Type
from agent.tools.base_tool import BaseTool
from common.log import logger
from config import conf


def _normalize_mcp_configs(raw) -> list:
    """
    Convert MCP server config to internal list format.
    Supports:
      - list format (mcp_servers):  [{"name": "x", "type": "stdio", ...}]
      - dict format (mcpServers):   {"x": {"command": "npx", ...}}
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        result = []
        for name, cfg in raw.items():
            entry = {"name": name, **cfg}
            if "type" not in entry:
                entry["type"] = "sse" if "url" in entry else "stdio"
            result.append(entry)
        return result
    return []


class ToolManager:
    """
    Tool manager for managing tools.

    One instance per Agent workspace. Not a plain singleton: the instance
    caches booted MCP subprocesses so that per-session agent init does not
    re-fork them, and each workspace has its own ``mcp.json``. A single
    process-wide instance would let the first Agent to start decide which MCP
    servers exist, hand its tools (and their credentials) to every other
    Agent, and leave their own servers permanently unloaded.
    """
    _instances: Dict[str, "ToolManager"] = {}
    _instances_lock = threading.Lock()

    def __new__(cls):
        from common.state_dir import real_state_root

        key = real_state_root()
        instance = cls._instances.get(key)
        if instance is not None:
            return instance
        with cls._instances_lock:
            instance = cls._instances.get(key)
            if instance is None:
                instance = super(ToolManager, cls).__new__(cls)
                instance.workspace_root = key
                instance.tool_classes = {}  # 存储工具类而不是实例
                instance._initialized = False
                cls._instances[key] = instance
            return instance

    @classmethod
    def instances(cls) -> list:
        """Every ToolManager built so far, for process-wide operations."""
        with cls._instances_lock:
            return list(cls._instances.values())

    @classmethod
    def reset_instances(cls) -> None:
        """Drop every cached instance. For tests."""
        with cls._instances_lock:
            cls._instances.clear()

    def __init__(self):
        # 每次调用 ToolManager() 时都会执行，包括拿到的是缓存实例的情况，
        # 因此每个字段都会被正确初始化。
        if not hasattr(self, 'tool_classes'):
            self.tool_classes = {}  # 存储工具类的字典
        if not hasattr(self, '_mcp_registry'):
            self._mcp_registry = None  # 延迟初始化：仅在配置 MCP 服务器时创建
        if not hasattr(self, '_mcp_tool_instances'):
            self._mcp_tool_instances: dict = {}  # tool_name -> McpTool 实例
        if not hasattr(self, '_mcp_lock'):
            # 防止并发调用者破坏 _mcp_loaded 的“先检查再赋值”流程，
            # 以免触发重复的后台加载器。
            self._mcp_lock = threading.Lock()
        if not hasattr(self, '_mcp_loaded'):
            # 幂等标志：第一个加载器在 _mcp_lock 内同步派发时置为 True，
            # 之后的 _load_mcp_tools() 调用都会变成空操作，
            # 因此每个会话的代理初始化都不会重新分叉 MCP 子进程。
            self._mcp_loaded = False
        if not hasattr(self, '_mcp_status'):
            # server_name -> “pending”/“ready”/“failed”
            # 异步加载期间供 UI 展示和内省参考。
            self._mcp_status: dict = {}
        if not hasattr(self, '_mcp_signature'):
            # 上次加载的 mcp.json 的 (mtime, sha256)。
            # refresh_mcp_if_changed() 据此判断：文件没有任何变化时就跳过重新解析。
            self._mcp_signature: tuple = (None, None)
        if not hasattr(self, '_mcp_active_configs'):
            # server_name -> 规范化配置字典，用于基于差异的重新加载。
            self._mcp_active_configs: dict = {}
        if not hasattr(self, '_mcp_tool_vectors'):
            # mcp_tool_name -> 嵌入向量，供按需工具检索使用。
            # 在首次检索时才惰性填充，因此没有启用该功能的用户
            # 不会产生任何嵌入成本。
            self._mcp_tool_vectors: dict = {}
        if not hasattr(self, '_mcp_vector_lock'):
            # 保护增量索引的构建，避免并发轮次把同一批
            # 新加载的 MCP 工具重复嵌入。
            self._mcp_vector_lock = threading.Lock()
        if not hasattr(self, '_embedding_provider_initialized'):
            # 嵌入提供方只惰性创建一次，供工具索引与每次查询嵌入复用。
            # None 表示仅关键字模式（未配置提供方），
            # 此时检索会回退为向调用方完整注入。
            self._embedding_provider_initialized = False
            self._embedding_provider = None

    def load_tools(self, tools_dir: str = "", config_dict=None):
        """
        Load tools from both directory and configuration.

        :param tools_dir: Directory to scan for tool modules
        """
        if tools_dir:
            self._load_tools_from_directory(tools_dir)
            self._configure_tools_from_config()
        else:
            self._load_tools_from_init()
            self._configure_tools_from_config(config_dict)

        self._load_mcp_tools()

    def _load_tools_from_init(self) -> bool:
        """
        Load tool classes from tools.__init__.__all__

        :return: True if tools were loaded, False otherwise
        """
        try:
            # 尝试导入工具包
            tools_package = importlib.import_module("agent.tools")

            # 检查 __all__ 是否已定义
            if hasattr(tools_package, "__all__"):
                tool_classes = tools_package.__all__

                # 直接从工具包导入各个工具类
                for class_name in tool_classes:
                    try:
                        # 跳过基础类
                        if class_name in ["BaseTool", "ToolManager"]:
                            continue

                        # 直接从工具包中获取类
                        if hasattr(tools_package, class_name):
                            cls = getattr(tools_package, class_name)

                            if (
                                    isinstance(cls, type)
                                    and issubclass(cls, BaseTool)
                                    and cls != BaseTool
                            ):
                                try:
                                    # 跳过需要特殊初始化的工具
                                    if class_name in ["MemorySearchTool", "MemoryGetTool"]:
                                        logger.debug(f"Skipped tool {class_name} (requires memory_manager)")
                                        continue
                                    # McpTool实例通过_load_mcp_tools()动态注册
                                    if class_name == "McpTool":
                                        logger.debug(f"Skipped tool {class_name} (registered dynamically via mcp_servers config)")
                                        continue
                                    
                                    # 创建一个临时实例来获取名称
                                    temp_instance = cls()
                                    tool_name = temp_instance.name
                                    # 存储类，而不是实例
                                    self.tool_classes[tool_name] = cls
                                    logger.debug(f"Loaded tool: {tool_name} from class {class_name}")
                                except ImportError as e:
                                    # 用明确的提示信息处理缺失依赖的情况
                                    error_msg = str(e)
                                    if "markdownify" in error_msg:
                                        logger.warning(
                                            f"[ToolManager] {cls.__name__} not loaded - missing markdownify.\n"
                                            f"  Install with: pip install markdownify"
                                        )
                                    else:
                                        logger.warning(f"[ToolManager] {cls.__name__} not loaded due to missing dependency: {error_msg}")
                                except Exception as e:
                                    logger.error(f"Error initializing tool class {cls.__name__}: {e}")
                    except Exception as e:
                        logger.error(f"Error importing class {class_name}: {e}")

                return len(self.tool_classes) > 0
            return False
        except ImportError:
            logger.warning("Could not import agent.tools package")
            return False
        except Exception as e:
            logger.error(f"Error loading tools from __init__.__all__: {e}")
            return False

    def _load_tools_from_directory(self, tools_dir: str):
        """Dynamically load tool classes from directory"""
        tools_path = Path(tools_dir)

        # 遍历所有.py文件
        for py_file in tools_path.rglob("*.py"):
            # 跳过初始化文件和基础工具文件
            if py_file.name in ["__init__.py", "base_tool.py", "tool_manager.py"]:
                continue

            # 获取模块名称
            module_name = py_file.stem

            try:
                # 直接从文件加载模块
                spec = importlib.util.spec_from_file_location(module_name, py_file)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)

                    # 查找模块中的工具类
                    for attr_name in dir(module):
                        cls = getattr(module, attr_name)
                        if (
                                isinstance(cls, type)
                                and issubclass(cls, BaseTool)
                                and cls != BaseTool
                        ):
                            try:
                                # 跳过内存工具（它们需要使用内存管理器进行特殊初始化）
                                if attr_name in ["MemorySearchTool", "MemoryGetTool"]:
                                    logger.debug(f"Skipped tool {attr_name} (requires memory_manager)")
                                    continue
                                
                                # 创建一个临时实例来获取名称
                                temp_instance = cls()
                                tool_name = temp_instance.name
                                # 存储类，而不是实例
                                self.tool_classes[tool_name] = cls
                            except ImportError as e:
                                # 用明确的提示信息处理缺失依赖的情况
                                error_msg = str(e)
                                if "markdownify" in error_msg:
                                    logger.warning(
                                        f"[ToolManager] {cls.__name__} not loaded - missing markdownify.\n"
                                        f"  Install with: pip install markdownify"
                                    )
                                else:
                                    logger.warning(f"[ToolManager] {cls.__name__} not loaded due to missing dependency: {error_msg}")
                            except Exception as e:
                                logger.error(f"Error initializing tool class {cls.__name__}: {e}")
            except Exception as e:
                print(f"Error importing module {py_file}: {e}")

    def _configure_tools_from_config(self, config_dict=None):
        """Configure tool classes based on configuration file"""
        try:
            # 获取工具配置
            tools_config = config_dict or conf().get("tools", {})

            # 记录已配置但未加载的工具
            missing_tools = []

            # 存储配置供以后实例化时使用
            self.tool_configs = tools_config

            # 检查缺少哪些已配置的工具
            for tool_name in tools_config:
                if tool_name not in self.tool_classes:
                    missing_tools.append(tool_name)

            # 如果缺少工具，记录警告
            if missing_tools:
                for tool_name in missing_tools:
                    if tool_name == "google_search":
                        logger.warning(
                            f"[ToolManager] Google Search tool is configured but may need API key.\n"
                            f"  Get API key from: https://serper.dev\n"
                            f"  Configure in config.json: tools.google_search.api_key"
                        )
                    else:
                        logger.warning(f"[ToolManager] Tool '{tool_name}' is configured but could not be loaded.")

        except Exception as e:
            logger.error(f"Error configuring tools from config: {e}")

    def _mcp_json_path(self) -> str:
        # 锚定到创建本实例的工作区，而不是锚定到环境身份：
        # MCP 的加载与刷新都跑在后台线程里，这些线程不携带身份，
        # 否则它们会去读取默认代理的 mcp.json。
        from common.state_dir import mcp_config_file
        return str(mcp_config_file(base=self.workspace_root))

    def _read_mcp_json_signature(self):
        """
        Return (mtime, sha256_of_bytes) for ~/cow/mcp.json without parsing.
        Returns (None, None) if the file doesn't exist or is unreadable.
        Cheap enough (one stat + one small read) to call on every agent init.
        """
        import os
        import hashlib
        path = self._mcp_json_path()
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return (None, None)
        try:
            with open(path, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            return (mtime, None)
        return (mtime, digest)

    def _load_mcp_configs(self) -> list:
        """
        Load MCP server configs with priority:
          1. ~/cow/mcp.json  (supports both mcpServers and mcp_servers keys)
          2. config.json mcp_servers field (fallback)
        """
        import os
        import json as _json

        mcp_json_path = self._mcp_json_path()

        if os.path.exists(mcp_json_path):
            try:
                with open(mcp_json_path, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                raw = data.get("mcpServers") or data.get("mcp_servers") or data
                # 调试：N 个代理共享同一个 mcp.json 时会触发 N 次；
                # 真正的启动过程只会记录一次（见下面的 INFO 日志）。
                logger.debug(f"[ToolManager] Loading MCP config from {mcp_json_path}")
                return _normalize_mcp_configs(raw)
            except Exception as e:
                logger.warning(f"[ToolManager] Failed to read {mcp_json_path}: {e}, falling back to config.json")

        raw = conf().get("mcp_servers", [])
        return _normalize_mcp_configs(raw)

    def _load_mcp_tools(self):
        """
        Trigger MCP tool loading in a background thread (idempotent).

        Returns immediately. Booting MCP servers (npx, uvx, etc.) takes
        seconds to tens of seconds on first run, which would otherwise
        block agent initialization and the user's first message.
        Built-in tools work fine without MCP, so we let the agent serve
        traffic right away and let MCP servers come online in the
        background. Per-session agents read a snapshot of whatever is
        ready at construction time and gracefully ignore the rest.
        """
        with self._mcp_lock:
            if self._mcp_loaded:
                return
            mcp_servers_config = self._load_mcp_configs()
            # 现在就拍下签名快照，将来当磁盘内容没有变化时，
            # refresh_mcp_if_changed() 调用就能直接短路返回。
            self._mcp_signature = self._read_mcp_json_signature()
            self._mcp_active_configs = {
                cfg.get("name", "<unnamed>"): cfg for cfg in mcp_servers_config
            }
            if not mcp_servers_config:
                # 即使没有需要加载的内容，也把状态标成已加载，
                # 以免每次调用时都重新读取配置文件。
                self._mcp_loaded = True
                return

            # 先立刻标记为 pending，让 list_mcp_status() 的调用者看到
            # 正在加载中的状态，而不是空字典。
            for cfg in mcp_servers_config:
                name = cfg.get("name", "<unnamed>")
                self._mcp_status[name] = "pending"

            self._mcp_loaded = True
            threading.Thread(
                target=self._load_mcp_tools_async,
                args=(mcp_servers_config,),
                daemon=True,
                name="mcp-loader",
            ).start()
            # DEBUG：每个代理各触发一次；当多个代理共享同一个 mcp.json 时
            # 这只是噪音。真正把服务器启动起来的日志在 INFO 级别。
            logger.debug(
                f"[ToolManager] MCP loading started in background "
                f"({len(mcp_servers_config)} server(s) configured)"
            )

    def refresh_mcp_if_changed(self):
        """
        Cheap check whether ~/cow/mcp.json has changed since last load.
        If it has, do a diff-based reload: start newly added servers,
        shut down removed ones, and restart any whose config was edited.
        Untouched servers are left running.

        Designed to be called on every agent creation. The fast path is
        a single os.stat() — completely free when nothing has changed.
        """
        with self._mcp_lock:
            new_sig = self._read_mcp_json_signature()
            if new_sig == self._mcp_signature:
                return  # 没有变化，直接空操作返回的快速路径

            try:
                new_configs = self._load_mcp_configs()
            except Exception as e:
                logger.warning(f"[ToolManager] MCP reload — failed to parse config: {e}")
                return

            new_by_name = {
                cfg.get("name", "<unnamed>"): cfg for cfg in new_configs
            }
            old_by_name = self._mcp_active_configs

            added = [n for n in new_by_name if n not in old_by_name]
            removed = [n for n in old_by_name if n not in new_by_name]
            changed = [
                n for n in new_by_name
                if n in old_by_name and new_by_name[n] != old_by_name[n]
            ]

            if not (added or removed or changed):
                # 签名虽然变了，但内容在逻辑上并无差别
                # （例如用户只是重新保存了文件而没有修改）。只需同步签名即可。
                self._mcp_signature = new_sig
                return

            logger.info(
                f"[ToolManager] mcp.json changed — "
                f"adding={added}, removing={removed}, restarting={changed}"
            )

            # 先停掉被移除的服务器和配置有变更的服务器（有变更的稍后会重新启动）
            for name in removed + changed:
                self._teardown_mcp_server(name)

            # 在后台启动新添加的以及配置有变更的服务器
            to_start = [new_by_name[n] for n in added + changed]
            if to_start:
                for cfg in to_start:
                    self._mcp_status[cfg.get("name", "<unnamed>")] = "pending"
                threading.Thread(
                    target=self._load_mcp_tools_async,
                    args=(to_start,),
                    daemon=True,
                    name="mcp-loader-reload",
                ).start()

            self._mcp_active_configs = new_by_name
            self._mcp_signature = new_sig

    def _teardown_mcp_server(self, server_name: str):
        """Shut down one MCP server and drop its tools from the registry."""
        if self._mcp_registry is None:
            return
        client = None
        with self._mcp_registry._registry_lock:
            client = self._mcp_registry._clients.pop(server_name, None)
        if client is not None:
            # 该客户端可能被共享同一个 mcp.json 的其他代理所复用。
            # 删除池中匹配的条目，这样稍后重新加载时会启动全新的子进程，
            # 而不会把正在被我们停掉的子进程继续分发出去。
            try:
                pool = self._mcp_registry._shared_pool
                with self._mcp_registry._shared_pool_lock:
                    for k in [k for k, v in pool.items() if v is client]:
                        pool.pop(k, None)
            except Exception:
                pass
            try:
                client.shutdown()
            except Exception as e:
                logger.warning(f"[MCP] Error shutting down '{server_name}': {e}")
        # 删除属于该服务器的工具。
        for tool_name in list(self._mcp_tool_instances.keys()):
            tool = self._mcp_tool_instances.get(tool_name)
            if tool is not None and getattr(tool, "server_name", None) == server_name:
                self._mcp_tool_instances.pop(tool_name, None)
        self._mcp_status.pop(server_name, None)

    def _load_mcp_tools_async(self, mcp_servers_config):
        """
        Background worker: bring up each MCP server one-by-one and
        publish ready tools to _mcp_tool_instances as they come online.

        Server failures are isolated — one bad server cannot block
        the others, and never raises out of the worker thread.
        """
        try:
            from agent.tools.mcp.mcp_client import McpClient, McpClientRegistry, set_reload_callback
            from agent.tools.mcp.mcp_tool import McpTool

            registry = McpClientRegistry()
            self._mcp_registry = registry
            # 让 OAuth 网页回调在用户完成授权后使服务器重新上线。
            set_reload_callback(self.reload_mcp_server)

            mcp_json_path = self._mcp_json_path()

            booted_any = False
            for cfg in mcp_servers_config:
                server_name = cfg.get("name", "<unnamed>")
                try:
                    # 复用那些从*同一个* mcp.json、以*相同*配置启动的子进程，
                    # 这样多个代理共享一个 mcp.json 时，
                    # 不会为每台服务器各起一份自己的副本。
                    # 启动过程按服务器名串行化，因此并发加载线程
                    # 即使在同一台服务器上竞争，最终也会共享同一个子进程。
                    share_key = registry.shared_key(mcp_json_path, server_name, cfg)
                    boot_failure = {}

                    def _boot():
                        c = McpClient(cfg)
                        if c.initialize():
                            return c
                        boot_failure["needs_auth"] = getattr(c, "needs_auth", False)
                        return None

                    client, reused = registry.get_or_boot_shared(share_key, _boot)
                    if client is None:
                        if boot_failure.get("needs_auth"):
                            self._mcp_status[server_name] = "needs_auth"
                            logger.info(
                                f"[MCP] Server '{server_name}' needs authorization — "
                                f"waiting for the user to complete the OAuth flow"
                            )
                        else:
                            self._mcp_status[server_name] = "failed"
                            logger.warning(
                                f"[MCP] Server '{server_name}' failed to initialize — skipping"
                            )
                        continue

                    tool_schemas = client.list_tools()
                    added = []
                    for schema in tool_schemas:
                        tool_name = schema.get("name", "")
                        if not tool_name:
                            continue
                        mcp_tool = McpTool(client, schema, server_name)
                        # 单条字典赋值在 GIL 下是原子的、安全的；读取方
                        # 通过 list() 快照来迭代，以避免并发修改。
                        self._mcp_tool_instances[tool_name] = mcp_tool
                        added.append(tool_name)

                    # 工具只有在客户端注册进共享注册表之后才对外可见，
                    # 因此调用方永远不会看到一个加载到一半的服务器。
                    with registry._registry_lock:
                        registry._clients[server_name] = client
                    self._mcp_status[server_name] = "ready"
                    if reused:
                        # 本代理只是挂接到了一个被复用的共享子进程上，静默记录即可，
                        # 这样共享同一个 mcp.json 的 N 个代理就不会重复打印这一行。
                        logger.debug(
                            f"[MCP] Server '{server_name}' reused — "
                            f"{len(added)} tool(s) attached"
                        )
                    else:
                        booted_any = True
                        logger.info(
                            f"[MCP] Server '{server_name}' ready — "
                            f"{len(added)} tool(s): {added}"
                        )
                except Exception as e:
                    self._mcp_status[server_name] = "failed"
                    logger.warning(f"[MCP] Server '{server_name}' load failed: {e}")

            ready = sum(1 for s in self._mcp_status.values() if s == "ready")
            total = len(self._mcp_status)
            # 只有本加载器确实启动过服务器时，才在 INFO 级别打印汇总。
            # 若共享池中的服务器全部是被复用的（第 2 到第 N 个代理
            # 共享同一个 mcp.json 的常见情形），就保持在 DEBUG 级别，
            # 避免出现 N 条相同的“加载完成”日志。
            _complete_log = logger.info if booted_any else logger.debug
            _complete_log(
                f"[ToolManager] MCP loading complete: "
                f"{ready}/{total} server(s) ready, "
                f"{len(self._mcp_tool_instances)} tool(s) available"
            )
        except Exception as e:
            logger.warning(f"[ToolManager] MCP background loader crashed: {e}")

    def reload_mcp_server(self, server_name: str) -> None:
        """Re-initialize a single MCP server (e.g. after OAuth authorization).

        Tears down any existing client for the server and starts it again in
        the background, so a freshly-stored access token is picked up and the
        server's tools become available on the next message.
        """
        with self._mcp_lock:
            cfg = self._mcp_active_configs.get(server_name)
        if not cfg:
            logger.warning(f"[MCP] reload requested for unknown server '{server_name}'")
            return
        logger.info(f"[MCP] Reloading server '{server_name}' after authorization")
        self._teardown_mcp_server(server_name)
        self._mcp_status[server_name] = "pending"
        threading.Thread(
            target=self._load_mcp_tools_async,
            args=([cfg],),
            daemon=True,
            name=f"mcp-reload-{server_name}",
        ).start()

    def list_mcp_status(self) -> dict:
        """Return {server_name: status} snapshot for UI / debugging."""
        return dict(self._mcp_status)

    def sync_mcp_into_agent(self, agent) -> tuple:
        """
        Reconcile a live agent's tool collection with the current MCP tool registry.

        Adds tools that finished loading after the agent was created,
        and removes tools whose MCP server was torn down. Built-in tools
        on the agent are left untouched.

        Handles both representations CowAgent uses:
          - Agent.tools: list[BaseTool]               (default Agent class)
          - AgentStream.tools: dict[str, BaseTool]    (streaming agent)

        Returns (added_names, removed_names) for logging.
        """
        if agent is None or not hasattr(agent, "tools"):
            return ([], [])

        # 绝不要把 MCP 工具重新注入受限的 Self-Evolution 审查代理。
        # 审查代理配备的是刻意裁剪过、并受工作区保护的工具集；
        # 如果在这里悄悄把配置好的 MCP 工具再加回去，就会绕过这条
        # 策略边界（参见 agent/evolution/executor.py）。该标志可能位于
        # 代理自身（Agent）上，也可能位于包裹流式执行器的 .agent 上。
        if getattr(agent, "_evolution_restricted", False) or getattr(
            getattr(agent, "agent", None), "_evolution_restricted", False
        ):
            return ([], [])

        from agent.tools.mcp.mcp_tool import McpTool
        current = self._mcp_tool_instances
        registry_names = set(current.keys())

        agent_tools = agent.tools

        if isinstance(agent_tools, dict):
            agent_mcp_names = {
                name for name, tool in agent_tools.items()
                if isinstance(tool, McpTool)
            }
            added = registry_names - agent_mcp_names
            removed = agent_mcp_names - registry_names
            if not (added or removed):
                return ([], [])
            for name in added:
                agent_tools[name] = current[name]
            for name in removed:
                agent_tools.pop(name, None)

        elif isinstance(agent_tools, list):
            agent_mcp_names = {
                t.name for t in agent_tools if isinstance(t, McpTool)
            }
            added = registry_names - agent_mcp_names
            removed = agent_mcp_names - registry_names
            if not (added or removed):
                return ([], [])
            if removed:
                agent.tools = [
                    t for t in agent_tools
                    if not (isinstance(t, McpTool) and t.name in removed)
                ]
            for name in added:
                agent.tools.append(current[name])

        else:
            return ([], [])

        return (sorted(added), sorted(removed))

    # ------------------------------------------------------------------
    # 按需 MCP 工具检索支持
    #
    # 向量索引与嵌入提供方都由这里持有（单例、进程级，
    # 生命周期与 MCP 工具保持一致）。上下文感知的挑选逻辑本身
    # 位于 agent.tools.mcp.tool_retrieval，因为执行器才是
    # 唯一知道对话上下文的地方。
    # ------------------------------------------------------------------

    def count_mcp_tools(self) -> int:
        """Return the number of currently loaded MCP tools."""
        return len(self._mcp_tool_instances)

    def get_mcp_tool_vectors(self) -> dict:
        """Return ``{mcp_tool_name: vector}`` for currently loaded MCP tools.

        Lazily embeds any MCP tools not yet in the cache (MCP servers load
        asynchronously, so tools may appear over time). Returns an empty dict
        when no embedding provider is available or embedding fails — the caller
        then falls back to full injection. Never raises.
        """
        try:
            self._ensure_mcp_tool_vectors()
        except Exception as e:
            logger.debug(f"[ToolManager] MCP tool vector build skipped: {e}")
        return dict(self._mcp_tool_vectors)

    def embed_query(self, text: str):
        """Embed a retrieval query with the shared provider.

        Returns the embedding vector, or None if no provider is available or
        the call fails (caller falls back to full injection). Never raises.
        """
        if not text:
            return None
        provider = self._get_embedding_provider()
        if provider is None:
            return None
        try:
            return provider.embed_query(text)
        except Exception as e:
            logger.debug(f"[ToolManager] query embedding failed: {e}")
            return None

    def _ensure_mcp_tool_vectors(self) -> None:
        """Incrementally embed MCP tools that are not yet cached."""
        # 先取快照，避免异步加载器运行期间发生并发修改。
        current = dict(self._mcp_tool_instances)
        missing = [name for name in current if name not in self._mcp_tool_vectors]
        if not missing:
            return

        provider = self._get_embedding_provider()
        if provider is None:
            return

        with self._mcp_vector_lock:
            # 持锁后重新检查：另一个线程可能已经把这些向量填充好了。
            missing = [name for name in current if name not in self._mcp_tool_vectors]
            if not missing:
                return
            texts = [self._mcp_tool_embed_text(current[name]) for name in missing]
            vectors = provider.embed_batch(texts)
            for name, vec in zip(missing, vectors):
                self._mcp_tool_vectors[name] = vec

    @staticmethod
    def _mcp_tool_embed_text(tool) -> str:
        """Build the text that represents an MCP tool for embedding."""
        name = getattr(tool, "name", "") or ""
        description = getattr(tool, "description", "") or ""
        return f"{name}: {description}".strip()

    def _get_embedding_provider(self):
        """Lazily create and cache the shared embedding provider (or None)."""
        if not self._embedding_provider_initialized:
            try:
                from agent.memory.embedding import create_default_embedding_provider
                self._embedding_provider = create_default_embedding_provider()
            except Exception as e:
                logger.warning(f"[ToolManager] embedding provider init failed: {e}")
                self._embedding_provider = None
            self._embedding_provider_initialized = True
        return self._embedding_provider

    def create_tool(self, name: str) -> BaseTool:
        """
        Get a new instance of a tool by name.

        :param name: The name of the tool to get.
        :return: A new instance of the tool or None if not found.
        """
        tool_class = self.tool_classes.get(name)
        if tool_class:
            # 创建一个新实例
            tool_instance = tool_class()

            # 应用配置（如果可用）
            if hasattr(self, 'tool_configs') and name in self.tool_configs:
                tool_instance.config = self.tool_configs[name]

            return tool_instance

        # 回退到 MCP 工具实例
        mcp_tool = self._mcp_tool_instances.get(name)
        if mcp_tool:
            return mcp_tool

        return None

    def list_tools(self) -> dict:
        """
        Get information about all loaded tools.

        :return: A dictionary with tool information.
        """
        result = {}
        for name, tool_class in self.tool_classes.items():
            # 创建一个临时实例来获取架构
            temp_instance = tool_class()
            result[name] = {
                "description": temp_instance.description,
                "parameters": temp_instance.get_json_schema()
            }

        # 包括 MCP 工具实例
        for name, mcp_tool in self._mcp_tool_instances.items():
            result[name] = {
                "description": mcp_tool.description,
                "parameters": mcp_tool.params,
            }

        return result

    def shutdown_mcp(self):
        """Shut down all MCP server clients."""
        if self._mcp_registry:
            self._mcp_registry.shutdown_all()
