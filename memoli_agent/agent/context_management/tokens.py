"""模型输入 token 计数端口与无外部依赖的保守实现。"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from typing import Any, Protocol

from memoli_agent.agent.types import ChatMessage

_CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


class TokenEstimator(Protocol):
    name: str
    exact: bool

    def count_text(self, text: str) -> int: ...

    def count_request(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
    ) -> int: ...


class ConservativeTokenEstimator:
    """偏高估算中文、英文、JSON 和 Chat Template 固定开销。"""

    name = "conservative-v1"
    exact = False

    def count_text(self, text: str) -> int:
        if not text:
            return 0
        cjk = len(_CJK.findall(text))
        other = max(0, len(text) - cjk)
        # 中文按 1 token/字；其他文本按至多 3 chars/token，最后留 10% 余量。
        return max(1, math.ceil((cjk + math.ceil(other / 3)) * 1.10))

    def count_request(
        self,
        messages: Sequence[ChatMessage],
        tools: Sequence[dict[str, Any]],
    ) -> int:
        total = 3  # assistant generation marker
        for message in messages:
            total += 5 + self.count_text(message.role)
            total += self.count_text(message.content)
            if message.name:
                total += self.count_text(message.name)
            if message.tool_call_id:
                total += self.count_text(message.tool_call_id)
            if message.tool_calls:
                serialized_calls = json.dumps(
                    message.tool_calls,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                total += self.count_text(serialized_calls)
            if message.blocks:
                total += self.count_text(
                    json.dumps(
                        message.blocks,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
        if tools:
            total += 8 + self.count_text(
                json.dumps(
                    list(tools),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        return total


# 模型 profile → tokenizer 适配器注册表（§4.7）。当前无内置真实 tokenizer 适配器，
# 未命中时退回 ConservativeTokenEstimator（exact=False）；接入真实适配器时在此注册。
_TOKENIZER_ADAPTERS: dict[str, TokenEstimator] = {}


def register_tokenizer_adapter(model_profile: str, adapter: TokenEstimator) -> None:
    """为指定模型 profile 注册 tokenizer 适配器（支持真实精确计数时调用）。"""

    _TOKENIZER_ADAPTERS[model_profile] = adapter


def resolve_token_estimator(model_profile: str = "") -> TokenEstimator:
    """按模型 profile 选择 tokenizer 适配器；无适配器时用保守估算（exact=False，§4.7）。

    诊断据此标识模型、适配器与精确计数状态：有适配器则 ``exact=True``，否则
    ``exact=False`` 不得宣称为精确 token。
    """

    if model_profile and model_profile in _TOKENIZER_ADAPTERS:
        return _TOKENIZER_ADAPTERS[model_profile]
    return ConservativeTokenEstimator()
