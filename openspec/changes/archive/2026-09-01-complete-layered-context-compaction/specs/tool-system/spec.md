## MODIFIED Requirements

### Requirement: Faithful raw tool trajectory

启用轨迹记录时，系统 SHALL 保存足以按顺序还原模型所见内容、模型工具意图、实际工具执行和模型所收结果的 canonical 客观事实；大型结果 SHALL 同时保留原始脱敏 payload 与绑定 conversation epoch 的冻结预览/引用，并 SHALL 将评价、隐藏 reasoning 与训练派生数据排除在原始事件之外。

#### Scenario: Tool call completes

- **WHEN** 已注册工具成功、失败、超时或产生控制信号
- **THEN** 原始轨迹 SHALL 保存 epoch、turn/message 序号、模型可见 schema、tool call id、工具名、模型原始参数、实际执行参数、时序、状态和错误
- **AND** SHALL 保存原始脱敏输出以及实际返回模型的有界输出或稳定受管引用

#### Scenario: Large tool result is previewed

- **WHEN** 工具原始脱敏结果超过模型可见预算
- **THEN** 轨迹 SHALL 保存原文 payload 引用、epoch、tool call id、内容哈希、原始/可见大小、转换标志和冻结预览
- **AND** 后续上下文恢复 SHALL 验证模型所见预览与首次提交版本一致

#### Scenario: Preview validation fails during restoration

- **WHEN** 冻结预览的 epoch、tool call id、内容哈希或 payload reference 与 canonical turn 不一致
- **THEN** Runtime SHALL 排除整个受影响 turn 或以可观察 tool-protocol 错误结束
- **AND** SHALL NOT 只注入 tool call、只注入 result 或重新生成不一致预览

#### Scenario: Explicit argument expansion occurs

- **WHEN** 文件引用或其他已声明机制把模型原始参数展开为实际执行参数
- **THEN** 轨迹 SHALL 分别保存原始表示和实际执行表示
- **AND** 工具结果 SHALL 明确告知发生了该转换

#### Scenario: Raw trajectory is persisted

- **WHEN** 工具事实成功提交到 SQLite
- **THEN** 原始事件 SHALL NOT 包含 reward、Rubric、成功标签、正确工具标签、失败归因或 SFT/RL 标签
- **AND** SHALL NOT 自动进入 Memory、Evolution 或 Post-training

#### Scenario: Required trace write fails before a side effect

- **WHEN** 副作用工具的意图无法在执行前成功提交
- **THEN** 系统 SHALL NOT 执行该副作用
- **AND** 当前 turn SHALL 以可观察的轨迹写入失败结束
