# Embedding 向量化客户端管理详解

## 1. 什么是 Embedding（向量嵌入）？

### 1.1 直观理解

Embedding 是将**文本、图片、音频等非结构化数据**转换成**固定长度的浮点数数组（向量）**的技术。

```
"今天天气真好" 
    ↓ Embedding 模型 (BGE-large-zh-v1.5)
[0.023, -0.451, 0.789, ..., 0.312]  ← 1024维向量
```

**核心原理**：语义相近的文本，其向量在空间中距离也近。

```
"今天天气真好"  → [0.02, -0.45, 0.78, ...]
"今天天气不错"  → [0.03, -0.43, 0.79, ...]  ← 向量很接近！
"数据库连接失败" → [0.87, 0.12, -0.34, ...]  ← 向量相差很远！
```

### 1.2 Embedding 在 AI 应用中的位置

```
┌──────────────────────────────────────────────────┐
│                   RAG 流程                        │
├──────────────────────────────────────────────────┤
│  1. 文档入库                                      │
│     文档 → Embedding 模型 → 向量 → 存入 Qdrant     │
│                                                  │
│  2. 用户查询                                      │
│     用户问题 → Embedding 模型 → 查询向量            │
│                                                  │
│  3. 检索                                          │
│     查询向量 → Qdrant 相似度检索 → 相关文档片段     │
│                                                  │
│  4. 生成                                          │
│     相关文档 + 用户问题 → LLM → 答案               │
└──────────────────────────────────────────────────┘
```

---

## 2. 技术栈解析

本项目涉及三个关键组件，它们的关系如下：

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────────────────┐
│  BGE 模型    │────▶│  TEI 服务     │◀────│  HuggingFaceEndpointEmbeddings │
│  (底层AI模型)│     │  (服务化引擎)  │     │  (LangChain 客户端)            │
└─────────────┘     └──────────────┘     └──────────────────────────────┘
```

### 2.1 BGE-large-zh-v1.5 — 底层 AI 向量模型

**BGE**（BAAI General Embedding）是由**智源研究院（BAAI）**开源的通用 Embedding 模型。

| 特性 | 说明 |
|------|------|
| 开发者 | 北京智源人工智能研究院（BAAI） |
| 语言 | 中文优化（也支持英文） |
| 模型规模 | Large（大模型版本） |
| 版本 | v1.5（最新稳定版） |
| 输出维度 | **1024 维** |
| 最大输入长度 | 512 tokens |
| 在 MTEB 中文榜单 | 排名前列 |

**为什么选择 BGE-large-zh-v1.5？**

1. **中文效果最好**：在中文语义相似度（STS）任务上表现优异
2. **开源免费**：无需付费 API，可本地部署
3. **1024 维向量**：精度与效率的平衡点（维度越高表达力越强，但存储和检索成本也越高）

### 2.2 TEI（Text Embeddings Inference）— 服务化引擎

**TEI** 是 Hugging Face 开发的**文本嵌入推理工具包**，专门用于将 Embedding 模型**部署为在线 API 服务**。

**为什么需要 TEI？**

如果直接在 Python 代码中加载 BGE 模型：

```python
# 直接加载模型（不推荐）
from sentence_transformers import SentenceTransformer
model = SentenceTransformer("BAAI/bge-large-zh-v1.5")
# 问题：
# 1. 每次启动都加载模型 → 启动慢（几GB的模型）
# 2. 模型常驻进程内存 → 内存占用大
# 3. 无法多进程共享 → 资源浪费
```

使用 TEI 部署为独立服务后：

```python
# 通过 HTTP API 调用（推荐）
from langchain_huggingface import HuggingFaceEndpointEmbeddings
client = HuggingFaceEndpointEmbeddings(model="http://localhost:8081")
# 优势：
# 1. 模型独立部署，启动不受影响
# 2. 多进程/多服务共享一个 TEI 实例
# 3. 支持 GPU 加速
# 4. 可独立扩缩容
```

**TEI 的核心优势**：

| 特性 | 说明 |
|------|------|
| 高性能 | 支持 Flash Attention、连续批处理等优化 |
| GPU 加速 | 支持 CUDA，推理速度大幅提升 |
| 标准化 API | 提供 RESTful API，兼容 OpenAI Embedding 接口格式 |
| 多模型支持 | 支持 BGE、E5、GTE 等主流模型 |
| Docker 部署 | 一键启动，环境隔离 |

### 2.3 HuggingFaceEndpointEmbeddings — LangChain 客户端

这是 LangChain 提供的**客户端封装**，用于远程调用 TEI 服务。

```python
from langchain_huggingface import HuggingFaceEndpointEmbeddings

# model 参数指向 TEI 服务的地址
client = HuggingFaceEndpointEmbeddings(model="http://localhost:8081")
```

**关键方法**：

```python
# 嵌入单条文本（返回一个向量）
vector = client.embed_query("今天天气真好")
# 返回: [0.023, -0.451, ..., 0.312]  (1024维)

