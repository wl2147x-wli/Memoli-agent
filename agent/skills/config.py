"""
Configuration support for skills.
"""

import json
import os
import platform
from typing import Dict, Optional, List
from agent.skills.types import SkillEntry


# 这类技能的 anyEnv 要求，也可以由 OpenAI 兼容的自定义
# 提供商来满足（启动时把其配置导出到下面的环境变量）。
# 若不这样做，仅选用自定义厂商（没有内置的 *_API_KEY）时，
# 该技能会被误判为“未配置”。
_CUSTOM_PROVIDER_ENV_BY_SKILL = {
    "image-generation": "SKILL_IMAGE_GENERATION_CUSTOM_PROVIDER",
}


def has_custom_provider(skill_name: str) -> bool:
    """Whether the skill has a usable custom provider configured via env.

    The provider payload is injected as JSON and is considered usable only
    when it carries both an api_key and api_base.
    """
    env_name = _CUSTOM_PROVIDER_ENV_BY_SKILL.get(skill_name)
    if not env_name:
        return False
    raw = os.environ.get(env_name)
    if not raw or not raw.strip():
        return False
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    return bool((payload.get("api_key") or "").strip()) and bool(
        (payload.get("api_base") or "").strip()
    )


def resolve_runtime_platform() -> str:
    """Get the current runtime platform."""
    return platform.system().lower()


def has_binary(bin_name: str) -> bool:
    """
    Check if a binary is available in PATH.
    
    :param bin_name: Binary name to check
    :return: True if binary is available
    """
    import shutil
    return shutil.which(bin_name) is not None


def has_any_binary(bin_names: List[str]) -> bool:
    """
    Check if any of the given binaries is available.
    
    :param bin_names: List of binary names to check
    :return: True if at least one binary is available
    """
    return any(has_binary(bin_name) for bin_name in bin_names)


def has_env_var(env_name: str) -> bool:
    """
    Check if an environment variable is set.
    
    :param env_name: Environment variable name
    :return: True if environment variable is set
    """
    return env_name in os.environ and bool(os.environ[env_name].strip())


def get_skill_config(config: Optional[Dict], skill_name: str) -> Optional[Dict]:
    """
    Get skill-specific configuration.
    
    :param config: Global configuration dictionary
    :param skill_name: Name of the skill
    :return: Skill configuration or None
    """
    if not config:
        return None
    
    skills_config = config.get('skills', {})
    if not isinstance(skills_config, dict):
        return None
    
    entries = skills_config.get('entries', {})
    if not isinstance(entries, dict):
        return None
    
    return entries.get(skill_name)


def should_include_skill(
    entry: SkillEntry,
    config: Optional[Dict] = None,
    current_platform: Optional[str] = None,
) -> bool:
    """
    Determine if a skill should be included based on requirements.
    
    Simple rule: Skills are auto-enabled if their requirements are met.
    - Has required API keys → enabled
    - Missing API keys → disabled
    - Wrong keys → enabled but will fail at runtime (LLM will handle error)
    
    :param entry: SkillEntry to check
    :param config: Configuration dictionary (currently unused, reserved for future)
    :param current_platform: Current platform (default: auto-detect)
    :return: True if skill should be included
    """
    metadata = entry.metadata
    
    # 无元数据 = 始终包含（无要求）
    if not metadata:
        return True
    
    # 检查平台要求（不能在错误的平台上运行）
    if metadata.os:
        platform_name = current_platform or resolve_runtime_platform()
        # 映射常见平台名称
        platform_map = {
            'darwin': 'darwin',
            'linux': 'linux',
            'windows': 'win32',
        }
        normalized_platform = platform_map.get(platform_name, platform_name)
        
        if normalized_platform not in metadata.os:
            return False
    
    # 若技能标记为 always: true，则忽略其他要求，直接将其包含
    if metadata.always:
        return True
    
    # 检查要求
    if metadata.requires:
        # 检查所需的二进制文件（全部必须存在）
        required_bins = metadata.requires.get('bins', [])
        if required_bins:
            if not all(has_binary(bin_name) for bin_name in required_bins):
                return False
        
        # 检查 anyBins（至少需命中其中一个）
        any_bins = metadata.requires.get('anyBins', [])
        if any_bins:
            if not has_any_binary(any_bins):
                return False
        
        # 检查环境变量（API 密钥）
        # 必须设置所有必需的环境变量
        required_env = metadata.requires.get('env', [])
        if required_env:
            for env_name in required_env:
                if not has_env_var(env_name):
                    return False

        # 检查 anyEnv（至少需命中一个）。已配置的自定义
        # 提供商同样可以满足技能的 anyEnv 要求。
        any_env = metadata.requires.get('anyEnv', [])
        if any_env:
            if not any(has_env_var(e) for e in any_env) and not has_custom_provider(entry.skill.name):
                return False
    
    return True


def get_missing_requirements(
    entry: SkillEntry,
    current_platform: Optional[str] = None,
) -> Dict[str, List[str]]:
    """
    Return a dict of missing requirements for a skill.
    Empty dict means all requirements are met.

    :param entry: SkillEntry to check
    :param current_platform: Current platform (default: auto-detect)
    :return: Dict like {"bins": ["curl"], "env": ["API_KEY"]}
    """
    missing: Dict[str, List[str]] = {}
    metadata = entry.metadata

    if not metadata or not metadata.requires:
        return missing

    required_bins = metadata.requires.get('bins', [])
    if required_bins:
        missing_bins = [b for b in required_bins if not has_binary(b)]
        if missing_bins:
            missing['bins'] = missing_bins

    any_bins = metadata.requires.get('anyBins', [])
    if any_bins and not has_any_binary(any_bins):
        missing['anyBins'] = any_bins

    required_env = metadata.requires.get('env', [])
    if required_env:
        missing_env = [e for e in required_env if not has_env_var(e)]
        if missing_env:
            missing['env'] = missing_env

    any_env = metadata.requires.get('anyEnv', [])
    if any_env and not any(has_env_var(e) for e in any_env) and not has_custom_provider(entry.skill.name):
        missing['anyEnv'] = any_env

    return missing


def is_config_path_truthy(config: Dict, path: str) -> bool:
    """
    Check if a config path resolves to a truthy value.
    
    :param config: Configuration dictionary
    :param path: Dot-separated path (e.g., 'skills.enabled')
    :return: True if path resolves to truthy value
    """
    parts = path.split('.')
    current = config
    
    for part in parts:
        if not isinstance(current, dict):
            return False
        current = current.get(part)
        if current is None:
            return False
    
    # 判断该值是否为真（truthy）
    if isinstance(current, bool):
        return current
    if isinstance(current, (int, float)):
        return current != 0
    if isinstance(current, str):
        return bool(current.strip())
    
    return bool(current)


def resolve_config_path(config: Dict, path: str):
    """
    Resolve a dot-separated config path to its value.
    
    :param config: Configuration dictionary
    :param path: Dot-separated path
    :return: Value at path or None
    """
    parts = path.split('.')
    current = config
    
    for part in parts:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
        if current is None:
            return None
    
    return current
