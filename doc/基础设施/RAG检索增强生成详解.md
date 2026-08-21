# RAG（检索增强生成）详解

## 1. 什么是 RAG？

**RAG**（Retrieval-Augmented Generation，检索增强生成）是一种将**信息检索**与**大语言模型（LLM）生成**相结合的技术架构。

### 1.1 为什么需要 RAG？

大语言模型（如 ChatGPT、DeepSeek）虽然强大，但有三大致命缺陷：

| 缺陷 | 说明 | 示例 |
|------|------|------|
| **知识截止日期** | 只知道自己训练时（截止日之前）的数据 | 问"2025年世界杯冠军是谁？" → 不知道 |
| **幻觉（Hallucination）** | 会编造不存在的事实 | 问"公司内部销售额" → 瞎编一个数字 |
| **私有数据不可访问** | 不知道企业内部数据 | 问"我们的数据库有哪些表？" → 不知道 |

**RAG 的解决方案**：在 LLM 生成答案之前，先从外部知识库中检索相关信息，将检索结果作为"参考材料"一起送给 LLM。

```
用户问题 → 检索相关文档 → LLM（基于文档生成答案） → 回答
```

### 1.2 RAG 的核心流程

```
┌─────────────────────────────────────────────────────────────┐
│                     RAG 完整流程                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  离线阶段（建库）                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐               │
│  │ 文档/数据 │ → │ Embedding │ → │ 向量数据库 │               │
│  └──────────┘    └──────────┘    └──────────┘               │
│                                                             │
│  在线阶段（查询）                                             │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────┐  │
│  │ 用户问题  │ → │ Embedding │ → │ 相似检索  │ → │ LLM  │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**类比理解**：就像考试时"开卷考试" vs "闭卷考试"：

- 闭卷：LLM 纯靠记忆回答（容易出错）
- 开卷：RAG 先查资料，参照资料回答（更准确）

---

## 2. RAG 的核心组件

### 2.1 文档加载与切分

```python
# 1. 加载文档
with open("knowledge_base.txt", "r", encoding="utf-8") as f:
    documents = f.read()

# 2. 切分文档（Chunking）
# 如果文档太长，需要切分成小块
chunks = split_text(documents, chunk_size=500, overlap=50)
```

**切分参数说明**：

| 参数 | 说明 | 建议值 |
|------|------|--------|
| `chunk_size` | 每个块的大小（字符数/token数） | 500-1000 |
| `chunk_overlap` | 相邻块之间的重叠部分 | 50-100 |

**为什么需要重叠（overlap）？**

避免关键信息被切分到两个块的边界，导致检索时遗漏：

```
块1: "...该公司2024年第四季度营收为"
块2: "500亿元，同比增长20%..."

如果没有重叠，"营收为500亿元" 这个完整信息就被切断了！
```

### 2.2 Embedding 向量化

将文本块转换为向量，存入向量数据库：

```python
# 3. 向量化
embeddings = embedding_client.embed_documents(chunks)

# 4. 存入向量数据库
for i, (chunk, vector) in enumerate(zip(chunks, embeddings)):
    await qdrant_client.upsert(
        collection_name="knowledge_base",
        points=[models.PointStruct(
            id=i,
            vector=vector,
            payload={"text": chunk, "source": "knowledge_base.txt"}
        )]
    )
```

### 2.3 检索（Retrieval）

用户提问时，将问题向量化，在向量数据库中检索最相关的文档：

```python
# 5. 用户问题 → 向量
query_vector = embedding_client.embed_query("上个月销售额是多少？")

# 6. 相似度检索
results = await qdrant_client.query_points(
    collection_name="knowledge_base",
    query=query_vector,
    limit=5  # 返回 Top-5 最相关文档
)

# 7. 提取检索到的文本
retrieved_texts = [point.payload["text"] for point in results.points]
```

### 2.4 增强生成（Augmented Generation）

将检索到的文档作为上下文，与用户问题一起送给 LLM：

```python
# 8. 构建 Prompt
prompt = f"""
请根据以下参考信息回答用户问题。如果参考信息不足以回答，请明确说明。

参考信息：
{'---'.join(retrieved_texts)}

用户问题：{user_question}

回答：
"""

# 9. LLM 生成答案
answer = llm.generate(prompt)
```

---

## 3. 检索策略

### 3.1 向量检索（语义相似度）

```python
# 语义上相近的文本会被检索到
"销售额" ≈ "营收" ≈ "收入" ≈ "营业额"
# 即使没有关键词完全匹配，向量检索也能找到
```

**优点**：语义理解能力强
**缺点**：对精确匹配（如 ID、编号）不友好

### 3.2 关键词检索（全文检索）

```python
# 精确匹配关键词
resp = await es_client.search(
    index="knowledge_base",
    query={"match": {"text": "销售额"}}
)
```

**优点**：精确匹配能力强
**缺点**：无法理解同义词和语义变化

### 3.3 混合检索（Hybrid Search）

结合向量检索和关键词检索的优势：

```python
# 向量检索结果
vector_results = await qdrant_client.query_points(...)

# 关键词检索结果
keyword_results = await es_client.search(...)