# 嵌入多条文本（返回向量列表）
vectors = client.embed_documents([
    "今天天气真好",
    "数据库连接失败",
    "销售额同比增长20%"
])
# 返回: [[0.023, ...], [0.087, ...], [-0.034, ...]]
```

---

## 3. Docker 部署 TEI 服务

### 3.1 拉取镜像并启动

```bash
docker run -d \
  --name tei-bge \
  -p 8081:80 \
  -v /path/to/models:/data \
  -e MODEL_ID=BAAI/bge-large-zh-v1.5 \
  ghcr.io/huggingface/text-embeddings-inference:latest
```

### 3.2 配置说明

| 参数 | 说明 |
|------|------|
| `-p 8081:80` | 将容器的 80 端口映射到宿主机的 8081 端口 |
| `-v /path/to/models:/data` | 挂载模型存储目录（避免每次重启重新下载模型） |
| `-e MODEL_ID=...` | 指定要加载的 Embedding 模型 |

### 3.3 验证服务

```bash
curl http://localhost:8081/embed \
  -H "Content-Type: application/json" \
  -d '{"inputs": "今天天气真好"}'
```

---

## 4. 本项目客户端实现

在 `data-agent/app/clients/embedding_client_manager.py` 中：

```python
from typing import Optional
from langchain_huggingface import HuggingFaceEndpointEmbeddings

class EmbeddedClientManager:
    """嵌入式向量嵌入客户端管理器"""

    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self.client: Optional[HuggingFaceEndpointEmbeddings] = None

    def _get_url(self):
        return f"http://{self.config.host}:{self.config.port}"

    def init(self):
        self.client = HuggingFaceEndpointEmbeddings(model=self._get_url())

# 全局实例
embedding_client_manager = EmbeddedClientManager(app_config.embedding)
```

### 4.1 配置说明

```yaml
# conf/app_config.yaml
embedding:
  host: localhost      # TEI 服务地址
  port: 8081           # TEI 服务端口
  model: BAAI/bge-large-zh-v1.5  # 使用的模型名称
```

### 4.2 测试代码

```python
if __name__ == '__main__':
    client = EmbeddedClientManager(app_config.embedding)
    client.init()

    # 嵌入单条文本
    query = client.client.embed_query("hello world")
    print(len(query))   # 1024（向量维度）
    print(query)        # [0.023, -0.451, ...]
```

---

## 5. Embedding 在本项目中的使用场景

### 5.1 构建元数据知识库

```python
# 将表描述向量化后存入 Qdrant
table_desc = "订单事实表，记录所有订单的金额、时间、状态等信息"
vector = embedding_client_manager.client.embed_query(table_desc)

await qdrant_client.upsert(
    collection_name="table_embeddings",
    points=[models.PointStruct(
        id="table_fact_order",
        vector=vector,
        payload={"table_name": "fact_order", "description": table_desc}
    )]
)
```

### 5.2 用户问题检索

```python
# 用户自然语言问题 → 向量 → 检索最相关的表和字段
user_question = "上个月卖了多少？"
query_vector = embedding_client_manager.client.embed_query(user_question)

results = await qdrant_client.query_points(
    collection_name="table_embeddings",
    query=query_vector,
    limit=5
)
# 返回最相关的5个表/字段
```

### 5.3 批量向量化

```python
# 批量向量化多个表描述
descriptions = [
    "订单事实表，记录所有订单信息",
    "用户维度表，记录用户基本信息",
    "商品维度表，记录商品SKU信息"
]
vectors = embedding_client_manager.client.embed_documents(descriptions)
# 返回: [[1024维向量], [1024维向量], [1024维向量]]
```

---

## 6. 常见 Embedding 模型对比

| 模型 | 维度 | 中文效果 | 速度 | 部署方式 |
|------|------|---------|------|---------|
| BAAI/bge-large-zh-v1.5 | 1024 | ⭐⭐⭐⭐⭐ | 中等 | 本地/TEI ✅ |
| BAAI/bge-small-zh-v1.5 | 512 | ⭐⭐⭐⭐ | 快 | 本地/TEI |
| text-embedding-ada-002 | 1536 | ⭐⭐⭐⭐ | 快 | OpenAI API（付费） |
| text-embedding-3-small | 512/1536 | ⭐⭐⭐⭐ | 快 | OpenAI API（付费） |
| m3e-large | 1024 | ⭐⭐⭐⭐ | 中等 | 本地/TEI |

---

## 7. 总结

| 组件 | 角色 |
|------|------|
| **BGE-large-zh-v1.5** | 底层 AI 模型，将文本转为 1024 维向量 |
| **TEI** | 服务化引擎，将 BGE 模型封装为 HTTP API 服务 |
| **HuggingFaceEndpointEmbeddings** | LangChain 客户端，远程调用 TEI 服务 |
| **EmbeddedClientManager** | 本项目封装，管理客户端生命周期 |

**三者的关系**：

```
BGE 模型 = 发动机
TEI     = 把发动机装进汽车，提供方向盘和油门
HuggingFaceEndpointEmbeddings = 遥控器，远程操控汽车
```

**在本项目中的核心价值**：将自然语言和数据库元数据都转换为向量，使得 NL2SQL 智能体能够通过语义相似度找到用户问题对应的数据库表和字段，是实现"自然语言 → SQL"转换的关键桥梁。\