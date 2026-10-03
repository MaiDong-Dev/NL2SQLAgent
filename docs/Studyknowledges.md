# 知识点积累

> 项目开发过程中的知识点问答沉淀。按「问题 → 解答」组织，尽量附上本仓真实代码位置与实测数据，便于日后复习。
> 规则：每解答一个问题，追加一节到本文件。

## 目录

- [Q1 节点如何把执行结果传给下一个节点（LangGraph state 机制）](#q1-节点如何把执行结果传给下一个节点langgraph-state-机制)
- [Q2 jieba extract_tags 为什么不用传 topK](#q2-jieba-extract_tags-为什么不用传-topk)
- [Q3 PromptTemplate 的 input_variables 是什么（模板变量契约）](#q3-prompttemplate-的-input_variables-是什么模板变量契约)
- [Q4 `python main.py` 启动的到底是哪一层（服务启动边界）](#q4-python-mainpy-启动的到底是哪一层服务启动边界)

---

## Q1 节点如何把执行结果传给下一个节点（LangGraph state 机制）

### 问题

`server/agent/nodes/` 下每个节点执行完自己的操作后，都要把结果放到 state 中给下一个节点——这套机制到底是怎么工作的？

### 解答

#### 1. 机制：节点不"往 state 里塞"，而是 return 增量

严格说节点**没有**权限直接改 state。正确流程：

```
节点读 state 的入参字段 → 干活 → return {"我负责的字段": 值}
                                    ↓
              LangGraph 框架拿这个 dict 做「浅合并」到 state
                                    ↓
                        下一个节点看到合并后的 state
```

```python
# server/agent/nodes/extract_keywords.py:58
return {"keywords": keywords}
```

只返回自己产出的那一个 key，**不回传整个 state**。这个区别很重要：如果在节点内部写 `state["keywords"] = keywords` 然后 return 空值/None，框架**不会**采纳这个就地修改——更新只认返回值。

#### 2. 三条通道的分工（最易混淆）

| 通道 | 放什么 | 谁写 | 特点 |
| --- | --- | --- | --- |
| **state** | 业务数据（query/keywords/table_infos/sql/error） | 节点 return | 节点间流转，可被 checkpoint 持久化 |
| **runtime.context** | 基础设施（mysql/qdrant/es repository、embedding client） | 启动时注入一次 | 节点只读，**不进 state** |
| **runtime.stream_writer** | SSE 进度/结果事件 | 任意时刻 | 直接推给前端，**不进 state** |

`execute_sql` 是理解分工的最佳例子——它是终点节点，结果不回 state，直接推 SSE，因此**函数没有 return**：

```python
# server/agent/nodes/execute_sql.py:22-43
async def execute_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    ...
    writer({"type": "result", "data": result})
```

为什么大对象（连接池、client）放 context 而不是 state？因为 state 要被 checkpoint 序列化和跨节点传递，塞一个 MySQL 连接池进去是灾难。

#### 3. 三个必须知道的坑

**坑一：浅合并是「整体覆盖」，不是追加。**

`correct_sql` 返回 `{"sql": result}` 就是把旧的错误 SQL 整个替换掉——这正是想要的。但想"往 list 里加一项"时，`return {"retrieved": [x]}` 会把之前的清空。

**坑二：并行节点在同一「超步」内，彼此的写入互不可见。**

LangGraph 用类似 BSP 的执行模型：`recall_column / recall_value / recall_metric` 属于同一超步，它们读到的都是**该超步开始时**的 state 快照，互相看不到对方刚写的东西。本仓让它们各写各的 key 才安全：

```python
# server/agent/state.py:74-76
retrieved_columns: list[ColumnInfo]   # 召回的字段信息
retrieved_values: list[ValueInfo]     # 召回的值信息
retrieved_metrics: list[MetricInfo]   # 召回的指标信息
```

若三个节点都写同一个 key，并行下就会互相覆盖丢数据。真需要"多节点往同一 list 累加"时，正确做法是给字段挂 reducer：`retrieved: Annotated[list, add]`，合并语义从"覆盖"变"追加"。

**坑三：并行分支必须写不同 key**——这是坑二的直接推论，也是 `merge_retrieved_info` 能安全 fan-in 三路的前提。

#### 4. state 不只是数据通道，还是控制流通道

`validate_sql` 把验证结果写进 `error`：

```python
# server/agent/nodes/validate_sql.py:39-43
return {"error": None}
...
return {"error": str(e)}
```

条件边**读这个字段**决定图往哪走：

```python
# server/agent/graph.py:131-133
graph_builder.add_conditional_edges("validate_sql",
                                    lambda state: "execute_sql" if state["error"] is None else "correct_sql",
                                    {"execute_sql": "execute_sql", "correct_sql": "correct_sql"})
```

#### 5. 本仓两个值得注意的真实细节

**其一：`merge_retrieved_info` 有一处「副作用式」写入，不走返回值。**

```python
# server/agent/nodes/merge_retrieved_info.py:79-80
if column_value not in retrieved_columns_map[column_id].examples:
    retrieved_columns_map[column_id].examples.append(column_value)
```

这是在 `ColumnInfo` **对象上原地 append**，靠同一进程内共享对象引用才生效，并不经过 state 合并。单进程没问题，但将来若开启跨进程/反序列化式 checkpoint，这类就地修改会失效——属于隐性依赖。

**其二：`state.py` 注释与实现对不上一处。** 注释写 error「由 correct_sql 消费后清空」：

```python
# server/agent/state.py:69
#  9. error  → validate_sql 节点设置，correct_sql 节点消费后清空
```

但 `correct_sql` 实际只返回 SQL，没清 error：

```python
# server/agent/nodes/correct_sql.py:63
return {"sql": result}
```

当前**无功能影响**（`execute_sql` 不读 error，之后就到 END），但若以后加"二次校验循环"，残留 error 会让条件边误判成仍失败。要么补 `return {"sql": result, "error": None}`，要么改注释。

#### 6. 为什么这套设计好：可测试

因为节点"只读入参、只返回增量"，所以能脱离整个图单独跑，每个节点底部的 `__main__` 就是这个用法：

```python
# server/agent/nodes/extract_keywords.py:78
state: DataAgentState = {"query": query}  # 构造最小可用 state
```

构造一个只有 `query` 的最小 dict 直接调用函数断言返回值——不需要 MySQL、不需要 Qdrant、不需要编译图。

### 一句话总结

**节点 return 的是「我改了什么」，不是「完整的 state」；合并由框架做，且在下一个超步才对下游可见。**

---

## Q2 jieba extract_tags 为什么不用传 topK

### 问题

```python
keywords = jieba.analyse.extract_tags(query, allowPOS=allow_pos)
```

这里为什么不传 `topK`？

### 解答

#### 1. 默认 topK=20，但在本场景下恒不生效

签名实测：

```python
(sentence, topK=20, withWeight=False, allowPOS=(), withFlag=False)
```

实际返回（用 `extract_keywords.py` 的测试用例跑的，未加词性过滤时）：

| 问句 | 默认（topK=20） | topK=None（不截断） |
| --- | --- | --- |
| 查询上个月北京地区销售额最高的前10个商品 | 7 个 | 7 个 |
| 统计2024年每个季度的活跃用户数 | 6 个 | 6 个 |
| 张三的订单记录 | 3 个 | 3 个 |
| 订单 | 1 个 | 1 个 |

**每一条两种结果数量完全相同** —— 20 这个上限一次都没摸到。传不传 `topK` 在这里等价，所以不传是合理的（不写无意义的参数）。

#### 2. 根因：短句下 TF-IDF 退化成 IDF 排序

`extract_tags` 内部：

```python
freq[k] *= self.idf_freq.get(k, self.median_idf) / total   # total = 所有词频之和
...
if topK: return tags[:topK]        # 只截断，不做阈值过滤
```

关键在 `total`：一条短问句里每个实词基本只出现一次，TF 都是 `1/n`，**n 对所有人一样**，所以权重排序实际只由 IDF（词的稀有程度）决定。

后果：候选词数量 = 分词后过掉停用词与词性过滤剩下的词数，通常远小于 20。`topK=20` 在这里就是个**永远不会被触发的保险丝**。

#### 3. 那为什么连"调小"都不做：召回种子的不对称代价

```python
# server/agent/nodes/extract_keywords.py:50-54
keywords = jieba.analyse.extract_tags(query, allowPOS=allow_pos)

# 去重 + 保留原始查询作为兜底关键词
keywords = list(set(keywords + [query]))
```

要害是这个**不对称**：漏召回 = 字段根本进不了候选集，后面再也救不回来；多召回 = 后面还有 `filter_table` / `filter_metric` 两个 LLM 节点专门裁剪。所以策略必然是"宁多勿少"，主动把 topK 压小（如设成 5）只会增加漏召回风险，换不来收益。

真正起过滤作用的是 **`allowPOS`**（只留名词/动词/形容词等实词），不是 topK。对比：不加 `allowPOS` 时"我想看一下"会抽出"一下"这种无信息量的词，加词性过滤后这类词就没了。

`+ [query]` 是第二重保险：遇到纯虚词问句（分词后一个实词都没有）时，至少还有原始整句能当检索种子。

#### 4. 什么时候必须传 topK

- **长文本**：几百字的需求描述，实词轻松超过 20 个，默认会**静默截断**丢词，而且丢的是 IDF 最低的（往往是领域专有词）——必须显式调大。
- **想要全部**：`topK=None` 或 `0`（源码是 `if topK:` 判断，falsy 值不截断）。
- **想压噪音**：可以调小，但本仓有下游 LLM 裁剪节点，不必在这里做。

#### 5. 附带发现：set 去重会丢掉权重顺序

```python
keywords = list(set(keywords + [query]))
```

`extract_tags` 本来按权重从高到低返回，经过 `set` 之后顺序变成 hash 序（Python 对 str 的 hash 有随机化，不同进程顺序可能不同）。

当前**没有 bug**：三个召回节点拿关键词是"无序集合"语义，向量检索不受顺序影响。但若将来要把"最重要的 N 个关键词"按权重展示给 LLM 或前端，得改成保序去重：

```python
keywords = list(dict.fromkeys(keywords + [query]))
```

#### 6. 补充：`set()` 到底是什么

**它不是方法，是 Python 的内置类型（类）**。`set` 本身是一个 type，`set(x)` 是调用它的构造函数来生成一个集合实例：

```python
>>> type(set)          # <class 'type'>   ← set 是个类，不是函数、更不是"方法"
>>> type(set([1, 2]))  # <class 'set'>
```

区别在哪：**方法**是依附于对象的函数（如 `list.append`、`str.split`，必须写成 `obj.method()`）；而 `set()` 是**可直接调用的内置构造器**，和 `list()`、`dict()`、`int()`、`tuple()` 是同一类东西。

集合（set）的三个特性：

| 特性 | 说明 |
| --- | --- |
| **元素唯一** | 自动去重——本仓用它就是为这个 |
| **无序** | 迭代顺序由元素 hash 决定，与插入顺序无关 |
| **元素必须可哈希** | str / int / tuple 可以，list / dict 不行（`set([[1]])` 会 TypeError） |

拆解本仓这一行：

```python
keywords = list(set(keywords + [query]))
#          ③    ②      ①          ①
```

1. `keywords + [query]`：列表拼接，把原始问句追加到末尾当兜底
2. `set(...)`：转成集合，重复的词自动消失
3. `list(...)`：再转回列表——因为 JSON 序列化不支持 set，下游遍历与 prompt 拼接也按 list 用

**两个坑**：

- **空集合必须写 `set()`**：写 `{}` 得到的是空**字典**（`type({})` → `dict`），这是最经典的陷阱。
- **转 set 即丢失顺序与重复信息**：本行不关心顺序所以无妨；若要保序去重见第 5 点的 `dict.fromkeys`。

顺带一个常见用途：`x in some_set` 的成员判断是 **O(1)**，而 list 是 O(n)——大数据量下用 set 做"是否存在"判断会快很多。

### 一句话总结

**不传 topK 是因为在这个短问句场景下它恒不生效，真正干过滤活的是 `allowPOS`；不主动调小则是因为召回种子的漏召代价远高于误召代价。**

---

## Q3 PromptTemplate 的 input_variables 是什么（模板变量契约）

### 问题

```python
# server/agent/nodes/recall_column.py:55-58
prompt = PromptTemplate(
    template=load_prompt("extend_keywords_for_column_recall"),
    input_variables=["query"],
)
```

`input_variables=["query"]` 这个参数什么意思？能不能不写？写错了会怎样？

### 解答

#### 1. 它声明的是「调用这个模板必须提供哪些变量」

`PromptTemplate` 做的是**字符串模板渲染**，默认 `template_format="f-string"`，即模板里的 `{xxx}` 是占位符，`format()` / `invoke()` 时按名字替换。

本仓这条 prompt 文件末尾就是变量插入点：

```55:58:prompts/extend_keywords_for_column_recall.prompt
用户问题：
{query}

输出：
```

所以 `input_variables=["query"]` 的字面意思是：「这个模板有一个待填的坑，名字叫 `query`」。它对应的是调用侧：

```63:63:server/agent/nodes/recall_column.py
result = await chain.ainvoke({"query": query})
```

`chain.ainvoke()` 收到的 dict 会一路传给首元素 `prompt`，dict 的 key 就是 `input_variables` 声明的名字——**dict key 与 input_variables 必须同名**，这是最容易写错的地方。

#### 2. 实测：写不写都能跑，写错了也不报错（langchain_core 1.2.7）

用一个含 `{query}` 和 `{table_infos}` 两个变量的模板实测：

| 声明方式 | 实际得到的 input_variables | 是否报错 |
| --- | --- | --- |
| 不传（省略该参数） | `['query', 'table_infos']`（自动推断） | 否 |
| `["query"]`（**少声明**） | `['query', 'table_infos']`（被模板覆盖） | **否** |
| `["query", "table_infos"]` | 同上 | 否 |
| `["query", "table_infos", "extra"]`（**多声明**） | `['query', 'table_infos']`（extra 被丢弃） | **否** |
| `["query"]` + `validate_template=False` | `['query', 'table_infos']` | 否 |

**结论很重要**：在本版本里 `input_variables` 是**文档性参数，不是强校验**。LangChain 会用模板里真实的 `{}` 反过来覆盖你的声明，所以：

- 声明少了 → 不会报「缺少变量」，静默按模板来；
- 声明多了 → 不会报「多余变量」，静默丢掉。

也就是说，本仓这行 `input_variables=["query"]` 的实际作用是**自文档**（读代码的人一眼知道要传什么），加上 IDE 补全/阅读时的提示，**不写它代码也照跑**。

#### 3. 那什么时候真会报错？——在 `format` 阶段，不在构造阶段

| 调用 | 实测结果 |
| --- | --- |
| `prompt.format(query="X")`（模板有 `{table_infos}`，少传） | **`KeyError: 'table_infos'`** |
| `prompt.format(query="X", table_infos="T", unused="U")`（多传） | 正常，`unused` 被静默忽略 |

所以真正的契约不在 `input_variables`，而在**模板文本里的 `{}`**：

- 少传 → 运行到调用才炸（`KeyError`），且是**每次节点执行时**才炸，不是启动时；
- 多传 → 永远静默，不会提示你写多了。

这也解释了为什么 `recall_column` 的 `chain.ainvoke({"query": query})` 只传一个 key 就够——因为它的 prompt 文件里**只有一个** `{query}`。而 `filter_table` 的 prompt 有两个占位符：

```46:46:server/agent/nodes/filter_table.py
prompt = PromptTemplate(template=load_prompt("filter_table_info"), input_variables=["query", "table_infos"])
```

对应 `prompts/filter_table_info.prompt` 里的 `{query}`（第 57 行）和 `{table_infos}`（第 60 行），传参也是两个：

```51:52:server/agent/nodes/filter_table.py
result = await chain.ainvoke(
    {"query": query, "table_infos": yaml.dump(table_infos, allow_unicode=True, sort_keys=False)})
```

#### 4. 附带的坑：prompt 文件里的 JSON 花括号必须写成 `{{ }}`

因为模板用的是 f-string 语法，**任何** `{` `}` 都会被当成变量。所以 prompt 里凡是写 JSON 示例，都要双写转义：

```48:52:prompts/filter_table_info.prompt
输出格式（严格遵守）：
{{
    "表名1":["字段1", "字段2", "..."],
    "表名2":["字段1", "字段2", "..."]
}}
```

实测：`{{ "a": ["b"] }}` 渲染后正确输出 `{ "a": ["b"] }`；而**不转义**时 LangChain 会把 `{ "a"` 当成一个变量名，推断出 `' "a"'` 这种垃圾变量——**构造时不报错，直到 `format` 才 `KeyError`**。

好的排查习惯：不确定某个 prompt 抽出了哪些变量时，直接打印：

```python
PromptTemplate(template=load_prompt("xxx")).input_variables
```

#### 5. 两套「契约」别混（呼应 Q1）

| 契约 | 谁和谁之间 | 载体 |
| --- | --- | --- |
| **节点间契约** | 节点 → 节点 | `state` 的 key（节点 return 的 dict，见 Q1） |
| **节点内契约** | 节点 → prompt 模板 | `input_variables` / 模板里的 `{}` |

`state["query"]` 和 `input_variables=["query"]` 里的 `query` 只是**恰好同名**（都是从业务问句来的），两者没有任何框架级关联——改名其中一个，另一个不会跟着变，也不会报错。

#### 6. 补充：为什么这里是 `PromptTemplate` 而不是 `ChatPromptTemplate`

`PromptTemplate` 产出的是**纯文本**（`PromptValue`），喂给 ChatModel 时会被自动包成一条 `HumanMessage`；`ChatPromptTemplate` 则是产出**消息列表**，支持 `("system", "...") / ("human", "...")` 分段。

本仓 7 个节点全用 `PromptTemplate`，因为 prompt 是单个 `.prompt` 文件整体加载、且是"指令 + 输入"混在一段文本里的结构（`{query}` 嵌在文本末尾），改成分段消息要动所有 prompt 文件——收益（更清晰的角色区分）不抵改动成本。

### 一句话总结

**`input_variables` 是「这个模板要填哪些坑」的声明，但在 langchain_core 1.2.7 下它会被模板里的 `{}` 推断结果覆盖、写错静默不报；真正的硬契约是模板文本中的 `{变量}`——少传在 `format` 时抛 `KeyError`，多传静默忽略，prompt 里写 JSON 示例必须 `{{ }}` 转义。**

---

## Q4 `python main.py` 启动的到底是哪一层（服务启动边界）

### 问题

```python
# main.py:30
uvicorn.run(app, host="0.0.0.0", port=8000)
```

跑 `python main.py` 是不是就等于把整个系统起来了？

### 解答

#### 1. 它只启动「Web 进程」这一层

`main.py` 全文只做三件事：

```10:13:main.py
app = FastAPI(lifespan=lifespan) 
# 注册路由
app.include_router(query_router)
```

1. 创建 FastAPI 应用，挂上 `lifespan`；
2. 注册路由——**全项目只有一条业务接口**：

```28:29:server/api/routers/query_router.py
@query_router.post("/api/query")
async def query(
```

   所以访问 `GET /` 必然 404（今天日志里那两条 `GET / 404` 就是这个，不是故障）；
3. `lifespan` 在启动时初始化 5 个客户端、关闭时释放：

```44:49:server/core/lifespan.py
    embedding_client_manager.init()
    qdrant_client_manager.init()
    es_client_manager.init()
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()
```

#### 2. 三件它**不做**的事（这才是"整个服务"的其余部分）

| 组成部分 | 由谁启动 | 说明 |
| --- | --- | --- |
| **中间件**（MySQL meta+dw、Qdrant、ES、Embedding） | `deploy` 下 `docker compose up -d` | 外部进程，`main.py` 只是去连它 |
| **元知识库**（表/字段/指标 → 三存储） | `scripts/rebuild_meta.py` 或 `meta_builder` 构建脚本 | 独立离线任务，见 Q3 同期记录的重建过程 |
| **前端页面** | `frontend` 下 `npm run dev` | 独立 Node 进程，靠 Vite `/api` 代理打到 8000 |

`lifespan.py` 的注释也写明了这个边界：

```21:21:server/core/lifespan.py
#   - 注意：此处只初始化连接，不执行元知识构建（构建由 meta_builder/scripts/build_meta_knowledge.py 独立触发）
```

#### 3. 最关键的陷阱：`startup complete` ≠ 依赖可用

看 MySQL 客户端的 `init()`：

```65:67:server/clients/mysql_client_manager.py
        self.engine = create_async_engine(url=self._get_url(),
                                          pool_size=10,
                                          pool_pre_ping=True)
```

`create_async_engine` **不发一个包**，只是建好引擎和连接池；真正的握手要等第一次取连接（`pool_pre_ping=True` 也是在取连接时才 ping）。

后果：**MySQL / Qdrant / ES 全挂了，`python main.py` 照样打印 `Application startup complete`**，错误要等到第一次 `/api/query` 才以 500 或节点异常的形式冒出来。

所以判断"服务真的可用"不能看启动日志，要看依赖体检。项目里已经有这个工具：

```bash
python -m scripts.check_services          # 6 项：mysql-meta / mysql-dw / qdrant / es / embedding / llm
```

它真的会连一次（不是建引擎了事），并且**失败返回退出码 1**，可以直接用在 CI 或 shell 判断里：

```python
# scripts/check_services.py:19
#  退出码：全部通过返回 0，存在失败项返回 1（可直接用于 CI / shell 判断）。
```

#### 4. 本仓实测（2026-10-03，重建元知识后）

```
[PASS] mysql-meta      0.10s  MySQL 8.0.46 · 库 meta · 4 张表
[PASS] mysql-dw        0.04s  MySQL 8.0.46 · 库 dw · 5 张表
[PASS] qdrant          0.21s  column 98 条；metric 8 条
[PASS] elasticsearch   0.01s  ES 8.19.10 · data-agent-value 2038 条
[PASS] embedding       0.26s  wl:8081 · 输出维度 1024（Qdrant 配置 1024）
[PASS] llm             1.74s  deepseek-v4-flash · 回复：正常
结果：6/6 通过
```

注意 `embedding` 那项会**校验实际输出维度与 `qdrant.embedding_size` 是否一致**——这是最容易被忽略的一类配置错误：向量维度不匹配时，写入会在 Qdrant 侧才报错，排查成本很高。

#### 5. 完整启动清单

```bash
# ① 中间件（只跑一次，容器起来后就一直在）
cd deploy && docker compose up -d
python -m scripts.check_services          # 体检，6/6 才算就绪

# ② 元知识（首次或数据源变更后）
python -m scripts.rebuild_meta -c conf/meta_config.yaml

# ③ 后端
uv run python main.py                     # 或 uvicorn main:app --reload 开热重载

# ④ 前端
cd frontend && npm run dev                # http://localhost:5173
```

开发时想改代码自动重启，用 `uvicorn main:app --reload` 代替 `python main.py`（后者是 `__main__` 里写死 `uvicorn.run`，也能跑，但没有 reload）。

### 一句话总结

**`main.py` 只负责「FastAPI 进程」——建应用、挂唯一接口 `/api/query`、在 lifespan 里初始化 5 个客户端；中间件、元知识、前端是另外三个独立的东西。而且因为 `init()` 只是建引擎（懒连接），启动日志成功不代表依赖可用，用 `python -m scripts.check_services` 体检才是准的。**
