# 多轮上下文压缩前后对比（真实数据）

> 由 `test_compaction_multi.py` 生成。配置：window=700 / available=630 / emergency_target=567 / archive_tokens=80 / recent_tail=120。Q3 销售分析报告 10 轮真实对话，反复压缩至预算耗尽。

```text
配置: window=700 available=630 emergency_target=567 (0.9*available)  archive_tokens=80  recent_tail=120

########################################################################
########## 第 1 次压缩 (emergency=True) ##########
########################################################################
--- 压缩前 输入: 25 条 ---
  [ 0] system    你是 Memoli 智能体。安全规则：不得删除证据；每步必须有依据。
  [ 1] user      请分析 Q3 销售数据，写一份结论报告，并保留全部计算证据。
  [ 2] assistant   [tool_call:read_sales({"quarter":"2024Q3"})]
  [ 3] tool      Q3营收¥1,240,500，环比+12.3%。华北¥508,405(41%)、华南¥409,365(33%)、华东¥322,730(26%)。退货率2.1%。证据E1-E5：订单2391单、退货260单、净营收¥1,214,085、客单价¥518、复购率31%。
  [ 4] assistant 已读取Q3数据，华北占比最高。下一步核对退货率与上月差异，确认风险来源。
  [ 5] user      继续核对退货率与上月差异，定位上升来源。
  [ 6] assistant   [tool_call:compare({"metric":"return_rate","periods":["2024-08","2024-09"]})]
  [ 7] tool      M8退货率1.8%(236单)，M9退货率2.4%(260单)，环比+0.6pp。增量主要来自华北(+18单)。证据E6-E8：华北M8退货41单→M9退货59单、增量集中在3C品类、华南华东基本持平。
  [ 8] assistant 退货率上升源自华北3C品类。决策：报告标注风险，建议复核华北3C售后流程。
  [ 9] user      把结论和证据整理进报告草稿。
  [10] assistant   [tool_call:write_doc({"title":"Q3销售分析","sections":3})]
  [11] tool      已写入《Q3销售分析》草稿，3节：概览/区域拆解/风险与建议；证据索引E1-E12嵌入正文。文档ID doc-2024Q3-001，存于/drafts/。
  [12] assistant 草稿完成，3节+证据E1-E12。等你确认发布或先自检。
  [13] user      发布前做一次自检。
  [14] assistant   [tool_call:self_check({"doc":"doc-2024Q3-001"})]
  [15] tool      自检通过：营收三处交叉一致(¥1,240,500)；证据E1-E12齐全；结论有据；无遗漏。风险项已标注。
  [16] assistant 自检通过，可发布。
  [17] user      发布。
  [18] assistant   [tool_call:publish({"doc":"doc-2024Q3-001","version":"1.0"})]
  [19] tool      已发布《Q3销售分析》v1.0至/reports/2024Q3/，全员可读。时间戳2024-10-15T09:30:00。
  [20] assistant 已发布v1.0，任务闭环。
  [21] user      补充竞品份额对比。
  [22] assistant   [tool_call:competitor({"market":"3C","quarter":"2024Q3"})]
  [23] tool      竞品A份额18.2%、B 12.5%，我司15.1%排第三。证据E13：华北3C我司份额22%居首。
  [24] assistant 已补充竞品对比，我司华北3C份额第一。建议在报告追加竞品节。
   输入 tokens = 1078  (available=630, emergency_target=567)
--- 压缩后 candidate: 6 条 ---
  [ 0] system    你是 Memoli 智能体。安全规则：不得删除证据；每步必须有依据。
  [ 1] system    <context_archive generation="1">
{"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": ["发布。"], "source_refs": [], "todo_remaining": [], "verification_status": []}
</context_archive>
  [ 2] user      补充竞品份额对比。
  [ 3] assistant   [tool_call:competitor({"market":"3C","quarter":"2024Q3"})]
  [ 4] tool      竞品A份额18.2%、B 12.5%，我司15.1%排第三。证据E13：华北3C我司份额22%居首。
  [ 5] assistant 已补充竞品对比，我司华北3C份额第一。建议在报告追加竞品节。
   输出 tokens = 296  usage_ratio=0.470  archive_generation=1

   诊断:
     {'action': 'archived', 'block_id': 'f35b1fbbff904c35b67930d77caa9067', 'kind': 'archive', 'source': 'context-state', 'reason': 'emergency', 'token_count': 71}

   仓库归档总数: 1
     gen1: token_count=71 source_refs属性=20条 / JSON内=0条
       完整 JSON: {"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": ["发布。"], "source_refs": [], "todo_remaining": [], "verification_status": []}
       source_refs(属性): ['message:a3eaf53e46764e6dcf04629b', 'message:d121ce69d3449946ffa015aa', 'message:2262d0fca860f3a8f9cdb0bc', 'message:f99dd4b69045c55ff1bc765e', 'message:6798ed47273bffd5a106f045', 'message:8816897208265a553cb5d31a', 'message:36473eb58ec5ed8a4c78bb47', 'message:c9f48869ea1bdd88801b8126', 'message:457081e45d261fd6f12205ba', 'message:ff16e87ae8de1e2818764bcb', 'message:eefba80162e379f0c71449ad', 'message:77e1e00e733cc1110dc0d134', 'message:23d2573df7497715c27f7070', 'message:24c10ed18976a4ef7fd1ee67', 'message:01321ccec4940708a6e270d4', 'message:3a9a855eebf964223c8b6236', 'message:597c35f38478fe532df3296e', 'message:e0561abe09ae70c5fde1a24e', 'message:29d0afee0212be62dcad280f', 'message:d6ad6ae1b6bf2ee6215ede7b']

   -> 追加第 7 轮真实对话，进入下一次压缩

########################################################################
########## 第 2 次压缩 (emergency=True) ##########
########################################################################
--- 压缩前 输入: 29 条 ---
  [ 0] system    你是 Memoli 智能体。安全规则：不得删除证据；每步必须有依据。
  [ 1] user      请分析 Q3 销售数据，写一份结论报告，并保留全部计算证据。
  [ 2] assistant   [tool_call:read_sales({"quarter":"2024Q3"})]
  [ 3] tool      Q3营收¥1,240,500，环比+12.3%。华北¥508,405(41%)、华南¥409,365(33%)、华东¥322,730(26%)。退货率2.1%。证据E1-E5：订单2391单、退货260单、净营收¥1,214,085、客单价¥518、复购率31%。
  [ 4] assistant 已读取Q3数据，华北占比最高。下一步核对退货率与上月差异，确认风险来源。
  [ 5] user      继续核对退货率与上月差异，定位上升来源。
  [ 6] assistant   [tool_call:compare({"metric":"return_rate","periods":["2024-08","2024-09"]})]
  [ 7] tool      M8退货率1.8%(236单)，M9退货率2.4%(260单)，环比+0.6pp。增量主要来自华北(+18单)。证据E6-E8：华北M8退货41单→M9退货59单、增量集中在3C品类、华南华东基本持平。
  [ 8] assistant 退货率上升源自华北3C品类。决策：报告标注风险，建议复核华北3C售后流程。
  [ 9] user      把结论和证据整理进报告草稿。
  [10] assistant   [tool_call:write_doc({"title":"Q3销售分析","sections":3})]
  [11] tool      已写入《Q3销售分析》草稿，3节：概览/区域拆解/风险与建议；证据索引E1-E12嵌入正文。文档ID doc-2024Q3-001，存于/drafts/。
  [12] assistant 草稿完成，3节+证据E1-E12。等你确认发布或先自检。
  [13] user      发布前做一次自检。
  [14] assistant   [tool_call:self_check({"doc":"doc-2024Q3-001"})]
  [15] tool      自检通过：营收三处交叉一致(¥1,240,500)；证据E1-E12齐全；结论有据；无遗漏。风险项已标注。
  [16] assistant 自检通过，可发布。
  [17] user      发布。
  [18] assistant   [tool_call:publish({"doc":"doc-2024Q3-001","version":"1.0"})]
  [19] tool      已发布《Q3销售分析》v1.0至/reports/2024Q3/，全员可读。时间戳2024-10-15T09:30:00。
  [20] assistant 已发布v1.0，任务闭环。
  [21] user      补充竞品份额对比。
  [22] assistant   [tool_call:competitor({"market":"3C","quarter":"2024Q3"})]
  [23] tool      竞品A份额18.2%、B 12.5%，我司15.1%排第三。证据E13：华北3C我司份额22%居首。
  [24] assistant 已补充竞品对比，我司华北3C份额第一。建议在报告追加竞品节。
  [25] user      把竞品对比并入报告，发布v1.1。
  [26] assistant   [tool_call:publish({"doc":"doc-2024Q3-001","version":"1.1","merge":["competitor"]})]
  [27] tool      已发布v1.1，新增第4节竞品对比，证据E13并入。时间戳2024-10-15T10:05:00。
  [28] assistant v1.1已发布，4节齐全。
   输入 tokens = 1230  (available=630, emergency_target=567)
--- 压缩后 candidate: 7 条 ---
  [ 0] system    你是 Memoli 智能体。安全规则：不得删除证据；每步必须有依据。
  [ 1] system    <context_archive generation="1">
{"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": ["发布。"], "source_refs": [], "todo_remaining": [], "verification_status": []}
</context_archive>
  [ 2] system    <context_archive generation="2">
{"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": ["补充竞品份额对比。"], "source_refs": [], "todo_remaining": [], "verification_status": []}
</context_archive>
  [ 3] user      把竞品对比并入报告，发布v1.1。
  [ 4] assistant   [tool_call:publish({"doc":"doc-2024Q3-001","version":"1.1","merge":["competitor"]})]
  [ 5] tool      已发布v1.1，新增第4节竞品对比，证据E13并入。时间戳2024-10-15T10:05:00。
  [ 6] assistant v1.1已发布，4节齐全。
   输出 tokens = 396  usage_ratio=0.629  archive_generation=2

   诊断:
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:a3eaf53e46764e6dcf04629b', 'token_count': 29}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:d121ce69d3449946ffa015aa', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:2262d0fca860f3a8f9cdb0bc', 'token_count': 71}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:f99dd4b69045c55ff1bc765e', 'token_count': 36}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:6798ed47273bffd5a106f045', 'token_count': 21}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:8816897208265a553cb5d31a', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:36473eb58ec5ed8a4c78bb47', 'token_count': 70}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:c9f48869ea1bdd88801b8126', 'token_count': 36}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:457081e45d261fd6f12205ba', 'token_count': 16}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:ff16e87ae8de1e2818764bcb', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:eefba80162e379f0c71449ad', 'token_count': 53}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:77e1e00e733cc1110dc0d134', 'token_count': 24}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:23d2573df7497715c27f7070', 'token_count': 10}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:24c10ed18976a4ef7fd1ee67', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:01321ccec4940708a6e270d4', 'token_count': 41}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:3a9a855eebf964223c8b6236', 'token_count': 9}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:597c35f38478fe532df3296e', 'token_count': 4}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:e0561abe09ae70c5fde1a24e', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:29d0afee0212be62dcad280f', 'token_count': 35}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:d6ad6ae1b6bf2ee6215ede7b', 'token_count': 10}
     {'action': 'archived', 'block_id': 'd3a50a1f162d0a7dd2892c3642522cf9', 'kind': 'archive', 'source': 'context-state', 'reason': 'emergency', 'token_count': 77}

   仓库归档总数: 2
     gen1: token_count=71 source_refs属性=20条 / JSON内=0条
       完整 JSON: {"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": ["发布。"], "source_refs": [], "todo_remaining": [], "verification_status": []}
       source_refs(属性): ['message:a3eaf53e46764e6dcf04629b', 'message:d121ce69d3449946ffa015aa', 'message:2262d0fca860f3a8f9cdb0bc', 'message:f99dd4b69045c55ff1bc765e', 'message:6798ed47273bffd5a106f045', 'message:8816897208265a553cb5d31a', 'message:36473eb58ec5ed8a4c78bb47', 'message:c9f48869ea1bdd88801b8126', 'message:457081e45d261fd6f12205ba', 'message:ff16e87ae8de1e2818764bcb', 'message:eefba80162e379f0c71449ad', 'message:77e1e00e733cc1110dc0d134', 'message:23d2573df7497715c27f7070', 'message:24c10ed18976a4ef7fd1ee67', 'message:01321ccec4940708a6e270d4', 'message:3a9a855eebf964223c8b6236', 'message:597c35f38478fe532df3296e', 'message:e0561abe09ae70c5fde1a24e', 'message:29d0afee0212be62dcad280f', 'message:d6ad6ae1b6bf2ee6215ede7b']
     gen2: token_count=77 source_refs属性=4条 / JSON内=0条
       完整 JSON: {"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": ["补充竞品份额对比。"], "source_refs": [], "todo_remaining": [], "verification_status": []}
       source_refs(属性): ['message:f75e1cf07f47d7d8953a451a', 'message:eae92995ff2549770d850b74', 'message:96de33327e8221eb49095387', 'message:31be1fb06badce18fd44c16a']

   -> 追加第 8 轮真实对话，进入下一次压缩

########################################################################
########## 第 3 次压缩 (emergency=True) ##########
########################################################################
--- 压缩前 输入: 33 条 ---
  [ 0] system    你是 Memoli 智能体。安全规则：不得删除证据；每步必须有依据。
  [ 1] user      请分析 Q3 销售数据，写一份结论报告，并保留全部计算证据。
  [ 2] assistant   [tool_call:read_sales({"quarter":"2024Q3"})]
  [ 3] tool      Q3营收¥1,240,500，环比+12.3%。华北¥508,405(41%)、华南¥409,365(33%)、华东¥322,730(26%)。退货率2.1%。证据E1-E5：订单2391单、退货260单、净营收¥1,214,085、客单价¥518、复购率31%。
  [ 4] assistant 已读取Q3数据，华北占比最高。下一步核对退货率与上月差异，确认风险来源。
  [ 5] user      继续核对退货率与上月差异，定位上升来源。
  [ 6] assistant   [tool_call:compare({"metric":"return_rate","periods":["2024-08","2024-09"]})]
  [ 7] tool      M8退货率1.8%(236单)，M9退货率2.4%(260单)，环比+0.6pp。增量主要来自华北(+18单)。证据E6-E8：华北M8退货41单→M9退货59单、增量集中在3C品类、华南华东基本持平。
  [ 8] assistant 退货率上升源自华北3C品类。决策：报告标注风险，建议复核华北3C售后流程。
  [ 9] user      把结论和证据整理进报告草稿。
  [10] assistant   [tool_call:write_doc({"title":"Q3销售分析","sections":3})]
  [11] tool      已写入《Q3销售分析》草稿，3节：概览/区域拆解/风险与建议；证据索引E1-E12嵌入正文。文档ID doc-2024Q3-001，存于/drafts/。
  [12] assistant 草稿完成，3节+证据E1-E12。等你确认发布或先自检。
  [13] user      发布前做一次自检。
  [14] assistant   [tool_call:self_check({"doc":"doc-2024Q3-001"})]
  [15] tool      自检通过：营收三处交叉一致(¥1,240,500)；证据E1-E12齐全；结论有据；无遗漏。风险项已标注。
  [16] assistant 自检通过，可发布。
  [17] user      发布。
  [18] assistant   [tool_call:publish({"doc":"doc-2024Q3-001","version":"1.0"})]
  [19] tool      已发布《Q3销售分析》v1.0至/reports/2024Q3/，全员可读。时间戳2024-10-15T09:30:00。
  [20] assistant 已发布v1.0，任务闭环。
  [21] user      补充竞品份额对比。
  [22] assistant   [tool_call:competitor({"market":"3C","quarter":"2024Q3"})]
  [23] tool      竞品A份额18.2%、B 12.5%，我司15.1%排第三。证据E13：华北3C我司份额22%居首。
  [24] assistant 已补充竞品对比，我司华北3C份额第一。建议在报告追加竞品节。
  [25] user      把竞品对比并入报告，发布v1.1。
  [26] assistant   [tool_call:publish({"doc":"doc-2024Q3-001","version":"1.1","merge":["competitor"]})]
  [27] tool      已发布v1.1，新增第4节竞品对比，证据E13并入。时间戳2024-10-15T10:05:00。
  [28] assistant v1.1已发布，4节齐全。
  [29] user      把本次任务归档到知识库。
  [30] assistant   [tool_call:archive_task({"task":"Q3-sales-report"})]
  [31] tool      已归档：任务Q3-sales-report，关联文档v1.1、证据E1-E13、决策3条。知识条目K-2024-Q3-07。
  [32] assistant 已归档K-2024-Q3-07，任务结束。
   输入 tokens = 1375  (available=630, emergency_target=567)
--- 压缩后 candidate: 8 条 ---
  [ 0] system    你是 Memoli 智能体。安全规则：不得删除证据；每步必须有依据。
  [ 1] system    <context_archive generation="1">
{"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": ["发布。"], "source_refs": [], "todo_remaining": [], "verification_status": []}
</context_archive>
  [ 2] system    <context_archive generation="2">
{"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": ["补充竞品份额对比。"], "source_refs": [], "todo_remaining": [], "verification_status": []}
</context_archive>
  [ 3] system    <context_archive generation="3">
{"decisions_reasons": ["", "v1.1已发布，4节齐全。"], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": [], "source_refs": [], "todo_remaining": [], "verification_status": []}
</context_archive>
  [ 4] user      把本次任务归档到知识库。
  [ 5] assistant   [tool_call:archive_task({"task":"Q3-sales-report"})]
  [ 6] tool      已归档：任务Q3-sales-report，关联文档v1.1、证据E1-E13、决策3条。知识条目K-2024-Q3-07。
  [ 7] assistant 已归档K-2024-Q3-07，任务结束。
   输出 tokens = 495  usage_ratio=0.786  archive_generation=3

   诊断:
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:a3eaf53e46764e6dcf04629b', 'token_count': 29}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:d121ce69d3449946ffa015aa', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:2262d0fca860f3a8f9cdb0bc', 'token_count': 71}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:f99dd4b69045c55ff1bc765e', 'token_count': 36}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:6798ed47273bffd5a106f045', 'token_count': 21}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:8816897208265a553cb5d31a', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:36473eb58ec5ed8a4c78bb47', 'token_count': 70}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:c9f48869ea1bdd88801b8126', 'token_count': 36}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:457081e45d261fd6f12205ba', 'token_count': 16}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:ff16e87ae8de1e2818764bcb', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:eefba80162e379f0c71449ad', 'token_count': 53}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:77e1e00e733cc1110dc0d134', 'token_count': 24}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:23d2573df7497715c27f7070', 'token_count': 10}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:24c10ed18976a4ef7fd1ee67', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:01321ccec4940708a6e270d4', 'token_count': 41}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:3a9a855eebf964223c8b6236', 'token_count': 9}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:597c35f38478fe532df3296e', 'token_count': 4}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:e0561abe09ae70c5fde1a24e', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:29d0afee0212be62dcad280f', 'token_count': 35}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:d6ad6ae1b6bf2ee6215ede7b', 'token_count': 10}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:f75e1cf07f47d7d8953a451a', 'token_count': 10}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:eae92995ff2549770d850b74', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:96de33327e8221eb49095387', 'token_count': 33}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:31be1fb06badce18fd44c16a', 'token_count': 30}
     {'action': 'archived', 'block_id': '7fb125cf0fc2220d13ba5387133ce3e6', 'kind': 'archive', 'source': 'context-state', 'reason': 'emergency', 'token_count': 80}

   仓库归档总数: 3
     gen1: token_count=71 source_refs属性=20条 / JSON内=0条
       完整 JSON: {"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": ["发布。"], "source_refs": [], "todo_remaining": [], "verification_status": []}
       source_refs(属性): ['message:a3eaf53e46764e6dcf04629b', 'message:d121ce69d3449946ffa015aa', 'message:2262d0fca860f3a8f9cdb0bc', 'message:f99dd4b69045c55ff1bc765e', 'message:6798ed47273bffd5a106f045', 'message:8816897208265a553cb5d31a', 'message:36473eb58ec5ed8a4c78bb47', 'message:c9f48869ea1bdd88801b8126', 'message:457081e45d261fd6f12205ba', 'message:ff16e87ae8de1e2818764bcb', 'message:eefba80162e379f0c71449ad', 'message:77e1e00e733cc1110dc0d134', 'message:23d2573df7497715c27f7070', 'message:24c10ed18976a4ef7fd1ee67', 'message:01321ccec4940708a6e270d4', 'message:3a9a855eebf964223c8b6236', 'message:597c35f38478fe532df3296e', 'message:e0561abe09ae70c5fde1a24e', 'message:29d0afee0212be62dcad280f', 'message:d6ad6ae1b6bf2ee6215ede7b']
     gen2: token_count=77 source_refs属性=4条 / JSON内=0条
       完整 JSON: {"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": ["补充竞品份额对比。"], "source_refs": [], "todo_remaining": [], "verification_status": []}
       source_refs(属性): ['message:f75e1cf07f47d7d8953a451a', 'message:eae92995ff2549770d850b74', 'message:96de33327e8221eb49095387', 'message:31be1fb06badce18fd44c16a']
     gen3: token_count=80 source_refs属性=4条 / JSON内=0条
       完整 JSON: {"decisions_reasons": ["", "v1.1已发布，4节齐全。"], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": [], "source_refs": [], "todo_remaining": [], "verification_status": []}
       source_refs(属性): ['message:31afd78dbe7e8dcf785455cd', 'message:7a4010909dbeb4e0c7393918', 'message:e4f76030d94c64904952833e', 'message:b1ec5511d809c17140d907b8']

   -> 追加第 9 轮真实对话，进入下一次压缩

########################################################################
########## 第 4 次压缩 (emergency=True) ##########
########################################################################
--- 压缩前 输入: 37 条 ---
  [ 0] system    你是 Memoli 智能体。安全规则：不得删除证据；每步必须有依据。
  [ 1] user      请分析 Q3 销售数据，写一份结论报告，并保留全部计算证据。
  [ 2] assistant   [tool_call:read_sales({"quarter":"2024Q3"})]
  [ 3] tool      Q3营收¥1,240,500，环比+12.3%。华北¥508,405(41%)、华南¥409,365(33%)、华东¥322,730(26%)。退货率2.1%。证据E1-E5：订单2391单、退货260单、净营收¥1,214,085、客单价¥518、复购率31%。
  [ 4] assistant 已读取Q3数据，华北占比最高。下一步核对退货率与上月差异，确认风险来源。
  [ 5] user      继续核对退货率与上月差异，定位上升来源。
  [ 6] assistant   [tool_call:compare({"metric":"return_rate","periods":["2024-08","2024-09"]})]
  [ 7] tool      M8退货率1.8%(236单)，M9退货率2.4%(260单)，环比+0.6pp。增量主要来自华北(+18单)。证据E6-E8：华北M8退货41单→M9退货59单、增量集中在3C品类、华南华东基本持平。
  [ 8] assistant 退货率上升源自华北3C品类。决策：报告标注风险，建议复核华北3C售后流程。
  [ 9] user      把结论和证据整理进报告草稿。
  [10] assistant   [tool_call:write_doc({"title":"Q3销售分析","sections":3})]
  [11] tool      已写入《Q3销售分析》草稿，3节：概览/区域拆解/风险与建议；证据索引E1-E12嵌入正文。文档ID doc-2024Q3-001，存于/drafts/。
  [12] assistant 草稿完成，3节+证据E1-E12。等你确认发布或先自检。
  [13] user      发布前做一次自检。
  [14] assistant   [tool_call:self_check({"doc":"doc-2024Q3-001"})]
  [15] tool      自检通过：营收三处交叉一致(¥1,240,500)；证据E1-E12齐全；结论有据；无遗漏。风险项已标注。
  [16] assistant 自检通过，可发布。
  [17] user      发布。
  [18] assistant   [tool_call:publish({"doc":"doc-2024Q3-001","version":"1.0"})]
  [19] tool      已发布《Q3销售分析》v1.0至/reports/2024Q3/，全员可读。时间戳2024-10-15T09:30:00。
  [20] assistant 已发布v1.0，任务闭环。
  [21] user      补充竞品份额对比。
  [22] assistant   [tool_call:competitor({"market":"3C","quarter":"2024Q3"})]
  [23] tool      竞品A份额18.2%、B 12.5%，我司15.1%排第三。证据E13：华北3C我司份额22%居首。
  [24] assistant 已补充竞品对比，我司华北3C份额第一。建议在报告追加竞品节。
  [25] user      把竞品对比并入报告，发布v1.1。
  [26] assistant   [tool_call:publish({"doc":"doc-2024Q3-001","version":"1.1","merge":["competitor"]})]
  [27] tool      已发布v1.1，新增第4节竞品对比，证据E13并入。时间戳2024-10-15T10:05:00。
  [28] assistant v1.1已发布，4节齐全。
  [29] user      把本次任务归档到知识库。
  [30] assistant   [tool_call:archive_task({"task":"Q3-sales-report"})]
  [31] tool      已归档：任务Q3-sales-report，关联文档v1.1、证据E1-E13、决策3条。知识条目K-2024-Q3-07。
  [32] assistant 已归档K-2024-Q3-07，任务结束。
  [33] user      做一次季度复盘小结。
  [34] assistant   [tool_call:summarize({"scope":"Q3","kind":"retrospective"})]
  [35] tool      复盘：营收+12.3%达标；退货率上升为风险项；报告v1.1已发布并归档。行动项2条。
  [36] assistant 复盘完成，2条行动项已记录。
   输入 tokens = 1522  (available=630, emergency_target=567)
--- 压缩后 candidate: 9 条 ---
  [ 0] system    你是 Memoli 智能体。安全规则：不得删除证据；每步必须有依据。
  [ 1] system    <context_archive generation="1">
{"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": ["发布。"], "source_refs": [], "todo_remaining": [], "verification_status": []}
</context_archive>
  [ 2] system    <context_archive generation="2">
{"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": ["补充竞品份额对比。"], "source_refs": [], "todo_remaining": [], "verification_status": []}
</context_archive>
  [ 3] system    <context_archive generation="3">
{"decisions_reasons": ["", "v1.1已发布，4节齐全。"], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": [], "source_refs": [], "todo_remaining": [], "verification_status": []}
</context_archive>
  [ 4] system    <context_archive generation="4">
{"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": [], "source_refs": [], "todo_remaining": [], "verification_status": []}
</context_archive>
  [ 5] user      做一次季度复盘小结。
  [ 6] assistant   [tool_call:summarize({"scope":"Q3","kind":"retrospective"})]
  [ 7] tool      复盘：营收+12.3%达标；退货率上升为风险项；报告v1.1已发布并归档。行动项2条。
  [ 8] assistant 复盘完成，2条行动项已记录。
   输出 tokens = 592  usage_ratio=0.940  archive_generation=4

   诊断:
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:a3eaf53e46764e6dcf04629b', 'token_count': 29}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:d121ce69d3449946ffa015aa', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:2262d0fca860f3a8f9cdb0bc', 'token_count': 71}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:f99dd4b69045c55ff1bc765e', 'token_count': 36}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:6798ed47273bffd5a106f045', 'token_count': 21}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:8816897208265a553cb5d31a', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:36473eb58ec5ed8a4c78bb47', 'token_count': 70}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:c9f48869ea1bdd88801b8126', 'token_count': 36}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:457081e45d261fd6f12205ba', 'token_count': 16}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:ff16e87ae8de1e2818764bcb', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:eefba80162e379f0c71449ad', 'token_count': 53}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:77e1e00e733cc1110dc0d134', 'token_count': 24}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:23d2573df7497715c27f7070', 'token_count': 10}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:24c10ed18976a4ef7fd1ee67', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:01321ccec4940708a6e270d4', 'token_count': 41}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:3a9a855eebf964223c8b6236', 'token_count': 9}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:597c35f38478fe532df3296e', 'token_count': 4}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:e0561abe09ae70c5fde1a24e', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:29d0afee0212be62dcad280f', 'token_count': 35}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:d6ad6ae1b6bf2ee6215ede7b', 'token_count': 10}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:f75e1cf07f47d7d8953a451a', 'token_count': 10}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:eae92995ff2549770d850b74', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:96de33327e8221eb49095387', 'token_count': 33}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:31be1fb06badce18fd44c16a', 'token_count': 30}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:31afd78dbe7e8dcf785455cd', 'token_count': 15}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:7a4010909dbeb4e0c7393918', 'token_count': 0}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:e4f76030d94c64904952833e', 'token_count': 32}
     {'action': 'deduplicated', 'block_id': '', 'kind': 'trajectory', 'source': 'session', 'reason': 'already-compacted-by:message:b1ec5511d809c17140d907b8', 'token_count': 10}
     {'action': 'archived', 'block_id': 'cd805c9670019c4286f5eb6586e3bd7c', 'kind': 'archive', 'source': 'context-state', 'reason': 'emergency', 'token_count': 68}

   仓库归档总数: 4
     gen1: token_count=71 source_refs属性=20条 / JSON内=0条
       完整 JSON: {"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": ["发布。"], "source_refs": [], "todo_remaining": [], "verification_status": []}
       source_refs(属性): ['message:a3eaf53e46764e6dcf04629b', 'message:d121ce69d3449946ffa015aa', 'message:2262d0fca860f3a8f9cdb0bc', 'message:f99dd4b69045c55ff1bc765e', 'message:6798ed47273bffd5a106f045', 'message:8816897208265a553cb5d31a', 'message:36473eb58ec5ed8a4c78bb47', 'message:c9f48869ea1bdd88801b8126', 'message:457081e45d261fd6f12205ba', 'message:ff16e87ae8de1e2818764bcb', 'message:eefba80162e379f0c71449ad', 'message:77e1e00e733cc1110dc0d134', 'message:23d2573df7497715c27f7070', 'message:24c10ed18976a4ef7fd1ee67', 'message:01321ccec4940708a6e270d4', 'message:3a9a855eebf964223c8b6236', 'message:597c35f38478fe532df3296e', 'message:e0561abe09ae70c5fde1a24e', 'message:29d0afee0212be62dcad280f', 'message:d6ad6ae1b6bf2ee6215ede7b']
     gen2: token_count=77 source_refs属性=4条 / JSON内=0条
       完整 JSON: {"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": ["补充竞品份额对比。"], "source_refs": [], "todo_remaining": [], "verification_status": []}
       source_refs(属性): ['message:f75e1cf07f47d7d8953a451a', 'message:eae92995ff2549770d850b74', 'message:96de33327e8221eb49095387', 'message:31be1fb06badce18fd44c16a']
     gen3: token_count=80 source_refs属性=4条 / JSON内=0条
       完整 JSON: {"decisions_reasons": ["", "v1.1已发布，4节齐全。"], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": [], "source_refs": [], "todo_remaining": [], "verification_status": []}
       source_refs(属性): ['message:31afd78dbe7e8dcf785455cd', 'message:7a4010909dbeb4e0c7393918', 'message:e4f76030d94c64904952833e', 'message:b1ec5511d809c17140d907b8']
     gen4: token_count=68 source_refs属性=4条 / JSON内=0条
       完整 JSON: {"decisions_reasons": [], "facts_evidence": [], "failure_paths": [], "files_artifacts": [], "goal_constraints": [], "source_refs": [], "todo_remaining": [], "verification_status": []}
       source_refs(属性): ['message:c78b95007b3b33d667c98e80', 'message:551a43e362a3ac837bfca34d', 'message:31aebd68edca4e752a58d51b', 'message:a6b04f645f3c8d4c3f526bf7']

   -> 追加第 10 轮真实对话，进入下一次压缩

########################################################################
########## 第 5 次压缩 (emergency=True) ##########
########################################################################
--- 压缩前 输入: 41 条 ---
  [ 0] system    你是 Memoli 智能体。安全规则：不得删除证据；每步必须有依据。
  [ 1] user      请分析 Q3 销售数据，写一份结论报告，并保留全部计算证据。
  [ 2] assistant   [tool_call:read_sales({"quarter":"2024Q3"})]
  [ 3] tool      Q3营收¥1,240,500，环比+12.3%。华北¥508,405(41%)、华南¥409,365(33%)、华东¥322,730(26%)。退货率2.1%。证据E1-E5：订单2391单、退货260单、净营收¥1,214,085、客单价¥518、复购率31%。
  [ 4] assistant 已读取Q3数据，华北占比最高。下一步核对退货率与上月差异，确认风险来源。
  [ 5] user      继续核对退货率与上月差异，定位上升来源。
  [ 6] assistant   [tool_call:compare({"metric":"return_rate","periods":["2024-08","2024-09"]})]
  [ 7] tool      M8退货率1.8%(236单)，M9退货率2.4%(260单)，环比+0.6pp。增量主要来自华北(+18单)。证据E6-E8：华北M8退货41单→M9退货59单、增量集中在3C品类、华南华东基本持平。
  [ 8] assistant 退货率上升源自华北3C品类。决策：报告标注风险，建议复核华北3C售后流程。
  [ 9] user      把结论和证据整理进报告草稿。
  [10] assistant   [tool_call:write_doc({"title":"Q3销售分析","sections":3})]
  [11] tool      已写入《Q3销售分析》草稿，3节：概览/区域拆解/风险与建议；证据索引E1-E12嵌入正文。文档ID doc-2024Q3-001，存于/drafts/。
  [12] assistant 草稿完成，3节+证据E1-E12。等你确认发布或先自检。
  [13] user      发布前做一次自检。
  [14] assistant   [tool_call:self_check({"doc":"doc-2024Q3-001"})]
  [15] tool      自检通过：营收三处交叉一致(¥1,240,500)；证据E1-E12齐全；结论有据；无遗漏。风险项已标注。
  [16] assistant 自检通过，可发布。
  [17] user      发布。
  [18] assistant   [tool_call:publish({"doc":"doc-2024Q3-001","version":"1.0"})]
  [19] tool      已发布《Q3销售分析》v1.0至/reports/2024Q3/，全员可读。时间戳2024-10-15T09:30:00。
  [20] assistant 已发布v1.0，任务闭环。
  [21] user      补充竞品份额对比。
  [22] assistant   [tool_call:competitor({"market":"3C","quarter":"2024Q3"})]
  [23] tool      竞品A份额18.2%、B 12.5%，我司15.1%排第三。证据E13：华北3C我司份额22%居首。
  [24] assistant 已补充竞品对比，我司华北3C份额第一。建议在报告追加竞品节。
  [25] user      把竞品对比并入报告，发布v1.1。
  [26] assistant   [tool_call:publish({"doc":"doc-2024Q3-001","version":"1.1","merge":["competitor"]})]
  [27] tool      已发布v1.1，新增第4节竞品对比，证据E13并入。时间戳2024-10-15T10:05:00。
  [28] assistant v1.1已发布，4节齐全。
  [29] user      把本次任务归档到知识库。
  [30] assistant   [tool_call:archive_task({"task":"Q3-sales-report"})]
  [31] tool      已归档：任务Q3-sales-report，关联文档v1.1、证据E1-E13、决策3条。知识条目K-2024-Q3-07。
  [32] assistant 已归档K-2024-Q3-07，任务结束。
  [33] user      做一次季度复盘小结。
  [34] assistant   [tool_call:summarize({"scope":"Q3","kind":"retrospective"})]
  [35] tool      复盘：营收+12.3%达标；退货率上升为风险项；报告v1.1已发布并归档。行动项2条。
  [36] assistant 复盘完成，2条行动项已记录。
  [37] user      跟踪上月的退货率行动项。
  [38] assistant   [tool_call:track_action({"action":"return-rate-review"})]
  [39] tool      行动项R-0812：华北3C售后流程复核，状态进行中，预计11月完成。
  [40] assistant 行动项R-0812进行中，11月到期。
   输入 tokens = 1661  (available=630, emergency_target=567)

!!! 压缩失败: ContextBudgetExhausted: compiled context exceeds model budget
   (真实 reasoner 此时会切换到 LLM 归档 TaskAwareCompactor；连续失败达 compaction_failure_limit=2 则抛 ContextCompactionCircuitOpen 熔断)
```
