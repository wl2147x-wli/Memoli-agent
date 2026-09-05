"""Web Search tool. Supports six backends with a unified response format:
  - bocha   (https://open.bochaai.com)
  - zhipu   (https://docs.bigmodel.cn/cn/guide/tools/web-search)
  - qianfan (https://cloud.baidu.com/doc/qianfan/s/2mh4su4uy)
  - linkai  (https://link-ai.tech, fallback)
  - anysearch (https://anysearch.com)
  - serply  (https://serply.io, Google/Bing SERP API)

Provider selection
  - strategy 'auto' (default): pick the first configured provider in the
    canonical order [bocha, qianfan, zhipu, linkai, anysearch, serply]. When
    the caller passes an explicit `provider` it overrides the pick; an
    invalid/unconfigured one silently falls back to the auto order.
  - strategy 'fixed': use the configured provider; if its credential is
    missing at call time, silently fall back to auto order (no card hint).

Credentials
  - bocha   : tools.web_search.bocha_api_key  ->  env BOCHA_API_KEY
  - zhipu   : conf.zhipu_ai_api_key            ->  env ZHIPUAI_API_KEY
  - qianfan : conf.qianfan_api_key             ->  env QIANFAN_API_KEY
  - linkai  : conf.linkai_api_key              ->  env LINKAI_API_KEY
  - anysearch : tools.web_search.anysearch_api_key  -> env ANYSEARCH_API_KEY
  - serply  : tools.web_search.serply_api_key  ->  env SERPLY_API_KEY
"""

import json
import os
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import requests

from agent.tools.base_tool import BaseTool, ToolResult
from common.log import logger
from config import conf


DEFAULT_TIMEOUT = 30

# 规范的回退顺序，按中文实时搜索的质量与相关性从高到低排列：
# 博查（整体最佳）、千帆（热点新闻最佳）、
# zhipu（擅长长文）、linkai（云聚合器）、
# anysearch、serply（全球 Google/Bing SERP，排在最后是因为
# 它没有针对上述中国市场提供商做过评测）。
PROVIDER_ORDER = ("bocha", "qianfan", "zhipu", "linkai", "anysearch", "serply")

PROVIDER_LABELS = {
    "bocha":   "Bocha",
    "zhipu":   "Zhipu",
    "qianfan": "Baidu Qianfan",
    "linkai":  "LinkAI",
    "anysearch": "AnySearch",
    "serply":  "Serply",
}


def _tools_web_search_conf() -> dict:
    """Return the tools.web_search config block (dict-like)."""
    tools_cfg = conf().get("tools") or {}
    if not isinstance(tools_cfg, dict):
        return {}
    block = tools_cfg.get("web_search") or {}
    return block if isinstance(block, dict) else {}


def _get_api_key(provider: str) -> str:
    """Resolve API key for a provider, with conf -> env fallback."""
    if provider == "bocha":
        key = (_tools_web_search_conf().get("bocha_api_key") or "").strip()
        return key or os.environ.get("BOCHA_API_KEY", "").strip()
    if provider == "zhipu":
        key = (conf().get("zhipu_ai_api_key") or "").strip()
        return key or os.environ.get("ZHIPUAI_API_KEY", "").strip()
    if provider == "qianfan":
        key = (conf().get("qianfan_api_key") or "").strip()
        return key or os.environ.get("QIANFAN_API_KEY", "").strip()
    if provider == "linkai":
        key = (conf().get("linkai_api_key") or "").strip()
        return key or os.environ.get("LINKAI_API_KEY", "").strip()
    if provider == "anysearch":
        key = (_tools_web_search_conf().get("anysearch_api_key") or "").strip()
        return key or os.environ.get("ANYSEARCH_API_KEY", "").strip()
    if provider == "serply":
        key = (_tools_web_search_conf().get("serply_api_key") or "").strip()
        return key or os.environ.get("SERPLY_API_KEY", "").strip()
    return ""


def configured_providers() -> List[str]:
    """Return configured providers in canonical order."""
    return [p for p in PROVIDER_ORDER if _get_api_key(p)]


def _configured_strategy() -> str:
    return (_tools_web_search_conf().get("strategy") or "auto").strip().lower()


def _configured_provider() -> str:
    return (_tools_web_search_conf().get("provider") or "").strip().lower()


