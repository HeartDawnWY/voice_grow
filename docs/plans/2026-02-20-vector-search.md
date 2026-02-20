# Vector Search Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 DB MySQL 查询失败后、在线下载之前，插入 ChromaDB 向量语义搜索层，解决繁简体/标题变体导致的二次检索失败问题。

**Architecture:**
- 新建独立服务 `VectorSearchService`（ChromaDB + sentence-transformers）
- 注入到 `ContentServiceBase`，作为可选依赖（降级友好）
- 搜索链：MySQL精确/模糊 → **向量语义搜索** → 在线下载
- 写入链：`create_content` 存 MySQL 后，同步写入 ChromaDB

**Tech Stack:**
- `chromadb>=0.5.0` — 本地持久化向量数据库
- `sentence-transformers>=3.0.0` — 多语言 embedding 模型
- 模型：`paraphrase-multilingual-MiniLM-L12-v2`（支持中文，约 420MB，首次自动下载）

---

### Task 1: 安装依赖

**Files:**
- Modify: `server/requirements.txt`

**Step 1: 添加依赖**

在 `server/requirements.txt` 的 `# Text Processing` 区域后追加：

```
# Vector Search (ChromaDB + sentence-transformers)
chromadb>=0.5.0
sentence-transformers>=3.0.0
```

**Step 2: 安装（在 server venv 中）**

```bash
cd /Users/jingen/Desktop/Project/voice_grow
server/.venv/bin/pip install chromadb>=0.5.0 "sentence-transformers>=3.0.0"
```

Expected output: `Successfully installed chromadb-... sentence-transformers-...`

**Step 3: 验证安装**

```bash
server/.venv/bin/python -c "import chromadb; import sentence_transformers; print('OK')"
```

Expected: `OK`

**Step 4: Commit**

```bash
git add server/requirements.txt
git commit -m "feat: add chromadb and sentence-transformers dependencies"
```

---

### Task 2: 创建 VectorSearchService

**Files:**
- Create: `server/app/services/vector_service.py`

**Step 1: 创建文件**

内容如下：

```python
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
            loop = asyncio.get_running_loop()
            query_vector = await loop.run_in_executor(None, self._encode, query)

            where = {"content_type": content_type} if content_type else None

            results = self._collection.query(
                query_embeddings=[query_vector],
                n_results=min(top_k, max(self._collection.count(), 1)),
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
            from ..models.database import Content, ContentType
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
```

**Step 2: 验证语法**

```bash
server/.venv/bin/python -c "
import sys; sys.path.insert(0, 'server')
from app.services.vector_service import VectorSearchService
print('Import OK')
"
```

Expected: `Import OK`

**Step 3: Commit**

```bash
git add server/app/services/vector_service.py
git commit -m "feat: add VectorSearchService with ChromaDB + sentence-transformers"
```

---

### Task 3: ContentServiceBase 注入 VectorSearchService

**Files:**
- Modify: `server/app/services/content/base.py`

**Step 1: 修改 `__init__` 方法**

在 `base.py` 的 `ContentServiceBase.__init__` 中添加可选参数 `vector_service`：

将：
```python
    def __init__(
        self,
        session_factory,
        minio_service: MinIOService,
        redis_service: Optional["RedisService"] = None
    ):
        self.session_factory = session_factory
        self.minio = minio_service
        self.redis = redis_service
```

改为：
```python
    def __init__(
        self,
        session_factory,
        minio_service: MinIOService,
        redis_service: Optional["RedisService"] = None,
        vector_service=None,
    ):
        self.session_factory = session_factory
        self.minio = minio_service
        self.redis = redis_service
        self.vector = vector_service  # VectorSearchService 实例，None 表示禁用
```

**Step 2: 验证语法**

```bash
server/.venv/bin/python -c "
import sys; sys.path.insert(0, 'server')
from app.services.content.base import ContentServiceBase
print('Import OK')
"
```

Expected: `Import OK`

**Step 3: Commit**

```bash
git add server/app/services/content/base.py
git commit -m "feat: inject optional VectorSearchService into ContentServiceBase"
```

---

### Task 4: get_content_by_name 添加向量搜索 fallback

**Files:**
- Modify: `server/app/services/content/query.py`

**Step 1: 在 `get_content_by_name` 方法末尾（MySQL 返回 None 后）添加向量搜索**

找到 `get_content_by_name` 方法末尾的 `return None`，替换为：

```python
            if content:
                return await self._content_to_dict(content)

            # --- 向量语义搜索 fallback ---
            if self.vector and self.vector.is_ready:
                hits = await self.vector.search(
                    query=name,
                    content_type=content_type.value,
                    top_k=1,
                )
                if hits:
                    best_id, score, matched_title = hits[0]
                    logger.info(
                        f"向量搜索命中: query='{name}' → '{matched_title}' "
                        f"(similarity={score}, content_id={best_id})"
                    )
                    return await self.get_content_by_id(best_id)

            return None
```

**Step 2: 验证语法**

```bash
server/.venv/bin/python -c "
import sys; sys.path.insert(0, 'server')
from app.services.content.query import ContentQueryMixin
print('Import OK')
"
```

Expected: `Import OK`

**Step 3: Commit**

```bash
git add server/app/services/content/query.py
git commit -m "feat: add vector semantic search fallback in get_content_by_name"
```

---

### Task 5: create_content 后同步写入向量 DB

**Files:**
- Modify: `server/app/services/content/admin.py`

**Step 1: 找到 `create_content` 方法**

在 `admin.py` 第 195 行附近的 `create_content` 方法中，找到最终 `return` 语句之前（已成功创建 DB 记录后），添加向量同步：

