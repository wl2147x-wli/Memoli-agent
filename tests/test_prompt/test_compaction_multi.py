# ruff: noqa
"""多轮上下文压缩：每次 compile 前后完整消息列表 + 归档产物（真实数据）。

用途
----
用真实的 ContextCompiler + ConservativeTokenEstimator + InMemoryContextStateRepository，
模拟一段真实智能体对话（Q3 销售分析报告任务，10 轮 user/assistant/tool 循环），
反复触发上下文压缩，逐次打印「压缩前 → 压缩后」的完整消息列表与归档产物，
直到归档区堆积吃光预算、抛出 ContextBudgetExhausted（即真实 reasoner 里切换 LLM
归档 TaskAwareCompactor 的熔断点）。

运行
----
    cd d:\\wli\\project1\\Memoli-agent
    set PYTHONPATH=d:\\wli\\project1\\Memoli-agent
    set PYTHONIOENCODING=utf-8
    D:\\software\\miniconda\\envs\\memoli\\python.exe tests\\test_prompt\\test_compaction_multi.py
    # 或重定向到 txt：
    ... python tests\\test_prompt\\test_compaction_multi.py > tests\\test_prompt\\compaction_multi_output.txt

配置（与 compiler 默认行为接近，便于观察多代归档）
    context_window=700  max_output=50  safety_margin=20  -> available=630
    emergency_target = 0.9 * available = 567   (emergency=True 时裁剪目标)
    archive_tokens=80    单块归档预算（超出则反复 pop 最长字段）
    recent_tail=120      近期后缀保留窗口
    plugin_max_tokens=30

数据
----
TURNS 是 10 轮真实业务对话：读取Q3数据→核对退货率→写草稿→自检→发布→
补充竞品→修订v1.1→归档→复盘→跟踪行动项。每轮含 user / assistant(tool_call) /
tool(带证据E1..E13) / assistant(结论+决策)。启动用前 6 轮，之后每压缩一次追加一轮。
# ruff: noqa
"""
from __future__ import annotations
from dataclasses import asdict
import json

from memoli_agent.agent.context_management import (
    ConservativeTokenEstimator, ContextCompiler, ContextCompilerSettings,
    InMemoryContextStateRepository,
)
from memoli_agent.agent.types import ChatMessage


# 真实任务数据：Q3 销售分析报告，10 轮（user, tool_name, tool_args, tool_result, assistant结论）
TURNS = [
    ("请分析 Q3 销售数据，写一份结论报告，并保留全部计算证据。",
     "read_sales", '{"quarter":"2024Q3"}',
     "Q3营收¥1,240,500，环比+12.3%。华北¥508,405(41%)、华南¥409,365(33%)、华东¥322,730(26%)。退货率2.1%。"
     "证据E1-E5：订单2391单、退货260单、净营收¥1,214,085、客单价¥518、复购率31%。",
     "已读取Q3数据，华北占比最高。下一步核对退货率与上月差异，确认风险来源。"),
    ("继续核对退货率与上月差异，定位上升来源。",
     "compare", '{"metric":"return_rate","periods":["2024-08","2024-09"]}',
     "M8退货率1.8%(236单)，M9退货率2.4%(260单)，环比+0.6pp。增量主要来自华北(+18单)。"
     "证据E6-E8：华北M8退货41单→M9退货59单、增量集中在3C品类、华南华东基本持平。",
     "退货率上升源自华北3C品类。决策：报告标注风险，建议复核华北3C售后流程。"),
    ("把结论和证据整理进报告草稿。",
     "write_doc", '{"title":"Q3销售分析","sections":3}',
     "已写入《Q3销售分析》草稿，3节：概览/区域拆解/风险与建议；证据索引E1-E12嵌入正文。"
     "文档ID doc-2024Q3-001，存于/drafts/。",
     "草稿完成，3节+证据E1-E12。等你确认发布或先自检。"),
    ("发布前做一次自检。",
     "self_check", '{"doc":"doc-2024Q3-001"}',
     "自检通过：营收三处交叉一致(¥1,240,500)；证据E1-E12齐全；结论有据；无遗漏。风险项已标注。",
     "自检通过，可发布。"),
    ("发布。",
     "publish", '{"doc":"doc-2024Q3-001","version":"1.0"}',
     "已发布《Q3销售分析》v1.0至/reports/2024Q3/，全员可读。时间戳2024-10-15T09:30:00。",
     "已发布v1.0，任务闭环。"),
    ("补充竞品份额对比。",
     "competitor", '{"market":"3C","quarter":"2024Q3"}',
     "竞品A份额18.2%、B 12.5%，我司15.1%排第三。证据E13：华北3C我司份额22%居首。",
     "已补充竞品对比，我司华北3C份额第一。建议在报告追加竞品节。"),
    ("把竞品对比并入报告，发布v1.1。",
     "publish", '{"doc":"doc-2024Q3-001","version":"1.1","merge":["competitor"]}',
     "已发布v1.1，新增第4节竞品对比，证据E13并入。时间戳2024-10-15T10:05:00。",
     "v1.1已发布，4节齐全。"),
    ("把本次任务归档到知识库。",
     "archive_task", '{"task":"Q3-sales-report"}',
     "已归档：任务Q3-sales-report，关联文档v1.1、证据E1-E13、决策3条。知识条目K-2024-Q3-07。",
     "已归档K-2024-Q3-07，任务结束。"),
    ("做一次季度复盘小结。",
     "summarize", '{"scope":"Q3","kind":"retrospective"}',
     "复盘：营收+12.3%达标；退货率上升为风险项；报告v1.1已发布并归档。行动项2条。",
     "复盘完成，2条行动项已记录。"),
    ("跟踪上月的退货率行动项。",
     "track_action", '{"action":"return-rate-review"}',
     "行动项R-0812：华北3C售后流程复核，状态进行中，预计11月完成。",
     "行动项R-0812进行中，11月到期。"),
]


