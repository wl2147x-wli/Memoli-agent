"""LLM provider 抽象层。

未来职责：

- 统一不同模型厂商的 chat 接口。
- 解析 tool calls。
- 支持 streaming、retry、timeout 和上下文过长处理。
"""
