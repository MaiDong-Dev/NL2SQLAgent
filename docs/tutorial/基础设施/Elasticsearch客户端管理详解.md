# Elasticsearch 客户端管理详解

## 1. Elasticsearch 概述

[Elasticsearch](https://www.elastic.co/elasticsearch)（简称 ES）是一个**开源、分布式、RESTful 风格的搜索引擎**，基于 Apache Lucene 构建，主打**全文检索、结构化检索、日志分析、数据统计**。

### 1.1 ES 的核心定位

```
┌──────────────────────────────────────────────────┐
│              Elasticsearch 能做什么                │
├──────────────────────────────────────────────────┤
│ 1. 全文搜索：对海量文本进行快速的模糊/精确搜索      │
│ 2. 结构化搜索：对数值、日期等结构化数据进行过滤     │
│ 3. 聚合分析：实时统计、分组、排序、分页             │
│ 4. 日志分析：ELK Stack（Elasticsearch + Logstash   │
│    + Kibana）的核心组件                            │
│ 5. 自动补全：搜索建议、拼音搜索                    │
└──────────────────────────────────────────────────┘
```

### 1.2 ES vs MySQL 的搜索能力对比

| 场景 | MySQL | Elasticsearch |
|------|-------|--------------|
| 精确匹配 `WHERE name = '张三'` | ✅ 优秀 | ✅ 优秀 |
| 模糊搜索 `WHERE name LIKE '%张%'` | ❌ 全表扫描，极慢 | ✅ 倒排索引，毫秒级 |
| 分词搜索 "搜索 引擎" 匹配 "搜索引擎" | ❌ 不支持 | ✅ 分词器原生支持 |
| 相关性排序 | ❌ 不支持 | ✅ TF-IDF/BM25 算法 |
| 高亮显示 | ❌ 不支持 | ✅ 原生支持 |
| 聚合统计 | 需要 GROUP BY，大表慢 | ✅ 分布式聚合，快速 |

**简单来说**：MySQL 擅长"找得准"，ES 擅长"找得快"和"找得全"。

---

## 2. ES 核心概念

### 2.1 类比关系型数据库

| Elasticsearch | 关系型数据库（MySQL） | 说明 |
|---------------|---------------------|------|
| Index（索引） | Table（表） | 文档的集合 |
| Document（文档） | Row（行） | 一条数据记录 |
| Field（字段） | Column（列） | 数据的一个属性 |
| Mapping（映射） | Schema（表结构） | 字段的类型定义 |
| DSL 查询 | SQL | 查询语言 |

### 2.2 倒排索引 — ES 的核心秘密

假设有两条文档：

```
文档1: "Python 是一门优秀的编程语言"
文档2: "Java 也是一门编程语言"
```

**倒排索引**的构建过程：

```
词语      →  出现在哪些文档
"Python"  →  [文档1]
"Java"    →  [文档2]
"编程"    →  [文档1, 文档2]
"语言"    →  [文档1, 文档2]
```

当用户搜索"Python 编程"时：
1. 分词：["Python", "编程"]
2. 查倒排索引：Python → [文档1]，编程 → [文档1, 文档2]
3. 计算相关性：文档1 匹配了 2 个词，得分最高
4. 返回结果：文档1 排第一

这就是 ES 为什么能**毫秒级**搜索海量数据的原因！

### 2.3 分词器（Analyzer）

分词器决定了文本如何被拆分成词语，直接影响搜索效果。

| 分词器 | 说明 | 示例 |
|--------|------|------|
| `standard` | 默认分词器，按词边界切分 | "搜索引擎" → ["搜", "索", "引", "擎"] |
| `ik_smart` | 中文分词器（粗粒度） | "搜索引擎" → ["搜索引擎"] |
| `ik_max_word` | 中文分词器（细粒度） | "搜索引擎" → ["搜索引擎", "搜索", "引擎"] |

> ⚠️ 中文分词必须使用 IK 分词器，否则会把每个汉字拆开，搜索效果极差。

---

## 3. 在本项目中的角色

在本项目（掌柜问数 NL2SQL Agent）中，ES 用于**存储表名、字段名、别名、描述等元数据的全文索引**，实现**关键词级别的表/字段检索**。

```
用户问题: "上个月的销售额是多少"
     ↓
ES 全文检索:
  - "销售额" 匹配 → fact_order.order_amount（订单金额）
  - "上个月" 匹配 → fact_order.order_date（订单日期）
     ↓
Agent 生成 SQL: SELECT SUM(order_amount) FROM fact_order 
                WHERE order_date >= '2025-06-01'
```

ES 和 Qdrant 在本项目中**互补配合**：
- **ES**：关键词精确/模糊匹配（"销售额" → "order_amount"）
- **Qdrant**：语义相似度匹配（"赚了多少钱" → "order_amount"）

---

## 4. 本项目客户端实现

在 `data-agent/app/clients/es_client_manager.py` 中：

```python
from typing import Optional
from elasticsearch import AsyncElasticsearch

class ESClientManager:
    """Elasticsearch异步客户端管理器"""

    def __init__(self, es_config: ESConfig):
        self.es_config = es_config
        self.client: Optional[AsyncElasticsearch] = None

    def _get_url(self):
        return f"http://{self.es_config.host}:{self.es_config.port}"

    def init(self):
        self.client = AsyncElasticsearch(hosts=[self._get_url()])

    async def close(self):
        await self.client.close()

# 全局实例
es_client_manager = ESClientManager(app_config.es)
```

### 4.1 为什么用异步客户端？

- `AsyncElasticsearch` 基于 `aiohttp` 的异步 HTTP 客户端
- 与 FastAPI 异步生态匹配
- 不阻塞事件循环

---

## 5. 核心 API 操作详解

### 5.1 创建索引（定义 Mapping）

```python
await client.indices.create(
    index="my_books",
    mappings={
        "dynamic": False,          # 禁止动态添加字段（严格模式）
        "properties": {
            "name": {
                "type": "text"     # 全文搜索类型
            },
            "author": {
                "type": "text"     # 全文搜索类型
            },
            "release_date": {
                "type": "date",    # 日期类型
                "format": "yyyy-MM-dd"
            },
            "page_count": {
                "type": "integer"  # 整数类型
            }
        }
    },
)
```

#### 字段类型说明

| 类型 | 用途 | 示例 |
|------|------|------|
| `text` | 全文搜索，会被分词 | 书名、描述、内容 |
| `keyword` | 精确匹配，不分词 | 状态码、标签、ID |
| `date` | 日期类型 | 发布日期 |
| `integer` / `long` | 整数 | 页数、数量 |
| `float` / `double` | 浮点数 | 价格、评分 |
| `boolean` | 布尔 | 是否启用 |

**`dynamic: False`**：禁止自动添加未在 mapping 中定义的字段，防止数据结构混乱。

### 5.2 批量插入数据（Bulk）

```python
await client.bulk(
    operations=[
        {"index": {"_index": "my_books"}},
        {
            "name": "Revelation Space",
            "author": "Alastair Reynolds",
            "release_date": "2000-03-15",
            "page_count": 585
        },
        {"index": {"_index": "my_books"}},
        {
            "name": "1984",
            "author": "George Orwell",
            "release_date": "1985-06-01",
            "page_count": 328
        },
        # ... 更多文档
    ],
)
```

**Bulk API 格式说明**：

```
{操作元数据}
{文档数据}
{操作元数据}
{文档数据}
...
```

每两条为一组：
- 第一条：指定操作类型（index/create/update/delete）和目标索引
- 第二条：文档的实际数据

### 5.3 全文搜索（Match Query）

```python
resp = await client.search(
    index="my_books",
    query={
        "match": {
            "name": "brave"    # 搜索书名中包含 "brave" 的文档
        }
    },
)
```

**Match Query 特点**：
- 会对搜索词进行分词
- 使用 BM25 算法计算相关性得分
- 默认按得分降序排列

### 5.4 多字段搜索（Multi-Match）

```python
resp = await client.search(
    index="my_books",
    query={
        "multi_match": {
            "query": "brave world",
            "fields": ["name", "author"]   # 同时在书名和作者中搜索
        }
    }
)
```

### 5.5 精确匹配（Term Query）

```python
resp = await client.search(
    index="my_books",
    query={
        "term": {
            "author.keyword": "George Orwell"   # 精确匹配，不分词
        }
    }
)
```

> ⚠️ `term` 查询用于 `keyword` 类型字段，不会分词，用于精确匹配。

---

## 6. ES 在 NL2SQL 场景中的实际应用

### 6.1 表/字段检索

```python
# 搜索与用户问题相关的表
resp = await client.search(
    index="data_agent",
    query={
        "multi_match": {
            "query": "上个月的销售额",
            "fields": [
                "table_name",        # 表名
                "table_description", # 表描述
                "column_name",       # 字段名
                "column_description",# 字段描述
                "column_alias"       # 字段别名
            ]
        }
    }
)
```

### 6.2 别名匹配

用户可能使用不同的表述方式，ES 通过别名匹配建立映射：

```
用户说的 "销售额" → ES 匹配 → 字段别名 "sales_amount" → 实际字段 "order_amount"
用户说的 "下单时间" → ES 匹配 → 字段别名 "order_time" → 实际字段 "order_date"
```

---

## 7. 总结

| 概念 | 说明 |
|------|------|
| Elasticsearch | 分布式全文搜索引擎，基于 Lucene |
| Index | 文档的集合，类比 MySQL 的表 |
| Document | 一条数据记录，JSON 格式 |
| Mapping | 定义字段类型和索引规则 |
| 倒排索引 | ES 的核心数据结构，实现毫秒级全文搜索 |
| Match Query | 全文搜索，会分词 |
| Term Query | 精确匹配，不分词 |
| Bulk API | 批量操作，高性能插入 |
| `dynamic: False` | 禁止动态映射，保持数据结构一致 |

**在本项目中的核心价值**：为表名、字段名、别名、描述等元数据提供全文检索能力，支持用户通过关键词快速定位到相关的数据库表和字段，是 NL2SQL 智能体中的**关键词匹配引擎**。\