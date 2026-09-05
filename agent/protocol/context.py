class TeamContext:
    def __init__(self, name: str, description: str, rule: str, agents: list, max_steps: int = 100):
        """
        Initialize the TeamContext with a name, description, rules, a list of agents, and a user question.
        :param name: The name of the group context.
        :param description: A description of the group context.
        :param rule: The rules governing the group context.
        :param agents: A list of agents in the context.
        """
        self.name = name
        self.description = description
        self.rule = rule
        self.agents = agents
        self.user_task = ""  # 为向后兼容保留
        self.task = None  # 稍后会填入 Task 实例
        self.model = None  # 稍后会填入 LLMModel 实例
        self.task_short_name = None  # 任务目录名
        # 已经执行过的代理的输出列表
        self.agent_outputs: list = []
        self.current_steps = 0
        self.max_steps = max_steps


class AgentOutput:
    def __init__(self, agent_name: str, output: str):
        self.agent_name = agent_name
        self.output = output