"""
Memory manager for AgentMesh

Provides high-level interface for memory operations
"""

import os
from typing import List, Optional, Dict, Any
from pathlib import Path
import hashlib
from datetime import datetime, timedelta

from agent.memory.config import MemoryConfig, get_default_memory_config
from agent.memory.storage import MemoryStorage, MemoryChunk, SearchResult
from agent.memory.chunker import TextChunker
from agent.memory.embedding import EmbeddingProvider, EmbeddingCache
from agent.memory.summarizer import MemoryFlushManager, create_memory_files_if_needed


class MemoryManager:
    """
    Memory manager with hybrid search capabilities
    
    Provides long-term memory for agents with vector and keyword search
    """
    
    def __init__(
        self,
        config: Optional[MemoryConfig] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        llm_model: Optional[Any] = None
    ):
        """
        Initialize memory manager
        
        Args:
            config: Memory configuration (uses global config if not provided)
            embedding_provider: Custom embedding provider (optional)
            llm_model: LLM model for summarization (optional)
        """
        self.config = config or get_default_memory_config()
        
        # 初始化存储
        db_path = self.config.get_db_path()
        self.storage = MemoryStorage(db_path)
        
        # 初始化分块器
        self.chunker = TextChunker(
            max_tokens=self.config.chunk_max_tokens,
            overlap_tokens=self.config.chunk_overlap_tokens
        )
        
        # 嵌入提供程序由调用方持有（agent_initializer 是规范入口，
        # 负责处理遗留配置/显式配置以及状态校验）。
        # 传入 None 时，内存会降级为仅关键字搜索。
        # 若在这里偷偷重新初始化 provider，就会绕过调用方的
        # 状态检查，并有损坏索引的风险。
        self.embedding_provider = embedding_provider
        if self.embedding_provider is None:
            from common.log import logger
            logger.info(
                "[MemoryManager] No embedding provider; memory will use keyword search only"
            )

        # 用于查询嵌入的缓存（避免会话中冗余的 API 调用）
        self._embedding_cache = EmbeddingCache()


        # 初始化内存刷新管理器
        workspace_dir = self.config.get_workspace()
        self.flush_manager = MemoryFlushManager(
            workspace_dir=workspace_dir,
            llm_model=llm_model
        )
        
        # 确保工作区目录存在
        self._init_workspace()
        
        self._dirty = False
    
    def _init_workspace(self):
        """Initialize workspace directories"""
        memory_dir = self.config.get_memory_dir()
        memory_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建默认内存文件
        workspace_dir = self.config.get_workspace()
        create_memory_files_if_needed(workspace_dir)
    
    async def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        max_results: Optional[int] = None,
        min_score: Optional[float] = None,
        include_shared: bool = True
    ) -> List[SearchResult]:
        """
        Search memory with hybrid search (vector + keyword)
        
        Args:
            query: Search query
            user_id: User ID for scoped search
            max_results: Maximum results to return
            min_score: Minimum score threshold
            include_shared: Include shared memories
            
        Returns:
            List of search results sorted by relevance
        """
        max_results = max_results or self.config.max_results
        min_score = min_score or self.config.min_score
        
        # 确定范围
        scopes = []
        if include_shared:
            scopes.append("shared")
        if user_id:
            scopes.append("user")
        
        if not scopes:
            return []
        
        # 如果需要同步
        if self.config.sync_on_search and self._dirty:
            await self.sync()
        
        from common.log import logger

        # 执行向量搜索（若嵌入提供程序可用）。
        # 失败时静默降级为仅关键字搜索，不会抛异常。
        vector_results = []
        if self.embedding_provider:
            try:
                provider_name = type(self.embedding_provider).__name__
                model_name = getattr(self.embedding_provider, 'model', '')
                cached = self._embedding_cache.get(query, provider_name, model_name)
                if cached is not None:
                    query_embedding = cached
                else:
                    query_embedding = self.embedding_provider.embed_query(query)
                    self._embedding_cache.put(query, provider_name, model_name, query_embedding)
                vector_results = self.storage.search_vector(
                    query_embedding=query_embedding,
                    user_id=user_id,
                    scopes=scopes,
                    limit=max_results * 2  # 多取一些候选，供合并时筛选
                )
                logger.info(f"[MemoryManager] Vector search found {len(vector_results)} results for query: {query}")
            except Exception as e:
                logger.error(
                    f"[MemoryManager] Vector search failed, falling back to keyword-only: {e}"
                )

        # 执行关键字搜索（当向量失败时也作为后备运行）
        keyword_results = self.storage.search_keyword(
            query=query,
            user_id=user_id,
            scopes=scopes,
            limit=max_results * 2
        )
        logger.info(f"[MemoryManager] Keyword search found {len(keyword_results)} results for query: {query}")

        # 合并结果
        merged = self._merge_results(
            vector_results,
            keyword_results,
            self.config.vector_weight,
            self.config.keyword_weight
        )

        # 按最低分数和限制过滤
        filtered = [r for r in merged if r.score >= min_score]
        return filtered[:max_results]
    
    async def add_memory(
        self,
        content: str,
        user_id: Optional[str] = None,
        scope: str = "shared",
        source: str = "memory",
        path: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Add new memory content
        
        Args:
            content: Memory content
            user_id: User ID for user-scoped memory
            scope: Memory scope ("shared", "user", "session")
            source: Memory source ("memory" or "session")
            path: File path (auto-generated if not provided)
            metadata: Additional metadata
        """
        if not content.strip():
            return
        
        # 如果未提供则生成路径
        if not path:
            content_hash = hashlib.md5(content.encode('utf-8')).hexdigest()[:8]
            if user_id and scope == "user":
                path = f"memory/users/{user_id}/memory_{content_hash}.md"
            else:
                path = f"memory/shared/memory_{content_hash}.md"
        
        # 将内容切块
        chunks = self.chunker.chunk_text(content)
        
        # 生成嵌入（如果提供者可用）
        texts = [chunk.text for chunk in chunks]
        if self.embedding_provider:
            embeddings = self.embedding_provider.embed_batch(texts)
        else:
            # 没有嵌入，只需使用 None
            embeddings = [None] * len(texts)
        
        # 创建内存块
        memory_chunks = []
        for chunk, embedding in zip(chunks, embeddings):
            chunk_id = self._generate_chunk_id(path, chunk.start_line, chunk.end_line)
            chunk_hash = MemoryStorage.compute_hash(chunk.text)
            
            memory_chunks.append(MemoryChunk(
                id=chunk_id,
                user_id=user_id,
                scope=scope,
                source=source,
                path=path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                text=chunk.text,
                embedding=embedding,
                hash=chunk_hash,
                metadata=metadata
            ))
        
        # 保存到存储
        self.storage.save_chunks_batch(memory_chunks)
        
        # 更新文件元数据
        file_hash = MemoryStorage.compute_hash(content)
        self.storage.update_file_metadata(
            path=path,
            source=source,
            file_hash=file_hash,
            mtime=int(os.path.getmtime(__file__)),  # 使用当前时间
            size=len(content)
        )
    
    async def sync(self, force: bool = False):
        """
        Synchronize memory from files.

        Two-pass design to amortize embedding HTTP cost:
          1. Walk all files, chunk those whose hash changed, collect pending
             chunks across files. No embedding calls yet.
          2. Run a single embed_batch over the union of pending chunks (the
             provider auto-paginates by vendor cap), then persist per-file.

        For workspaces with many small files (101 files / ~1 chunk each), this
        cuts ~100 HTTP calls down to ~ceil(total_chunks / vendor_cap).

        Args:
            force: Force full reindex
        """
        memory_dir = self.config.get_memory_dir()
        workspace_dir = self.config.get_workspace()

        files_to_scan: List[tuple] = []  # （文件路径、源、范围、用户 ID）

        memory_file = Path(workspace_dir) / "MEMORY.md"
        if memory_file.exists():
            files_to_scan.append((memory_file, "memory", "shared", None))

        if memory_dir.exists():
            for file_path in memory_dir.rglob("*.md"):
                rel_parts = file_path.relative_to(workspace_dir).parts
                if any(part.startswith('.') for part in rel_parts):
                    continue
                # 梦境日记是 Deep Dream 流程生成的叙事性复述，
                # 其中事实内容已被提炼进 MEMORY.md；再索引它们只会
                # 产生大量近似重复的条目，检索时挤占
                # 权威内容的位置。
                if "dreams" in rel_parts:
                    continue
                if "daily" in rel_parts:
                    if "users" in rel_parts or len(rel_parts) > 3:
                        user_idx = rel_parts.index("daily") + 1
                        user_id = rel_parts[user_idx] if user_idx < len(rel_parts) else None
                        scope = "user"
                    else:
                        user_id = None
                        scope = "shared"
                elif "users" in rel_parts:
                    user_idx = rel_parts.index("users") + 1
                    user_id = rel_parts[user_idx] if user_idx < len(rel_parts) else None
                    scope = "user"
                else:
                    user_id = None
                    scope = "shared"
                files_to_scan.append((file_path, "memory", scope, user_id))

        from config import conf
        if conf().get("knowledge", True):
            # 通过 state_dir 解析，因此没有自己的 knowledge/ 目录的 Agent
            # 会去扫描共享知识库，而不是空的（或缺失的）本地库。
            from common import state_dir
            knowledge_dir = Path(state_dir.knowledge_dir(base=workspace_dir))
            if knowledge_dir.exists():
                for file_path in knowledge_dir.rglob("*.md"):
                    files_to_scan.append((file_path, "knowledge", "shared", None))

        # 第 1 遍：就地分块 + 变更检测。刻意写成内联（而不是
        # 调用 self._prepare_file_for_sync），好让本方法不依赖任何
        # 同级辅助函数——在类对象比方法源码更旧的“部分重载”
        # 场景下依然健壮。
        pending: List[Dict[str, Any]] = []
        workspace_dir_path = self.config.get_workspace()
        for file_path, source, scope, user_id in files_to_scan:
            try:
                content = file_path.read_text(encoding='utf-8')
            except Exception:
                continue
            file_hash = MemoryStorage.compute_hash(content)
            rel_path = str(file_path.relative_to(workspace_dir_path))
            if self.storage.get_file_hash(rel_path) == file_hash:
                continue
            chunks = self.chunker.chunk_text(content)
            if not chunks:
                continue
            pending.append({
                "file_path": file_path,
                "rel_path": rel_path,
                "source": source,
                "scope": scope,
                "user_id": user_id,
                "file_hash": file_hash,
                "chunks": chunks,
                "texts": [c.text for c in chunks],
            })

        if not pending:
            self._dirty = False
            return

        # 第 2 遍：对所有待处理块一次性批量嵌入。
        # 关键：拿到有效嵌入之前，绝不改动索引。
        # 若 embed_batch 失败，就保持现有索引（块与 file_hash）
        # 不动，这样下次同步会重试相同的文件。若写入
        # NULL 嵌入并更新 file_hash，则会把文件标记为
        # “已成功同步”，等于在没有向量的情况下悄悄搁置它。
        all_texts: List[str] = []
        for entry in pending:
            all_texts.extend(entry["texts"])

        if not self.embedding_provider:
            # 完全没有配置提供程序（旧版仅关键字模式）。
            # 那就保留不带嵌入的块——这符合用户的意图。
            all_embeddings: List[Optional[List[float]]] = [None] * len(all_texts)
        else:
            try:
                all_embeddings = self.embedding_provider.embed_batch(all_texts)
            except Exception as e:
                from common.log import logger
                logger.error(
                    f"[MemoryManager] Batch embedding failed for {len(all_texts)} "
                    f"chunks across {len(pending)} files: {e}. "
                    f"Index left untouched; will retry on next sync."
                )
                # 在触碰存储前先退出。self._dirty 仍保持 True，
                # 让调用方知道还有待处理的工作。
                return

        # 第 3 遍：就地持久化，采用与第 1 遍相同的独立自足写法。
        cursor = 0
        for entry in pending:
            n = len(entry["texts"])
            entry_embeddings = all_embeddings[cursor:cursor + n]
            cursor += n

            rel_path = entry["rel_path"]
            self.storage.delete_by_path(rel_path)
            memory_chunks = []
            for chunk, embedding in zip(entry["chunks"], entry_embeddings):
                chunk_id = self._generate_chunk_id(rel_path, chunk.start_line, chunk.end_line)
                chunk_hash = MemoryStorage.compute_hash(chunk.text)
                memory_chunks.append(MemoryChunk(
                    id=chunk_id,
                    user_id=entry["user_id"],
                    scope=entry["scope"],
                    source=entry["source"],
                    path=rel_path,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    text=chunk.text,
                    embedding=embedding,
                    hash=chunk_hash,
                    metadata=None,
                ))
            self.storage.save_chunks_batch(memory_chunks)
            stat = entry["file_path"].stat()
            self.storage.update_file_metadata(
                path=rel_path,
                source=entry["source"],
                file_hash=entry["file_hash"],
                mtime=int(stat.st_mtime),
                size=stat.st_size,
            )

        self._dirty = False

    def flush_memory(
        self,
        messages: list,
        user_id: Optional[str] = None,
        reason: str = "threshold",
        max_messages: int = 10,
        context_summary_callback=None,
    ) -> bool:
        """
        Flush conversation summary to daily memory file.

        Args:
            messages: Conversation message list
            user_id: Optional user ID
            reason: "threshold" | "overflow" | "daily_summary"
            max_messages: Max recent messages to include (0 = all)
            context_summary_callback: Optional callback(str) invoked with the
                daily summary text for in-context injection

        Returns:
            True if flush was dispatched
        """
        success = self.flush_manager.flush_from_messages(
            messages=messages,
            user_id=user_id,
            reason=reason,
            max_messages=max_messages,
            context_summary_callback=context_summary_callback,
        )
        if success:
            self._dirty = True
        return success
    
    def get_status(self) -> Dict[str, Any]:
        """Get memory status"""
        stats = self.storage.get_stats()
        return {
            'chunks': stats['chunks'],
            'files': stats['files'],
            'workspace': str(self.config.get_workspace()),
            'dirty': self._dirty,
            'embedding_enabled': self.embedding_provider is not None,
            'embedding_provider': self.config.embedding_provider if self.embedding_provider else 'disabled',
            'embedding_model': self.config.embedding_model if self.embedding_provider else 'N/A',
            'search_mode': 'hybrid (vector + keyword)' if self.embedding_provider else 'keyword only (FTS5)'
        }
    
    def mark_dirty(self):
        """Mark memory as dirty (needs sync)"""
        self._dirty = True
    
    def close(self):
        """Close memory manager and release resources"""
        self.storage.close()
    
    # 辅助方法
    
    def _generate_chunk_id(self, path: str, start_line: int, end_line: int) -> str:
        """Generate unique chunk ID"""
        content = f"{path}:{start_line}:{end_line}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()
    
    @staticmethod
    def _compute_temporal_decay(path: str, half_life_days: float = 30.0) -> float:
        """
        Compute temporal decay multiplier for dated memory files.
        
        Inspired by OpenClaw's temporal-decay: exponential decay based on file date.
        MEMORY.md and non-dated files are "evergreen" (no decay, multiplier=1.0).
        Daily files like memory/2025-03-01.md decay based on age.
        
        Formula: multiplier = exp(-ln2/half_life * age_in_days)
        """
        import re
        import math
        
        match = re.search(r'(\d{4})-(\d{2})-(\d{2})\.md$', path)
        if not match:
            return 1.0  # 永不衰减：MEMORY.md、未注明日期的文件
        
        try:
            file_date = datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3))
            )
            age_days = (datetime.now() - file_date).days
            if age_days <= 0:
                return 1.0
            
            decay_lambda = math.log(2) / half_life_days
            return math.exp(-decay_lambda * age_days)
        except (ValueError, OverflowError):
            return 1.0
    
    def _merge_results(
        self,
        vector_results: List[SearchResult],
        keyword_results: List[SearchResult],
        vector_weight: float,
        keyword_weight: float
    ) -> List[SearchResult]:
        """Merge vector and keyword search results with temporal decay for dated files"""
        merged_map = {}
        
        for result in vector_results:
            key = (result.path, result.start_line, result.end_line)
            merged_map[key] = {
                'result': result,
                'vector_score': result.score,
                'keyword_score': 0.0
            }
        
        for result in keyword_results:
            key = (result.path, result.start_line, result.end_line)
            if key in merged_map:
                merged_map[key]['keyword_score'] = result.score
            else:
                merged_map[key] = {
                    'result': result,
                    'vector_score': 0.0,
                    'keyword_score': result.score
                }
        
        merged_results = []
        for entry in merged_map.values():
            combined_score = (
                vector_weight * entry['vector_score'] +
                keyword_weight * entry['keyword_score']
            )
            
            # 对带日期的旧内存文件应用时间衰减
            result = entry['result']
            decay = self._compute_temporal_decay(result.path)
            combined_score *= decay
            
            merged_results.append(SearchResult(
                path=result.path,
                start_line=result.start_line,
                end_line=result.end_line,
                score=combined_score,
                snippet=result.snippet,
                source=result.source,
                user_id=result.user_id
            ))
        
        merged_results.sort(key=lambda r: r.score, reverse=True)
        return merged_results
