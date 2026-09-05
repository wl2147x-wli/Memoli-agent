"""
Frontmatter parsing for skills.
"""

import re
import json
from typing import Dict, Any, Optional, List
from agent.skills.types import SkillMetadata, SkillInstallSpec


def parse_frontmatter(content: str) -> Dict[str, Any]:
    """
    Parse YAML-style frontmatter from markdown content.
    
    Returns a dictionary of frontmatter fields.
    """
    frontmatter = {}
    
    # 匹配 --- 标记之间的 frontmatter 块
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if not match:
        return frontmatter
    
    frontmatter_text = match.group(1)
    
    # 尝试使用 PyYAML 进行正确的 YAML 解析
    try:
        import yaml
        frontmatter = yaml.safe_load(frontmatter_text)
        if not isinstance(frontmatter, dict):
            frontmatter = {}
        return frontmatter
    except ImportError:
        # 如果 PyYAML 不可用，则回退到简单解析
        pass
    except Exception:
        # 如果 YAML 解析失败，则回退到简单解析
        pass
    
    # 简单的类似 YAML 的解析（仅支持 key: value 格式）
    # 这是 PyYAML 不可用时的后备方案
    for line in frontmatter_text.split('\n'):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()
            
            # 看起来像 JSON 时，尝试按 JSON 解析
            if value.startswith('{') or value.startswith('['):
                try:
                    value = json.loads(value)
                except json.JSONDecodeError:
                    pass
            # 解析布尔值
            elif value.lower() in ('true', 'false'):
                value = value.lower() == 'true'
            # 解析数字
            elif value.isdigit():
                value = int(value)
            
            frontmatter[key] = value
    
    return frontmatter


def parse_metadata(frontmatter: Dict[str, Any]) -> Optional[SkillMetadata]:
    """
    Parse skill metadata from frontmatter.
    
    Looks for 'metadata' field containing JSON with skill configuration.
    """
    metadata_raw = frontmatter.get('metadata')
    if not metadata_raw:
        return None
    
    # 如果是字符串，尝试解析为 JSON
    if isinstance(metadata_raw, str):
        try:
            metadata_raw = json.loads(metadata_raw)
        except json.JSONDecodeError:
            return None
    
    if not isinstance(metadata_raw, dict):
        return None
    
    # 去掉外层命名空间包装（例如 {"cowagent": {...}} 或 {"openclaw": {...}}）
    meta_obj = _unwrap_metadata_namespace(metadata_raw)
    
    # 解析安装规范
    install_specs = []
    install_raw = meta_obj.get('install', [])
    if isinstance(install_raw, list):
        for spec_raw in install_raw:
            if not isinstance(spec_raw, dict):
                continue
            
            kind = spec_raw.get('kind', spec_raw.get('type', '')).lower()
            if not kind:
                continue
            
            spec = SkillInstallSpec(
                kind=kind,
                id=spec_raw.get('id'),
                label=spec_raw.get('label'),
                bins=_normalize_string_list(spec_raw.get('bins')),
                os=_normalize_string_list(spec_raw.get('os')),
                formula=spec_raw.get('formula'),
                package=spec_raw.get('package'),
                module=spec_raw.get('module'),
                url=spec_raw.get('url'),
                archive=spec_raw.get('archive'),
                extract=spec_raw.get('extract', False),
                strip_components=spec_raw.get('stripComponents'),
                target_dir=spec_raw.get('targetDir'),
            )
            install_specs.append(spec)
    
    # 解析 requires 字段（依赖声明）
    requires = {}
    requires_raw = meta_obj.get('requires', {})
    if isinstance(requires_raw, dict):
        for key, value in requires_raw.items():
            requires[key] = _normalize_string_list(value)
    
    return SkillMetadata(
        always=meta_obj.get('always', False),
        default_enabled=meta_obj.get('default_enabled', True),
        skill_key=meta_obj.get('skillKey'),
        primary_env=meta_obj.get('primaryEnv'),
        emoji=meta_obj.get('emoji'),
        homepage=meta_obj.get('homepage'),
        os=_normalize_string_list(meta_obj.get('os')),
        requires=requires,
        install=install_specs,
    )


_KNOWN_METADATA_NAMESPACES = {"cowagent", "openclaw"}


def _unwrap_metadata_namespace(metadata_raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Unwrap a single-key namespace wrapper like {"cowagent": {...} or {"openclaw": {...}}}.
    If the top-level dict has exactly one key matching a known namespace, return the inner dict.
    Otherwise return the original dict unchanged.
    """
    keys = set(metadata_raw.keys())
    ns_keys = keys & _KNOWN_METADATA_NAMESPACES
    if len(ns_keys) == 1 and len(keys) == 1:
        ns = ns_keys.pop()
        inner = metadata_raw[ns]
        if isinstance(inner, dict):
            return inner
    return metadata_raw


def _normalize_string_list(value: Any) -> List[str]:
    """Normalize a value to a list of strings."""
    if not value:
        return []
    
    if isinstance(value, list):
        return [str(v).strip() for v in value if v]
    
    if isinstance(value, str):
        return [v.strip() for v in value.split(',') if v.strip()]
    
    return []


def parse_boolean_value(value: Optional[str], default: bool = False) -> bool:
    """Parse a boolean value from frontmatter."""
    if value is None:
        return default
    
    if isinstance(value, bool):
        return value
    
    if isinstance(value, str):
        return value.lower() in ('true', '1', 'yes', 'on')
    
    return default


def get_frontmatter_value(frontmatter: Dict[str, Any], key: str) -> Optional[str]:
    """Get a frontmatter value as a string."""
    value = frontmatter.get(key)
    return str(value) if value is not None else None
