"""Memoli-agent benchmark adapter."""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

from benchmarks.config import AgentBenchmarkConfig
from benchmarks.datasets.base import (
    BenchmarkMessage,
    BenchmarkPrediction,
    BenchmarkQuestion,
    BenchmarkSample,
)
from memoli_agent.agent.memory.runtime import MemoryMutation, MemoryQuery
from memoli_agent.bootstrap.app import AppRuntime, build_app_runtime
from memoli_agent.bootstrap.config import AppConfig, load_config
from memoli_agent.bus.events import InboundMessage


class MemoliAgentAdapter:
    def __init__(
        self,
        config: AgentBenchmarkConfig,
        dataset_name: str,
        split: str,
    ) -> None:
        self.config = config
        self.dataset_name = dataset_name
        self.split = split
        self.runtime: AppRuntime | None = None
        self.sample_workspace: Path | None = None

    async def reset(self, sample_id: str) -> None:
        workspace_root = Path(self.config.workspace_root)
        sample_workspace = workspace_root / self.dataset_name / self.split / _safe_id(sample_id)
        reset_enabled = self.config.reset_memory_per_sample and self.config.reset_per_sample
        if reset_enabled and sample_workspace.exists():
            _safe_rmtree(sample_workspace, workspace_root)
        sample_workspace.mkdir(parents=True, exist_ok=True)

        app_config = load_config(self.config.config_path)
        app_config = _with_sample_paths(app_config, sample_workspace)
        app_config.channels.cli.enabled = False
        self.runtime = build_app_runtime(app_config)
        self.sample_workspace = sample_workspace

    async def ingest(self, sample: BenchmarkSample) -> None:
        runtime = self._runtime()
        if self.config.ingest_mode == "agent_turn":
            for session in sample.sessions:
                for message in session.messages:
                    await runtime.runner.handle_inbound(
                        InboundMessage(
                            channel="benchmark",
                            chat_id=sample.id,
                            sender=message.speaker or message.role,
                            content=message.content,
                            metadata={
                                "benchmark_phase": "ingest",
                                "session_id": session.id,
                                "message_id": message.id,
                                "dataset": self.dataset_name,
                            },
                        )
                    )
            return

        if self.config.ingest_mode != "memory_write":
            raise ValueError(f"Unsupported ingest_mode: {self.config.ingest_mode}")
        if runtime.memory_runtime is None:
            raise RuntimeError("Memoli memory runtime is disabled.")

        for session in sample.sessions:
            for message in session.messages:
                await runtime.memory_runtime.mutate(
                    MemoryMutation(
                        content=_render_message(sample.id, session.id, message),
                        source=f"{self.dataset_name}:{sample.id}:{session.id}:{message.id}",
                        metadata={
                            "dataset": self.dataset_name,
                            "split": self.split,
                            "sample_id": sample.id,
                            "session_id": session.id,
                            "message_id": message.id,
                            "timestamp": message.timestamp,
                            "role": message.role,
                            "speaker": message.speaker,
                            **message.metadata,
                        },
                    )
                )

    async def answer(
        self, sample: BenchmarkSample, question: BenchmarkQuestion
    ) -> BenchmarkPrediction:
        runtime = self._runtime()
        retrieved_context: list[str] = []
        if self.config.capture_retrieved_context and runtime.memory_runtime is not None:
            result = await runtime.memory_runtime.query(
                MemoryQuery(query=question.question, limit=5)
            )
            retrieved_context = [item.content for item in result.items]

        outbound = await runtime.runner.handle_inbound(
            InboundMessage(
                channel="benchmark",
                chat_id=sample.id,
                sender="benchmark",
                content=question.question,
                metadata={
                    "benchmark_phase": "answer",
                    "dataset": self.dataset_name,
                    "split": self.split,
                    "question_id": question.id,
                    "question_type": question.question_type,
                },
            )
        )
        return BenchmarkPrediction(
            sample_id=sample.id,
            question_id=question.id,
            prediction=outbound.content,
            gold_answers=question.gold_answers,
            retrieved_context=retrieved_context,
            metadata={
                **outbound.metadata,
                "sample_workspace": str(self.sample_workspace or ""),
            },
        )

    async def close(self) -> None:
        self.runtime = None
        self.sample_workspace = None

    def _runtime(self) -> AppRuntime:
        if self.runtime is None:
            raise RuntimeError("MemoliAgentAdapter.reset(sample_id) must be called first.")
        return self.runtime


def _with_sample_paths(config: AppConfig, sample_workspace: Path) -> AppConfig:
    # AppConfig is mutable, but replace top-level sections to avoid sharing nested objects
    # if a caller reuses the loaded config object.
    config = replace(config)
    config.runtime = replace(config.runtime, workspace=str(sample_workspace))
    config.memory = replace(config.memory, path=str(sample_workspace / "memory"))
    config.subagent = replace(config.subagent, root=str(sample_workspace / "subagents"))
    return config


def _render_message(sample_id: str, session_id: str, message: BenchmarkMessage) -> str:
    prefix = f"[sample={sample_id}][session={session_id}][message={message.id}]"
    if message.timestamp:
        prefix += f"[time={message.timestamp}]"
    speaker = message.speaker or message.role
    return f"{prefix} {speaker}: {message.content}"


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value)[:120]


def _safe_rmtree(target: Path, root: Path) -> None:
    resolved_target = target.resolve()
    resolved_root = root.resolve()
    if resolved_target == resolved_root or resolved_root not in resolved_target.parents:
        raise ValueError(f"Refusing to remove unsafe benchmark path: {target}")
    shutil.rmtree(resolved_target)