class WebSearch(BaseTool):
    """Tool for searching the web across multiple providers."""

    name: str = "web_search"
    description: str = "Search the web for real-time information. Returns titles, URLs, and snippets."

    params: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query string"
            },
            "count": {
                "type": "integer",
                "description": "Number of results to return (1-50, default: 10)"
            },
            "freshness": {
                "type": "string",
                "description": (
                    "Time range filter. Options: "
                    "'noLimit' (default), 'oneDay', 'oneWeek', 'oneMonth', 'oneYear', "
                    "or date range like '2025-01-01..2025-02-01'"
                )
            },
            "summary": {
                "type": "boolean",
                "description": "Whether to include text summary for each result (default: false)"
            }
        },
        "required": ["query"]
    }

    def __init__(self, config: dict = None):
        self.config = config or {}

    @staticmethod
    def is_available() -> bool:
        """Tool is offered to the agent when at least one provider has a key."""
        return bool(configured_providers())

    def get_json_schema(self) -> dict:
        """Augment the static schema with a `provider` field — only when the
        user has ≥2 providers configured AND strategy is 'auto'. Otherwise
        the backend picks silently and exposing the field would only waste
        the agent's tokens."""
        schema = {
            "name": self.name,
            "description": self.description,
            "parameters": json.loads(json.dumps(self.params)),  # 深拷贝
        }
        if _configured_strategy() != "auto":
            return schema
        available = configured_providers()
        if len(available) < 2:
            return schema

        schema["parameters"]["properties"]["provider"] = {
            "type": "string",
            "enum": available,
            "description": "Optional. Specifies the search backend. You may switch between providers when the user wants results from a particular source or from multiple sources.",
        }
        return schema

    # ------------------------------------------------------------------
    # 提供商解析
    # ------------------------------------------------------------------

    def _resolve_provider(self, requested: Optional[str]) -> Optional[str]:
        """Pick a provider for this call.

        Priority: caller-supplied (if configured) > fixed strategy (if
        configured) > first configured in PROVIDER_ORDER. Silent fallback
        when the desired one has no key.
        """
        available = configured_providers()
        if not available:
            return None

        if requested:
            req = requested.strip().lower()
            if req in available:
                return req
            logger.warning(f"[WebSearch] requested provider '{requested}' unavailable, falling back")

        if _configured_strategy() == "fixed":
            pinned = _configured_provider()
            if pinned in available:
                return pinned
            if pinned:
                logger.warning(f"[WebSearch] pinned provider '{pinned}' unavailable, falling back to auto")

        return available[0]

    @staticmethod
    def _resolution_reason(requested: Optional[str], chosen: str) -> str:
        """Human-readable explanation for why `chosen` won the resolver."""
        if requested and requested.strip().lower() == chosen:
            return "caller-requested"
        strategy = _configured_strategy()
        if strategy == "fixed" and _configured_provider() == chosen:
            return "fixed-strategy"
        return "auto-fallback"

    # ------------------------------------------------------------------
    # 切入点
    # ------------------------------------------------------------------

    def execute(self, args: Dict[str, Any]) -> ToolResult:
        query = (args.get("query") or "").strip()
        if not query:
            return ToolResult.fail("Error: 'query' parameter is required")

        count = args.get("count", 10)
        freshness = args.get("freshness", "noLimit")
        summary = args.get("summary", False)
        if not isinstance(count, int) or count < 1 or count > 50:
            count = 10

        requested = args.get("provider")
        provider = self._resolve_provider(requested)
        if not provider:
            return ToolResult.fail(
                "Error: No search provider configured. "
                "Configure one of BOCHA_API_KEY / zhipu_ai_api_key / qianfan_api_key / linkai_api_key / "
                "anysearch_api_key / SERPLY_API_KEY."
            )

        # 始终记录路由决策，这样在多提供商部署下，
        # 一眼就能看出某次查询到底是由哪个后端服务的。
        available = configured_providers()
        reason = self._resolution_reason(requested, provider)
        q_preview = query if len(query) <= 60 else (query[:57] + "...")
        logger.info(
            f"[WebSearch] provider={provider} reason={reason} "
            f"available={list(available)} query={q_preview!r} count={count} freshness={freshness}"
        )

        try:
            if provider == "bocha":
                return self._search_bocha(query, count, freshness, summary)
            if provider == "zhipu":
                return self._search_zhipu(query, count, freshness)
            if provider == "qianfan":
                return self._search_qianfan(query, count, freshness)
            if provider == "linkai":
                return self._search_linkai(query, count, freshness)
            if provider == "anysearch":
                return self._search_anysearch(query, count)
            if provider == "serply":
                return self._search_serply(query, count)
            return ToolResult.fail(f"Error: Unknown provider '{provider}'")
        except requests.Timeout:
            return ToolResult.fail(f"Error: Search request timed out after {DEFAULT_TIMEOUT}s")
        except requests.ConnectionError:
            return ToolResult.fail("Error: Failed to connect to search API")
        except Exception as e:
            logger.error(f"[WebSearch] Unexpected error ({provider}): {e}", exc_info=True)
            return ToolResult.fail(f"Error: Search failed - {str(e)}")

    # ------------------------------------------------------------------
    # 博查
    # ------------------------------------------------------------------

    def _search_bocha(self, query: str, count: int, freshness: str, summary: bool) -> ToolResult:
        api_key = _get_api_key("bocha")
        url = "https://api.bochaai.com/v1/web-search"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {"query": query, "count": count, "freshness": freshness, "summary": summary}

        logger.debug(f"[WebSearch] bocha: query='{query}', count={count}")
        resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 401:
            return ToolResult.fail("Error: Invalid bocha API key.")
        if resp.status_code == 403:
            return ToolResult.fail("Error: bocha API — insufficient balance. Top up at https://open.bochaai.com")
        if resp.status_code == 429:
            return ToolResult.fail("Error: bocha API rate limit reached.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: bocha API returned HTTP {resp.status_code}")

        data = resp.json()
        api_code = data.get("code")
        if api_code is not None and api_code != 200:
            msg = data.get("msg") or "Unknown error"
            return ToolResult.fail(f"Error: bocha API error (code={api_code}): {msg}")

        pages = (data.get("data") or {}).get("webPages", {}).get("value", []) or []
        results = []
        for p in pages:
            item = {
                "title": p.get("name", ""),
                "url": p.get("url", ""),
                "snippet": p.get("snippet", ""),
                "siteName": p.get("siteName", ""),
                "datePublished": p.get("datePublished") or p.get("dateLastCrawled", ""),
            }
            if p.get("summary"):
                item["summary"] = p["summary"]
            results.append(item)
        total = (data.get("data") or {}).get("webPages", {}).get("totalEstimatedMatches", len(results))
        return ToolResult.success({
            "query": query, "backend": "bocha",
            "total": total, "count": len(results), "results": results,
        })

    # ------------------------------------------------------------------
    # 智谱
    # ------------------------------------------------------------------

    def _search_zhipu(self, query: str, count: int, freshness: str) -> ToolResult:
        api_key = _get_api_key("zhipu")
        api_base = (conf().get("zhipu_ai_api_base") or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
        url = f"{api_base}/web_search"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # 智谱网页搜索要求 `search_query` 不超过 70 个字符；
        # 这里先截断，避免代理给出的过长查询被接口拒绝。
        trimmed_query = (query or "")[:70]
        engine = (_tools_web_search_conf().get("zhipu_search_engine") or "search_pro").strip().lower()
        if engine not in ("search_std", "search_pro", "search_pro_sogou", "search_pro_quark"):
            engine = "search_pro"

        payload: Dict[str, Any] = {
            "search_engine": engine,
            "search_query": trimmed_query,
            "search_intent": False,
            "count": max(1, min(int(count or 10), 50)),
            "search_recency_filter": freshness if freshness in (
                "oneDay", "oneWeek", "oneMonth", "oneYear", "noLimit"
            ) else "noLimit",
        }
        content_size = (_tools_web_search_conf().get("zhipu_content_size") or "").strip().lower()
        if content_size in ("medium", "high"):
            payload["content_size"] = content_size

        logger.debug(f"[WebSearch] zhipu: query='{trimmed_query}', count={payload['count']}, engine={engine}")
        resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 401:
            return ToolResult.fail("Error: Invalid Zhipu API key.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: Zhipu API returned HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        # 业务级错误（如 1701/1702/1703）会以
        # {"error": {"code","message"}} 的形式返回，哪怕 HTTP 状态是 200。
        if isinstance(data, dict) and data.get("error"):
            err = data["error"] or {}
            return ToolResult.fail(f"Error: Zhipu returned {err.get('code')}: {err.get('message','')}")

        items = data.get("search_result") or (data.get("data") or {}).get("search_result") or []
        results = []
        for it in items:
            results.append({
                "title": it.get("title", ""),
                "url": it.get("link") or it.get("url", ""),
                "snippet": it.get("content") or it.get("snippet", ""),
                "siteName": it.get("media") or it.get("siteName", ""),
                "datePublished": it.get("publish_date") or it.get("datePublished", ""),
            })
        return ToolResult.success({
            "query": query, "backend": "zhipu",
            "total": len(results), "count": len(results), "results": results,
        })

    # ------------------------------------------------------------------
    # 千帆（百度）
    # ------------------------------------------------------------------

    def _search_qianfan(self, query: str, count: int, freshness: str) -> ToolResult:
        api_key = _get_api_key("qianfan")
        api_base = (conf().get("qianfan_api_base") or "https://qianfan.baidubce.com/v2").rstrip("/")
        url = f"{api_base}/ai_search/web_search"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-Appbuilder-From": "cow",
        }

        count = max(1, min(int(count or 10), 50))
        payload: Dict[str, Any] = {
            "messages": [{"role": "user", "content": query}],
            "search_source": "baidu_search_v2",
            "resource_type_filter": [{"type": "web", "top_k": count}],
        }

        # 百度 AI 搜索要求把“新鲜度”表示成日期范围过滤器，而不是
        # 命名的时效令牌。因此这里把我们的通用取值转换成
        # API 所期望的底层 page_time 时间范围。
        search_filter = self._qianfan_build_freshness_filter(freshness)
        if search_filter:
            payload["search_filter"] = search_filter

        logger.debug(f"[WebSearch] qianfan: query='{query}', count={count}, freshness={freshness!r}")
        resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 401:
            return ToolResult.fail("Error: Invalid Qianfan API key.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: Qianfan API returned HTTP {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        # 即使在 HTTP 200 时，百度也会以 {"code","message"} 的形式返回业务错误。
        if isinstance(data, dict) and data.get("code"):
            return ToolResult.fail(f"Error: Qianfan returned {data.get('code')}: {data.get('message','')}")

        refs = data.get("references") or []
        results = []
        for d in refs:
            results.append({
                "title": d.get("title", ""),
                "url": d.get("url", ""),
                "snippet": (d.get("content") or "")[:200],
                "siteName": d.get("web_anchor") or d.get("website") or "",
                "datePublished": d.get("date", ""),
            })
        return ToolResult.success({
            "query": query, "backend": "qianfan",
            "total": len(results), "count": len(results), "results": results,
        })

    @staticmethod
    def _qianfan_build_freshness_filter(freshness: str) -> Optional[Dict[str, Any]]:
        if not freshness or freshness == "noLimit":
            return None
        delta_days = {"oneDay": 1, "oneWeek": 7, "oneMonth": 30, "oneYear": 365}.get(freshness)
        if not delta_days:
            return None
        from datetime import datetime, timedelta
        now = datetime.now()
        end_date = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        start_date = (now - timedelta(days=delta_days)).strftime("%Y-%m-%d")
        return {"range": {"page_time": {"gte": start_date, "lt": end_date}}}

    # ------------------------------------------------------------------
    # LinkAI（插件）
    # ------------------------------------------------------------------

    def _search_linkai(self, query: str, count: int, freshness: str) -> ToolResult:
        api_key = _get_api_key("linkai")
        api_base = (conf().get("linkai_api_base") or "https://api.link-ai.tech").rstrip("/")
        url = f"{api_base}/v1/plugin/execute"

        from common.utils import get_cloud_headers
        headers = get_cloud_headers(api_key)

        payload = {"code": "web-search", "args": {"query": query, "count": count, "freshness": freshness}}
        logger.debug(f"[WebSearch] linkai: query='{query}', count={count}")
        resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 401:
            return ToolResult.fail("Error: Invalid LinkAI API key.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: LinkAI API returned HTTP {resp.status_code}")

        data = resp.json()
        if not data.get("success"):
            msg = data.get("message") or "Unknown error"
            return ToolResult.fail(f"Error: LinkAI search failed: {msg}")

        raw = data.get("data", "")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return ToolResult.success({
                    "query": query, "backend": "linkai",
                    "total": 1, "count": 1, "results": [{"content": raw}],
                })

        if isinstance(raw, dict):
            pages = (raw.get("webPages") or {}).get("value", []) or []
            if pages:
                results = []
                for p in pages:
                    item = {
                        "title": p.get("name", ""),
                        "url": p.get("url", ""),
                        "snippet": p.get("snippet", ""),
                        "siteName": p.get("siteName", ""),
                        "datePublished": p.get("datePublished") or p.get("dateLastCrawled", ""),
                    }
                    if p.get("summary"):
                        item["summary"] = p["summary"]
                    results.append(item)
                total = (raw.get("webPages") or {}).get("totalEstimatedMatches", len(results))
                return ToolResult.success({
                    "query": query, "backend": "linkai",
                    "total": total, "count": len(results), "results": results,
                })

        return ToolResult.success({
            "query": query, "backend": "linkai",
            "total": 1, "count": 1, "results": [{"content": str(raw)}],
        })

    def _search_anysearch(self, query: str, count: int) -> ToolResult:
        api_key = _get_api_key("anysearch")
        url = "https://api.anysearch.com/v1/search"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        # AnySearch 也接受不携带密钥的匿名请求（带每日免费额度），
        # 因此仅在配置了密钥时才发送 Authorization 请求头。
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # AnySearch 最多接受 1-20 条结果；而工具共用的参数定义允许 1-50。
        max_results = max(1, min(int(count or 10), 20))
        payload = {"query": query, "max_results": max_results, "format": "json"}

        logger.debug(f"[WebSearch] anysearch: query='{query}', max_results={max_results}")
        resp = requests.post(url, headers=headers, json=payload, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 401:
            return ToolResult.fail("Error: Invalid AnySearch API key.")
        if resp.status_code == 402:
            return ToolResult.fail("Error: AnySearch quota exhausted. Check usage at https://anysearch.com")
        if resp.status_code == 429:
            return ToolResult.fail("Error: AnySearch API rate limit reached.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: AnySearch API returned HTTP {resp.status_code}")

        data = resp.json()
        # AnySearch 以业务代码 0（而非 200）表示成功。
        api_code = data.get("code")
        if api_code not in (0, None):
            msg = data.get("message") or "Unknown error"
            return ToolResult.fail(f"Error: AnySearch API error (code={api_code}): {msg}")

        body = data.get("data") or {}
        results = []
        for it in body.get("results") or []:
            results.append({
                "title": it.get("title", ""),
                "url": it.get("url", ""),
                "snippet": it.get("snippet") or (it.get("content") or "")[:200],
            })
        total = (body.get("metadata") or {}).get("total_results", len(results))
        return ToolResult.success({
            "query": query, "backend": "anysearch",
            "total": total, "count": len(results), "results": results,
        })

    # ------------------------------------------------------------------
    # 瑟普利
    # ------------------------------------------------------------------

    def _search_serply(self, query: str, count: int) -> ToolResult:
        api_key = _get_api_key("serply")
        path = urlencode({"q": query, "num": max(1, min(int(count or 10), 50))})
        headers = {
            "X-Api-Key": api_key,
            "Accept": "application/json",
            # Serply 位于 Cloudflare 之后，而 Cloudflare 会拒绝 requests
            # 默认的 User-Agent，因此这里显式发送一个用户代理。
            "User-Agent": "CowAgent",
        }

        logger.debug(f"[WebSearch] serply: query='{query}', count={count}")
        resp = requests.get(f"https://api.serply.io/v1/search/{path}", headers=headers, timeout=DEFAULT_TIMEOUT)

        if resp.status_code == 401:
            return ToolResult.fail("Error: Invalid Serply API key.")
        if resp.status_code == 429:
            return ToolResult.fail("Error: Serply API rate limit reached.")
        if resp.status_code != 200:
            return ToolResult.fail(f"Error: Serply API returned HTTP {resp.status_code}")

        data = resp.json()
        items = data.get("results") or []
        results = []
        for it in items:
            results.append({
                "title": it.get("title", ""),
                "url": it.get("link", ""),
                "snippet": it.get("description", ""),
            })
        return ToolResult.success({
            "query": query, "backend": "serply",
            "total": len(results), "count": len(results), "results": results,
        })