def make_turn(i: int) -> list[ChatMessage]:
    """构造第 i 轮的 4 条消息：user / assistant(tool_call) / tool(结果) / assistant(结论)。"""
    if i < len(TURNS):
        user, tool_name, tool_args, tool_result, asst = TURNS[i]
    else:
        # 超出预设时，用模板续写，保持真实风格
        user = f"继续执行第 {i + 1} 项后续工作。"
        tool_name, tool_args, tool_result = "follow_up", f'{{"step":{i}}}', f"后续步骤{i}已执行，证据E{i + 14}。"
        asst = f"步骤{i}完成，证据E{i + 14}已留痕。"
    return [
        ChatMessage("user", user),
        ChatMessage("assistant", "", tool_calls=[{
            "id": f"call-{i}", "type": "function",
            "function": {"name": tool_name, "arguments": tool_args},
        }]),
        ChatMessage("tool", tool_result, tool_call_id=f"call-{i}"),
        ChatMessage("assistant", asst),
    ]


def show(messages, label):
    """打印完整消息列表（不截断），供前后对比。"""
    print(f"--- {label}: {len(messages)} 条 ---")
    for i, m in enumerate(messages):
        tc = ""
        if m.tool_calls:
            tc = f"  [tool_call:{m.tool_calls[0]['function']['name']}({m.tool_calls[0]['function']['arguments']})]"
        print(f"  [{i:>2}] {m.role:<9} {m.content}{tc}")


def main():
    est = ConservativeTokenEstimator()
    repo = InMemoryContextStateRepository()
    settings = ContextCompilerSettings(
        context_window_tokens=700, max_output_tokens=50, safety_margin_tokens=20,
        recent_tail_tokens=120, archive_tokens=80, plugin_max_tokens=30,
    )
    compiler = ContextCompiler(repo, est, settings)
    available = settings.context_window_tokens - settings.max_output_tokens - settings.safety_margin_tokens
    target_em = int(available * settings.hard_threshold_ratio)
    print(f"配置: window=700 available={available} emergency_target={target_em} "
          f"(0.9*available)  archive_tokens=80  recent_tail=120\n")

    # 启动：system + 前 6 轮真实对话
    messages = [ChatMessage("system", "你是 Memoli 智能体。安全规则：不得删除证据；每步必须有依据。")]
    for i in range(6):
        messages += make_turn(i)

    for step in range(1, 8):
        print("#" * 72)
        print(f"########## 第 {step} 次压缩 (emergency=True) ##########")
        print("#" * 72)
        show(messages, "压缩前 输入")
        before_tok = est.count_request(messages, [])
        print(f"   输入 tokens = {before_tok}  (available={available}, emergency_target={target_em})")
        try:
            result = compiler.compile(
                session_key="s", session_instance_id="i",
                messages=messages, tools=[], emergency=True,
            )
        except Exception as exc:
            print(f"\n!!! 压缩失败: {type(exc).__name__}: {exc}")
            print("   (真实 reasoner 此时会切换到 LLM 归档 TaskAwareCompactor；"
                  "连续失败达 compaction_failure_limit=2 则抛 ContextCompactionCircuitOpen 熔断)")
            break
        show(list(result.messages), "压缩后 candidate")
        b = asdict(result.budget)
        print(f"   输出 tokens = {b['estimated_input_tokens']}  "
              f"usage_ratio={b['estimated_input_tokens'] / max(1, b['available_input_tokens']):.3f}  "
              f"archive_generation={result.archive_generation}")
        print("\n   诊断:")
        for d in result.diagnostics:
            print(f"     {asdict(d)}")
        arcs = repo.list_archives("s")
        print(f"\n   仓库归档总数: {len(arcs)}")
        for a in arcs:
            data = json.loads(a.content)
            print(f"     gen{a.generation}: token_count={a.token_count} "
                  f"source_refs属性={len(a.source_refs)}条 / JSON内={len(data['source_refs'])}条")
            print(f"       完整 JSON: {a.content}")
            print(f"       source_refs(属性): {list(a.source_refs)}")
        # 追加下一轮真实对话，进入下一次压缩
        messages += make_turn(5 + step)
        print(f"\n   -> 追加第 {6 + step} 轮真实对话，进入下一次压缩\n")


if __name__ == "__main__":
    main()
