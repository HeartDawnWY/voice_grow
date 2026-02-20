"""
向量语义搜索服务

使用 ChromaDB + sentence-transformers 对内容标题做语义向量检索。
解决问题：在线下载的标题（繁体/带修饰词）与用户查询词不匹配。

搜索链：MySQL精确/模糊 → 向量语义搜索 → 在线下载
"""

import asyncio
import logging
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)

# 相似度阈值：低于此分数不返回结果
SIMILARITY_THRESHOLD = 0.72

# ChromaDB 持久化路径（相对于工作目录）
CHROMA_PERSIST_PATH = "./chroma_db"

# 使用多语言小模型（支持中文，约 420MB）
EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"


class VectorSearchService:
    """向量语义搜索服务（ChromaDB + sentence-transformers）"""

    def __init__(self, persist_path: str = CHROMA_PERSIST_PATH):
        self._persist_path = persist_path
        self._client = None
        self._collection = None
        self._model = None
        self._ready = False

    def initialize(self) -> bool:
        """初始化 ChromaDB 客户端和 embedding 模型。

        在主线程同步调用（应用启动时）。
        返回 True 表示初始化成功，False 表示失败（降级模式）。
        """
        try:
            import chromadb
            from sentence_transformers import SentenceTransformer

            self._client = chromadb.PersistentClient(path=self._persist_path)
            self._collection = self._client.get_or_create_collection(
                name="contents",
                metadata={"hnsw:space": "cosine"},  # 余弦相似度
            )
            logger.info(f"ChromaDB 初始化成功: path={self._persist_path}, "
                        f"records={self._collection.count()}")

            logger.info(f"加载 embedding 模型: {EMBEDDING_MODEL}")
            self._model = SentenceTransformer(EMBEDDING_MODEL)
            logger.info("Embedding 模型加载成功")

            self._ready = True
            return True

        except Exception as e:
            logger.warning(f"VectorSearchService 初始化失败（降级为无向量搜索模式）: {e}")
            self._ready = False
            return False

    def _encode(self, text: str) -> List[float]:
        """将文本编码为向量"""
        return self._model.encode(text, normalize_embeddings=True).tolist()

    async def add_content(
        self,
        content_id: int,
        title: str,
        content_type: str,
    ) -> bool:
        """向量化内容标题并写入 ChromaDB。

        Args:
            content_id: MySQL 中的内容 ID
            title: 内容标题（原始，含繁体或修饰词均可）
            content_type: 内容类型（story/music/english）

        Returns:
            True 表示写入成功
        """
        if not self._ready:
            return False
        try:
            loop = asyncio.get_running_loop()
            vector = await loop.run_in_executor(None, self._encode, title)

            self._collection.upsert(
                ids=[str(content_id)],
                embeddings=[vector],
                metadatas=[{"title": title, "content_type": content_type}],
            )
            logger.debug(f"向量写入: id={content_id}, title='{title}'")
            return True
        except Exception as e:
            logger.warning(f"向量写入失败: id={content_id}, title='{title}': {e}")
            return False

    async def search(
        self,
        query: str,
        content_type: Optional[str] = None,
        top_k: int = 3,
    ) -> List[Tuple[int, float, str]]:
        """语义搜索最相似内容。

        Args:
            query: 用户查询词（简体中文）
            content_type: 按内容类型过滤（可选）
            top_k: 返回最多 top_k 条结果

        Returns:
            [(content_id, similarity_score, title), ...] 按相似度降序
            仅返回相似度 >= SIMILARITY_THRESHOLD 的结果
        """
        if not self._ready:
            return []

        try:
            count = self._collection.count()
            if count == 0:
                return []

            loop = asyncio.get_running_loop()
            query_vector = await loop.run_in_executor(None, self._encode, query)

            where = {"content_type": content_type} if content_type else None

            results = self._collection.query(
                query_embeddings=[query_vector],
                n_results=min(top_k, count),
                where=where,
                include=["distances", "metadatas"],
            )

            ids = results["ids"][0]
            # ChromaDB cosine distance: distance = 1 - similarity
            distances = results["distances"][0]
            metadatas = results["metadatas"][0]

            hits = []
            for id_, dist, meta in zip(ids, distances, metadatas):
                similarity = 1.0 - dist
                if similarity >= SIMILARITY_THRESHOLD:
                    hits.append((int(id_), round(similarity, 3), meta.get("title", "")))

            logger.debug(f"向量搜索: query='{query}', type={content_type}, hits={hits}")
            return hits

        except Exception as e:
            logger.warning(f"向量搜索失败: query='{query}': {e}")
            return []

    async def index_all_contents(self, content_service) -> int:
        """全量索引 MySQL 中所有活跃内容（启动时调用）。

        Returns:
            成功索引的内容数量
        """
        if not self._ready:
            return 0

        try:
            from ..models.database import Content
            from sqlalchemy import select

            logger.info("开始全量向量索引...")
            indexed = 0

            async with content_service.session_factory() as session:
                result = await session.execute(
                    select(Content.id, Content.title, Content.type)
                    .where(Content.is_active == True)
                )
                rows = result.all()

            for row in rows:
                content_id, title, content_type = row
                if title:
                    ok = await self.add_content(
                        content_id, title, content_type.value
                    )
                    if ok:
                        indexed += 1

            logger.info(f"全量向量索引完成: {indexed}/{len(rows)} 条")
            return indexed

        except Exception as e:
            logger.error(f"全量向量索引失败: {e}", exc_info=True)
            return 0

    def delete_content(self, content_id: int) -> bool:
        """从向量 DB 删除内容（内容停用时调用）"""
        if not self._ready:
            return False
        try:
            self._collection.delete(ids=[str(content_id)])
            return True
        except Exception as e:
            logger.warning(f"向量删除失败: id={content_id}: {e}")
            return False

    @property
    def is_ready(self) -> bool:
        return self._ready

    def count(self) -> int:
        """返回向量库中的记录数"""
        if not self._ready:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0
