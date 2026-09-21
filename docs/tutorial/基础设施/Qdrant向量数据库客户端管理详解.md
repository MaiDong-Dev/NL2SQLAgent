# Qdrant 向量数据库客户端管理详解

## 1. 什么是向量数据库？

在理解 Qdrant 之前，先理解"向量数据库"这个概念。

### 1.1 传统数据库 vs 向量数据库

| 维度 | 传统数据库（MySQL/ES） | 向量数据库（Qdrant/Milvus） |
|------|----------------------|---------------------------|
| 存储内容 | 结构化数据（数字、文本） | 高维向量（浮点数数组） |
| 查询方式 | 精确匹配、关键词搜索 | **相似度检索**（语义相近） |
| 典型问题 | "找到年龄=25的用户" | "找到与这段话语义最相似的文档" |
| 索引技术 | B+树、倒排索引 | HNSW、IVF 等近似最近邻算法 |

### 1.2 为什么需要向量数据库？

大模型 / Embedding 模型会将文本转换成高维向量：

```
"今天天气真好" → Embedding → [0.12, -0.34, 0.56, ..., 0.78]  (1024维)
```

**语义相近的文本，其向量在空间中距离也近**。向量数据库就是用来存储和检索这些向量的。

---

## 2. Qdrant 概述

