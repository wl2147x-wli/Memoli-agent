"""
Memory configuration module

Provides global memory configuration with simplified workspace structure
"""

from __future__ import annotations
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path


def _default_workspace():
    """
    Resolve the workspace of the routed Agent. Deferring to state_dir keeps
    every consumer of get_default_memory_config() - ConversationStore, the
    evolution executor, the evolution-undo tool - on the right workspace
    without each entrypoint having to prime the singleton.
    """
    from common.state_dir import state_root_str
    return state_root_str()


@dataclass
class MemoryConfig:
    """Configuration for memory storage and search"""
    
    # 存储路径（默认：~/cow）
    workspace_root: str = field(default_factory=_default_workspace)
    
    # 嵌入配置
    embedding_provider: str = "openai"  # 嵌入供应商标识，可用值见 EMBEDDING_VENDORS
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    
    # 分块配置
    chunk_max_tokens: int = 500
    chunk_overlap_tokens: int = 50
    
    # 搜索配置
    max_results: int = 10
    min_score: float = 0.1
    
    # 混合搜索权重
    vector_weight: float = 0.7
    keyword_weight: float = 0.3
    
    # 内存来源
    sources: List[str] = field(default_factory=lambda: ["memory", "session"])
    
    # 同步配置
    enable_auto_sync: bool = True
    sync_on_search: bool = True
    
    
    def get_workspace(self) -> Path:
        """Get workspace root directory"""
        return Path(self.workspace_root)

    def get_memory_dir(self) -> Path:
        """Get memory files directory"""
        from common import state_dir
        return state_dir.memory_dir(base=self.workspace_root)

    def get_db_path(self) -> Path:
        """Get SQLite database path for long-term memory index"""
        from common import state_dir
        return state_dir.memory_index_db(base=self.workspace_root)

    def get_skills_dir(self) -> Path:
        """Get skills directory"""
        from common import state_dir
        return state_dir.skills_dir(base=self.workspace_root)


# 每个工作区一份配置，而不是每个进程一份：多个代理会共享本
# 模块，而读取它的消费者并不接收 config= 参数
# （ConversationStore、进化执行器、进化撤销工具、记忆管理器）。
# 若只保留单个槽位，最后初始化的 Agent 就会
# 决定其它所有 Agent 的内存写入位置。
_memory_configs: Dict[str, MemoryConfig] = {}
_pinned_memory_config: Optional[MemoryConfig] = None
_memory_config_lock = threading.RLock()


def _key(workspace_root: str) -> str:
    """Canonicalize so a registration and a lookup for the same directory
    agree. ``~/cow``, ``/var/...`` and ``/private/var/...`` all reach the same
    place; keying on the raw string would silently miss the registered config
    and hand back a bare default instead."""
    import os
    from common.utils import expand_path

    return os.path.realpath(expand_path(str(workspace_root)))


def get_default_memory_config() -> MemoryConfig:
    """Config for the workspace this call belongs to, per the routed identity.

    Returns the instance registered by that Agent's initializer when there is
    one, so callers see its embedding settings and not just a bare default.
    """
    if _pinned_memory_config is not None:
        return _pinned_memory_config

    workspace_root = _default_workspace()
    key = _key(workspace_root)
    config = _memory_configs.get(key)
    if config is not None:
        return config
    with _memory_config_lock:
        config = _memory_configs.get(key)
        if config is None:
            config = MemoryConfig(workspace_root=workspace_root)
            _memory_configs[key] = config
        return config


def register_memory_config(config: MemoryConfig) -> None:
    """Publish an Agent's config as the default for its own workspace.

    What an initializer wants: the fully built config (embedding provider and
    all) reaches this Agent's config-less consumers, without touching what any
    other Agent resolves.
    """
    with _memory_config_lock:
        _memory_configs[_key(config.workspace_root)] = config


def reset_memory_configs() -> None:
    """Drop every registered config and any pin. For tests."""
    global _pinned_memory_config
    with _memory_config_lock:
        _memory_configs.clear()
        _pinned_memory_config = None


def set_global_memory_config(config: Optional[MemoryConfig]) -> None:
    """Force every workspace to one config; pass None to follow routing again.

    A blunt instrument, kept for tests and single-Agent callers that want to
    override embedding or search settings process-wide. Prefer
    register_memory_config in anything that runs per Agent.
    """
    global _pinned_memory_config
    with _memory_config_lock:
        _pinned_memory_config = config
