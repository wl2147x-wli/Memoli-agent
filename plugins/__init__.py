from .event import *
from .plugin import *
from .plugin_manager import PluginManager

instance = PluginManager()

register = instance.register
# load_plugins = 实例.load_plugins
# 发射事件 = 实例.发射事件