[Qdrant](https://qdrant.tech/) 是一款**开源、高性能、云原生的向量数据库**，专门用于**高维向量存储 + 相似度检索**，是当前 AI 应用（RAG、推荐系统、语义搜索）的标配存储组件。

### 2.1 核心特性

| 特性 | 说明 |
|------|------|
| 高性能 | 基于 Rust 开发，单机可处理百万级向量 |
| 支持过滤 | 向量检索 + 元数据（Payload）条件过滤同时使用 |
| 多种距离度量 | 余弦相似度、欧氏距离、点积 |
| RESTful API | 提供 HTTP/gRPC 两种协议 |
| 丰富的数据类型 | 支持多种向量和标量类型 |
| 云原生 | 支持 Docker 部署、水平扩展 |

### 2.2 典型应用场景

```
┌──────────────────────────────────────────────────────┐
│                   Qdrant 应用场景                      │
├──────────────────────────────────────────────────────┤
│ 1. RAG 知识库检索                                     │
│    用户问题 → Embedding → 向量检索 → 最相关文档片段     │
│                                                      │
│ 2. 语义搜索                                           │
│    "怎么退款" ≈ "如何申请退货" → 语义匹配              │
│                                                      │
│ 3. 推荐系统                                           │
│    用户画像向量 → 检索相似用户 → 推荐相似商品           │
│                                                      │
│ 4. 图片/音视频多模态检索                               │
│    图片 → CLIP Embedding → 检索相似图片               │
│                                                      │
│ 5. 智能问答                                           │
│    问题 → 检索相关文档 → LLM 生成答案                  │
└──────────────────────────────────────────────────────┘
```

### 2.3 在本项目中的角色

在本项目（掌柜问数 NL2SQL Agent）中，Qdrant 用于**存储表结构和字段的向量化表示**，实现**语义级别的表/字段检索**。

例如用户问："帮我查一下上个月的销售额"，Agent 需要找到相关的表和字段：

```
用户问题 → Embedding → [0.12, -0.34, ...]
                              ↓
Qdrant 检索 → 最相关的表: fact_order
           → 最相关的字段: order_amount, order_date
```

---

## 3. 核心概念

### 3.1 Collection（集合）

类比关系型数据库中的"表"，是向量的逻辑分组。

```python
await client.create_collection(
    collection_name="table_embeddings",
    vectors_config=models.VectorParams(
        size=1024,                          # 向量维度
        distance=models.Distance.COSINE     # 相似度计算方式
    ),
)
```

### 3.2 Point（点）

Qdrant 中的基本数据单元，包含：

- **id**：唯一标识
- **vector**：高维向量（浮点数数组）
- **payload**（可选）：附加的元数据（JSON 格式）

```python
models.PointStruct(
    id=1,
    vector=[0.12, -0.34, 0.56, ...],  # 1024维向量
    payload={
        "table_name": "fact_order",
        "description": "订单事实表"
    }
)
```

### 3.3 距离度量（Distance Metrics）

| 度量方式 | 公式特点 | 适用场景 |
|---------|---------|---------|
| **Cosine（余弦相似度）** | 只看方向不看长度 | 文本语义相似度 ✅ |
| Euclid（欧氏距离） | 绝对距离 | 图像、坐标 |
| Dot（点积） | 综合考虑方向和长度 | 推荐系统 |

本项目使用**余弦相似度（Cosine）**，因为：
- 文本向量化后，方向比长度更重要
- 最适合语义搜索、RAG 场景
- 不看向量长度，只看方向是否接近

### 3.4 向量维度选择

```python
vectors_config=models.VectorParams(size=1024, distance=models.Distance.COSINE)
```

`size=1024` 表示每个向量由 1024 个浮点数组成。维度取决于使用的 Embedding 模型：

| 模型 | 输出维度 |
|------|---------|
| BAAI/bge-large-zh-v1.5 | **1024 维** ✅ |
| text-embedding-ada-002 | 1536 维 |
| BAAI/bge-small-zh-v1.5 | 512 维 |

---

## 4. 本项目客户端实现

在 `data-agent/app/clients/qdrant_client_manager.py` 中：

```python
from typing import Optional
from qdrant_client import AsyncQdrantClient, models

class QdrantClientManager:
    """Qdrant向量数据库异步客户端管理器"""

    def __init__(self, qdrant_config: QdrantConfig):
        self.qdrant_config = qdrant_config
        self.client: Optional[AsyncQdrantClient] = None

    def _get_url(self):
        return f"http://{self.qdrant_config.host}:{self.qdrant_config.port}"

    def init(self):
        self.client = AsyncQdrantClient(self._get_url())

    async def close(self):
        await self.client.close()

# 全局实例
qdrant_client_manager = QdrantClientManager(app_config.qdrant)
```

### 4.1 设计模式

采用**延迟初始化（Lazy Initialization）**模式：
- `__init__` 只保存配置，不创建连接
- `init()` 在应用启动时调用，创建真正的客户端实例
- `close()` 在应用关闭时调用，释放资源

### 4.2 为什么用异步客户端？

- `AsyncQdrantClient` 基于 `httpx` 的异步 HTTP 客户端
- 与 FastAPI 的异步生态完美匹配
- 不阻塞事件循环，支持高并发检索

---

## 5. 完整测试示例

```python
import asyncio
import random

# 初始化
qdrant_client_manager.init()
client = qdrant_client_manager.client

async def test():
    # 1. 创建集合（如果不存在）
    if not await client.collection_exists("my_collection"):
        await client.create_collection(
            collection_name="my_collection",
            vectors_config=models.VectorParams(
                size=10,                          # 10维向量
                distance=models.Distance.COSINE   # 余弦相似度
            ),
        )

    # 2. 批量插入100个随机向量
    await client.upsert(
        collection_name="my_collection",
        points=[
            models.PointStruct(
                id=i,
                vector=[random.random() for _ in range(10)]
            )
            for i in range(100)
        ],
    )

    # 3. 相似度检索：查找最相似的10个向量
    res = await client.query_points(
        collection_name="my_collection",
        query=[random.random() for _ in range(10)],  # 查询向量
        limit=10,                                      # 返回 Top-10
        score_threshold=0.5                            # 最低相似度阈值
    )
    print(res.points)

asyncio.run(test())
```

---

## 6. API 操作详解

### 6.1 创建集合

```python
await client.create_collection(
    collection_name="table_embeddings",
    vectors_config=models.VectorParams(
        size=1024,                           # 必须与 Embedding 模型输出维度一致
        distance=models.Distance.COSINE      # 余弦相似度
    ),
)
```

### 6.2 插入/更新向量

```python
await client.upsert(
    collection_name="table_embeddings",
    points=[
        models.PointStruct(
            id="table_fact_order",           # 唯一标识
            vector=embedding_result,         # 1024维向量
            payload={                        # 元数据（可选但推荐）
                "table_name": "fact_order",
                "description": "订单事实表，记录所有订单信息"
            }
        )
    ]
)
```

`upsert` = update + insert：如果 id 已存在则更新，否则插入。

### 6.3 相似度检索

```python
res = await client.query_points(
    collection_name="table_embeddings",
    query=query_vector,         # 查询向量
    limit=10,                   # 返回 Top-K
    score_threshold=0.5         # 只返回相似度 ≥ 0.5 的结果
)
```

**返回结果**包含每个点的 `id`、`score`（相似度得分）、`payload`（元数据）。

### 6.4 带过滤的检索

```python
res = await client.query_points(
    collection_name="table_embeddings",
    query=query_vector,
    query_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="table_type",           # 过滤字段
                match=models.MatchValue(value="fact")  # 只检索事实表
            )
        ]
    ),
    limit=10
)
```

---

## 7. Qdrant Web UI

Qdrant 自带 Web 管理界面，启动后可通过浏览器访问：

```
http://localhost:6333/dashboard
```

功能包括：
- 查看所有 Collection
- 浏览向量数据
- 可视化检索结果
- 监控服务状态

---

## 8. 总结

| 概念 | 说明 |
|------|------|
| Qdrant | 开源、高性能向量数据库，Rust 编写 |
| Collection | 向量的逻辑分组，类似数据库的"表" |
| Point | 一个向量 + 可选的元数据（payload） |
| Cosine | 余弦相似度，最适合文本语义检索 |
| Upsert | 插入或更新（id 存在则更新） |
| Query Points | 相似度检索，返回 Top-K 最相似向量 |
| BGE-large-zh-v1.5 | 本项目使用的 Embedding 模型，输出 1024 维向量 |

**在本项目中的核心价值**：将数据库表结构向量化后存入 Qdrant，当用户提出自然语言问题时，通过语义相似度检索找到最相关的表和字段，是 NL2SQL 智能体的关键基础设施。\