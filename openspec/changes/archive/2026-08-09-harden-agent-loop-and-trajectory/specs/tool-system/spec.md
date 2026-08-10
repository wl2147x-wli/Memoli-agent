## ADDED Requirements

### Requirement: Required evidence failure boundary

必需轨迹证据写入失败时，系统 SHALL 停止新的模型和工具操作；Observer 插件失败不得改变已产生的正常业务结果，Policy 插件失败 SHALL 在工具副作用前阻止执行。

#### Scenario: Checkpoint side effect was committed
- **WHEN** 工作 checkpoint 已更新但对应必需轨迹写入失败
- **THEN** turn SHALL 以 `trace-write-failed` 终止
- **AND** SHALL NOT 发起后续模型或工具调用

#### Scenario: Observer recording fails
- **WHEN** 只读 Observer hook 或其诊断记录失败
- **THEN** 主对话 SHALL 继续使用未被 Observer 修改的结果
