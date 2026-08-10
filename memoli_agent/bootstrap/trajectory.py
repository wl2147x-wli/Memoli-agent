"""轨迹存储装配。"""

from memoli_agent.agent.trajectory import (
    NullTrajectoryStore,
    SQLiteTrajectoryStore,
    TrajectoryStore,
)
from memoli_agent.bootstrap.config import AppConfig


def build_trajectory_store(config: AppConfig) -> TrajectoryStore:
    """根据配置返回本地 SQLite 或 Null store。"""

    trajectory = config.trajectory
    if not trajectory.enabled:
        return NullTrajectoryStore()
    return SQLiteTrajectoryStore(
        trajectory.database,
        payload_directory=trajectory.payload_directory,
        capture_content=trajectory.capture_content,
        max_inline_bytes=trajectory.max_inline_bytes,
        max_payload_bytes=trajectory.max_payload_bytes,
        sensitive_keys=trajectory.sensitive_keys,
    )