# 融合排序（RRF: Reciprocal Rank Fusion）
final_results = merge_and_rerank(vector_results, keyword_results)
```

**在本项目中的应用**：

| 检索方式 | 引擎 | 检索内容 |
|---------|------|---------|
| 向量检索 | Qdrant | 表结构、字段信息（语义匹配） |
| 关键词检索 | Elasticsearch | 表名、字段名、别名（精确匹配） |
| **混合检索** | Qdrant + ES | 综合两种检索结果 |

---

## 4. RAG 在 NL2SQL 中的特殊应用

本项目（掌柜问数）实现的是 **NL2SQL 领域的 RAG**，与传统 RAG 有所不同：

### 4.1 传统 RAG vs NL2SQL RAG

| 维度 | 传统 RAG | NL2SQL RAG |
|------|---------|-----------|
| 检索对象 | 文档片段 | 数据库表结构、字段定义、指标定义 |
| 检索目的 | 获取知识来回答问题 | 获取表/字段信息来生成 SQL |
| 最终输出 | 自然语言答案 | SQL 查询语句 |
| 知识库内容 | 文本文档 | 元数据（表名、字段名、类型、描述、别名） |

### 4.2 本项目的 RAG 流程

```
用户问题："上个月销售额是多少？"
          │
          ▼
┌─────────────────────────────────────────────┐
│  1. 关键词提取                                │
│     关键词: ["上个月", "销售额"]               │
└─────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────┐
│  2. 多路召回（RAG 核心）                       │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ Qdrant   │  │    ES    │  │  MySQL   │   │
│  │ 向量检索  │  │ 全文检索  │  │ 精确查询  │   │
│  │ 字段语义  │  │ 表名/别名 │  │ 元数据表  │   │
│  └──────────┘  └──────────┘  └──────────┘   │
│          │            │            │         │
│          └────────────┼────────────┘         │
│                       ▼                      │
│              合并召回结果                      │
└─────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────┐
│  3. 过滤与筛选                                │
│     过滤不相关的表/字段，保留最相关的           │
└─────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────┐
│  4. 生成 SQL（增强生成）                       │
│     Prompt = 表结构 + 字段信息 + 用户问题       │
│     LLM → SELECT SUM(order_amount)           │
│            FROM fact_order                   │
│            WHERE order_date >= '2025-06-01'  │
└─────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────┐
│  5. 校验 → 修正 → 执行 → 返回结果              │
└─────────────────────────────────────────────┘
```

### 4.3 多路召回详解

本项目的"召回"阶段使用了三种检索方式：

**方式一：向量召回（Qdrant）**

```python
# 将用户问题扩展后的关键词向量化
query_vector = embedding_client.embed_query("销售额 营收 收入")

# 在 Qdrant 中检索语义最接近的字段
results = await qdrant_client.query_points(
    collection_name="column_embeddings",
    query=query_vector,
    limit=10
)
# 返回: [order_amount, total_revenue, sales_volume, ...]
```

**方式二：全文召回（Elasticsearch）**

```python
# 在 ES 中全文检索关键词
results = await es_client.search(
    index="data_agent",
    query={
        "multi_match": {
            "query": "销售额",
            "fields": ["column_name", "column_alias", "column_description"]
        }
    }
)
# 返回: [order_amount（别名"销售额"）, ...]
```

**方式三：精确查询（MySQL Meta）**

```python
# 直接从元数据库查询匹配的表和字段
results = await session.execute(
    text("SELECT * FROM column_info WHERE name LIKE '%amount%' OR alias LIKE '%销售额%'")
)
```

---

## 5. RAG 的进阶技术

### 5.1 重排序（Re-ranking）

初次检索后，用更强的模型重新排序：

```python
# 1. 粗排：向量检索召回 Top-20
coarse_results = await qdrant_client.query_points(limit=20)

# 2. 精排：用 Cross-Encoder 模型对 Top-20 重新打分
scores = cross_encoder.predict([(query, doc) for doc in coarse_results])
final_results = sorted(zip(coarse_results, scores), key=lambda x: x[1], reverse=True)[:5]
```

### 5.2 查询重写（Query Rewriting）

用户问题可能不够精确，LLM 可以帮忙重写：

```python
# 原始问题
user_query = "上个月赚了多少？"

# LLM 重写
rewritten_query = llm.generate(
    "将以下问题重写为更精确的数据库查询描述：\n" + user_query
)
# 重写后: "2025年6月的总营收额（订单金额汇总）"
```

### 5.3 关键词扩展（Keyword Expansion）

```python
# 原始关键词
keywords = ["销售额"]

# LLM 扩展同义词
expanded = llm.generate(
    f"为以下关键词生成同义词和相关词：{keywords}"
)
# 扩展后: ["销售额", "营收", "收入", "营业额", "订单金额", "总收入"]
```

---

## 6. RAG 评估指标

| 指标 | 含义 | 计算方式 |
|------|------|---------|
| 召回率（Recall） | 检索到的相关文档 / 所有相关文档 | TP / (TP + FN) |
| 精确率（Precision） | 检索到的相关文档 / 检索到的所有文档 | TP / (TP + FP) |
| MRR | 第一个相关文档的平均排名倒数 | 1/第一个相关文档的排名 |
| NDCG | 考虑排序位置的相关性得分 | 归一化折损累积增益 |

---

## 7. 总结

| 概念 | 一句话解释 |
|------|-----------|
| RAG | 检索 + 生成：先从知识库检索，再让 LLM 基于检索结果生成答案 |
| Embedding | 将文本转为向量，语义相近的文本向量也相近 |
| Chunking | 将长文档切分成小块 |
| 向量检索 | 基于语义相似度的检索（Qdrant） |
| 全文检索 | 基于关键词匹配的检索（Elasticsearch） |
| 混合检索 | 结合向量检索和全文检索的优势 |
| 重排序 | 对检索结果进行二次精排 |
| 查询重写 | 优化用户问题以提高检索质量 |

**在本项目中的核心价值**：RAG 是 NL2SQL 智能体的"大脑"，通过多路召回（向量 + 全文 + 精确匹配）从数据库元数据中找到用户问题对应的表和字段，然后交给 LLM 生成准确的 SQL 语句。没有 RAG，LLM 不可能知道你的数据库里有哪些表和字段。\