在 `create_content` 方法末尾的 `return result_dict` 之前插入：

```python
        # 同步写入向量 DB（非关键，失败不影响主流程）
        if self.vector and self.vector.is_ready:
            try:
                await self.vector.add_content(
                    content_id=new_content.id,
                    title=new_content.title,
                    content_type=new_content.type.value,
                )
            except Exception as e:
                logger.warning(f"向量写入失败（非关键）: content_id={new_content.id}, error={e}")
```

注意：需要先读 `admin.py` 确认变量名（`new_content` 或其他），确保与实际代码一致。

**Step 2: 确认 admin.py 中 create_content 的变量名**

```bash
grep -n "new_content\|content_id\|return " server/app/services/content/admin.py | head -40
```

根据实际变量名调整上方代码。

**Step 3: 验证语法**

```bash
server/.venv/bin/python -c "
import sys; sys.path.insert(0, 'server')
from app.services.content.admin import AdminMixin
print('Import OK')
"
```

Expected: `Import OK`

**Step 4: Commit**

```bash
git add server/app/services/content/admin.py
git commit -m "feat: sync new content to vector DB after create_content"
```

---

### Task 6: main.py 初始化并注入 VectorSearchService

**Files:**
- Modify: `server/app/main.py`

**Step 1: 在 imports 区域添加**

在 `from .services.download_service import DownloadService` 后添加：

```python
from .services.vector_service import VectorSearchService
```

**Step 2: 在 lifespan 函数的 step 7（初始化业务服务）之前，添加向量服务初始化**

在 `# 7. 初始化业务服务` 注释之前插入：

```python
    # 6.5. 初始化向量搜索服务（可选，失败降级）
    logger.info("初始化向量搜索服务...")
    vector_service = VectorSearchService()
    vector_ok = vector_service.initialize()
    if not vector_ok:
        logger.warning("向量搜索服务初始化失败，将以降级模式运行（无语义搜索）")
        vector_service = None
```

**Step 3: 修改 ContentService 初始化，传入 vector_service**

将：
```python
    content_service = ContentService(session_factory, minio_service, redis_service)
```

改为：
```python
    content_service = ContentService(session_factory, minio_service, redis_service, vector_service)
```

**Step 4: 在 yield 之前添加全量索引（异步后台任务）**

在 `logger.info("VoiceGrow Server 启动完成!")` 之前插入：

```python
    # 全量向量索引（后台执行，不阻塞启动）
    if vector_service and vector_service.is_ready:
        asyncio.create_task(vector_service.index_all_contents(content_service))
        logger.info("向量全量索引已在后台启动")
```

**Step 5: 验证语法（不启动服务，只检查 import）**

```bash
server/.venv/bin/python -c "
import sys; sys.path.insert(0, 'server')
from app.main import create_app
print('Import OK')
"
```

Expected: `Import OK`

**Step 6: Commit**

```bash
git add server/app/main.py
git commit -m "feat: initialize VectorSearchService and inject into ContentService at startup"
```

---

### Task 7: 集成测试验证

**Step 1: 确认全部模块可以导入**

```bash
server/.venv/bin/python -c "
import sys; sys.path.insert(0, 'server')
from app.services.vector_service import VectorSearchService
from app.services.content_service import ContentService
from app.main import create_app
print('All imports OK')
"
```

Expected: `All imports OK`

**Step 2: 单元测试 VectorSearchService**

```bash
server/.venv/bin/python -c "
import asyncio, sys, os, tempfile
sys.path.insert(0, 'server')

async def test():
    from app.services.vector_service import VectorSearchService

    with tempfile.TemporaryDirectory() as tmp:
        vs = VectorSearchService(persist_path=tmp)
        ok = vs.initialize()
        assert ok, 'initialize failed'

        # 写入繁体标题
        await vs.add_content(1, '小紅帽童話故事', 'story')
        await vs.add_content(2, '白雪公主與七個小矮人', 'story')

        # 用简体搜索
        hits = await vs.search('小红帽', content_type='story')
        assert hits, 'no hits found'
        assert hits[0][0] == 1, f'expected id=1, got {hits[0][0]}'
        print(f'搜索命中: {hits}')
        print('VectorSearchService 测试通过 ✓')

asyncio.run(test())
"
```

Expected output:
```
搜索命中: [(1, 0.xxx, '小紅帽童話故事')]
VectorSearchService 测试通过 ✓
```

**Step 3: Commit（如果上述测试通过）**

```bash
git commit --allow-empty -m "test: verify VectorSearchService unit test passes"
```

---

## 完成标准

- [ ] `chromadb` 和 `sentence-transformers` 已安装
- [ ] `VectorSearchService` 初始化成功（查看启动日志）
- [ ] 繁体 → 简体测试通过（Task 7 Step 2）
- [ ] 首次"播放小红帽" → 在线下载 → 内容写入 ChromaDB
- [ ] 第二次"播放小红帽" → MySQL miss → 向量命中 → 直接播放（不再下载）
- [ ] 向量服务失败时，系统正常降级（不崩溃，走在线下载路径）

## 注意事项

- ChromaDB 数据存储在 `./chroma_db/`（相对于启动目录），建议在 `.gitignore` 中排除
- 模型文件约 420MB，首次启动会自动下载到 `~/.cache/huggingface/`
- `initialize()` 是同步阻塞方法，会在启动时加载模型（约 2-5 秒）
- 全量索引是异步后台任务，不阻塞服务启动
- 向量服务降级为 `None` 时，`get_content_by_name` 直接跳过向量搜索，行为与未实现前一致
