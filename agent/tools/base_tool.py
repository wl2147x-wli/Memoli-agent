from enum import Enum
from typing import Any, Optional
from common.log import logger
import copy


class ToolStage(Enum):
    """Enum representing tool decision stages"""
    PRE_PROCESS = "pre_process"  # 需由代理主动调用的工具
    POST_PROCESS = "post_process"  # 在 Final_answer 之后自动执行的工具


class ToolResult:
    """Tool execution result

    ``result`` is what the model reads, so it is written for a model: JSON,
    exit codes, whatever parses cleanly. ``display`` is the same outcome
    written for a person, and clients render it instead when it is set. A tool
    whose result is already readable leaves it None and the two stay one thing.
    """

    def __init__(self, status: str = None, result: Any = None, ext_data: Any = None,
                 display: Optional[str] = None):
        self.status = status
        self.result = result
        self.ext_data = ext_data
        self.display = display

    @staticmethod
    def success(result, ext_data: Any = None, display: Optional[str] = None):
        return ToolResult(status="success", result=result, ext_data=ext_data, display=display)

    @staticmethod
    def fail(result, ext_data: Any = None, display: Optional[str] = None):
        return ToolResult(status="error", result=result, ext_data=ext_data, display=display)


def is_tool_available(tool) -> bool:
    """Availability of a tool that may not implement the check at all.

    Errs towards offering it: a check that breaks should cost the agent a log
    line, not a capability.
    """
    try:
        return bool(tool.is_available())
    except Exception as e:
        logger.debug(f"[{getattr(tool, 'name', '?')}] availability check failed: {e}")
        return True


def renders_own_cards(tool, arguments: dict) -> bool:
    """Whether a call reports itself. Errs towards the generic card, which is
    never wrong, only sometimes redundant."""
    if tool is None:
        return False
    try:
        return bool(tool.renders_own_cards(arguments))
    except Exception as e:
        logger.debug(f"[{getattr(tool, 'name', '?')}] card check failed: {e}")
        return False


class BaseTool:
    """Base class for all tools."""

    # 默认决策阶段是预处理
    stage = ToolStage.PRE_PROCESS

    # 类属性必须被继承
    name: str = "base_tool"
    description: str = "Base tool"
    params: dict = {}  # 存储 JSON 架构
    model: Optional[Any] = None  # LLM模型实例，类型取决于机器人实现
    progress_callback = None
    cancel_event = None
    event_callback = None
    # 当前正在执行的这条调用的 ID，由代理循环在每次调用时注入。
    # 通过 `emit_event` 自行上报工作的工具，需要它来指明
    # 这些工作在客户端界面中归属于哪一条记录。
    tool_call_id: Optional[str] = None
    # 工作区目录，每次运行时注入。之所以在此声明，是为了保证
    # 工具在解析相对路径时不会悄悄错过这份注入。
    cwd: Optional[str] = None
    # 同一轮内对同一工具的多次调用是否允许并发执行。
    # 默认关闭：代理循环按模型要求的顺序逐个运行工具，
    # 大多数工具也正是按这种预期编写的。只有当满足
    # “构造上彼此独立、且慢到排队成为主要开销”时才应开启。
    parallel_safe: bool = False

    def renders_own_cards(self, arguments: dict) -> bool:
        """Whether this call reports itself, so the caller should stay quiet.

        A tool that runs several units of work at once can say which of them
        is still going, and the generic card wrapped around the whole call
        then shows the same thing a second time with every unit's arguments
        and every unit's output run together. Answering True for such a call
        leaves only the cards the tool emits itself. A failure that stops the
        tool before it emits anything still gets a card, otherwise it would
        vanish.
        """
        return False

    def is_available(self) -> bool:
        """Whether this tool should be offered to the model right now.

        Read once per turn, so a tool behind a setting the user can change
        mid-conversation answers for the setting as it stands rather than as
        it stood when the Agent was built. A tool that is always usable - the
        overwhelming majority - leaves this alone.
        """
        return True

    def is_cancelled(self) -> bool:
        """True once the user asked to stop the run.

        Long-running tools should poll this and abort early; the agent loop
        checkpoint right after the tool returns turns it into a clean cancel.
        """
        event = getattr(self, "cancel_event", None)
        return event is not None and event.is_set()

    def report_progress(self, message: str):
        callback = getattr(self, "progress_callback", None)
        if not callback:
            return
        try:
            callback(str(message))
        except Exception as e:
            logger.debug(f"[{self.name}] progress callback failed: {e}")

    def emit_event(self, event_type: str, data: dict):
        """Report a unit of work running inside this call.

        One call is one entry in the client's view of the run. A tool that
        drives several independent pieces of work at once - and only such a
        tool - can announce each of them here, so the client can follow them
        separately instead of watching a single spinner stand in for all of
        them. Silent when nothing is listening.
        """
        callback = getattr(self, "event_callback", None)
        if not callback:
            return
        try:
            callback(event_type, data)
        except Exception as e:
            logger.debug(f"[{self.name}] event callback failed: {e}")

    def get_json_schema(self) -> dict:
        """The tool as the model sees it.

        Bound to the instance, not the class, so a tool whose name, wording or
        parameters depend on runtime state can override any of them in
        __init__ and have both this and the agent loop's direct read of
        `.description` agree.
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.params
        }

    def execute_tool(self, params: dict) -> ToolResult:
        try:
            return self.execute(params)
        except Exception as e:
            logger.error(e)

    def execute(self, params: dict) -> ToolResult:
        """Specific logic to be implemented by subclasses"""
        raise NotImplementedError

    @classmethod
    def _parse_schema(cls) -> dict:
        """Convert JSON Schema to Pydantic fields"""
        fields = {}
        for name, prop in cls.params["properties"].items():
            # 将 JSON Schema 类型映射为对应的 Python 类型
            type_map = {
                "string": str,
                "number": float,
                "integer": int,
                "boolean": bool,
                "array": list,
                "object": dict
            }
            fields[name] = (
                type_map[prop["type"]],
                prop.get("default", ...)
            )
        return fields

    def should_auto_execute(self, context) -> bool:
        """
        Determine if this tool should be automatically executed based on context.

        :param context: The agent context
        :return: True if the tool should be executed, False otherwise
        """
        # 只有处于后处理阶段的工具才会自动执行
        return self.stage == ToolStage.POST_PROCESS

    def close(self):
        """
        Close any resources used by the tool.
        This method should be overridden by tools that need to clean up resources
        such as browser connections, file handles, etc.

        By default, this method does nothing.
        """
        pass
