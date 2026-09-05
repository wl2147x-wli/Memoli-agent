# 编码：utf-8
"""Keep the suite out of the developer's real workspace.

Whatever a test loads config for, ``agent_workspace`` ends up pointing at the
directory the person running the suite actually uses, and anything that resolves
a path without pinning one down writes there: the memory files, the scheduler
store and the tmp directory are all reachable that way.

Only that one key is redirected, and only for the session. Loading the config
outright would be worse than the problem: tests would inherit the developer's
model, language and channel settings, and start passing or failing on them.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True, scope="session")
def workspace_out_of_the_way():
    import config as config_module

    with tempfile.TemporaryDirectory(prefix="cow-tests-") as tmp:
        workspace = os.path.join(tmp, "cow")
        real_load = config_module.load_config

        def load_then_redirect():
            real_load()
            config_module.conf()["agent_workspace"] = workspace

        # 现在申请从未加载的测试，并在任何之后重新申请
        # 这样做，因为加载会将值替换为真实值。
        config_module.conf()["agent_workspace"] = workspace
        config_module.load_config = load_then_redirect

        # 集合在运行之前导入每个测试模块，以及一个模块
        # 在导入时加载配置可以已经留下注册表或存储
        # 解决了与真实道路相反的问题。放下那些。
        _forget_resolved_paths()
        try:
            yield workspace
        finally:
            config_module.load_config = real_load


def _forget_resolved_paths():
    from agent.memory import clear_conversation_store_cache
    from agent.memory.config import reset_memory_configs
    from agent.registry import set_agent_registry

    set_agent_registry(None)
    reset_memory_configs()
    clear_conversation_store_cache()
