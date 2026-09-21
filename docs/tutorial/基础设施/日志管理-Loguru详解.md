# 日志管理 — Loguru 详解

## 1. 为什么需要日志？

在项目开发中，日志是**调试和排错的第一工具**。很多开发者习惯用 `print()` 来调试，但它有致命缺陷：

| print() | 日志系统 |
|---------|---------|
| 只能输出到控制台 | 可同时输出到控制台 + 文件 |
| 无时间戳 | 自动记录精确时间（毫秒级） |
| 无级别区分 | 支持 DEBUG/INFO/WARNING/ERROR/CRITICAL |
| 无法追踪请求 | 可注入 request_id 实现请求链路追踪 |
| 生产环境无法关闭 | 可按级别动态开关 |
| 无文件分割 | 自动按大小/时间分割日志文件 |

> **名言**："日志功能对于任何应用程序而言都是不可或缺的核心环节，它能极大简化调试过程。"

---

## 2. Loguru 概述

[Loguru](https://loguru.readthedocs.io/en/stable/) 是一个致力于为 Python 带来**"愉悦式日志体验"**的库。

### 2.1 为什么选 Loguru 而不是标准库 logging？

| 特性 | Python logging | Loguru |
|------|---------------|--------|
| 配置复杂度 | 需要 Logger、Handler、Formatter 三者配合 | 一行代码即可 |
| 默认输出 | 无（需要手动配置） | 开箱即用，直接 `logger.info()` |
| 异常捕获 | 需要手动 `exc_info=True` | 自动捕获并美化输出 |
| 日志分割 | 需要 `RotatingFileHandler` | 内置 `rotation` 参数 |
| 日志保留 | 需要 `TimedRotatingFileHandler` | 内置 `retention` 参数 |
| 颜色支持 | 需要第三方库 | 原生支持彩色输出 |
| 结构化日志 | 不支持 | 支持 `bind()` 绑定上下文 |
| 异步安全 | 需要额外处理 | 天然支持多线程/异步 |

### 2.2 快速入门

```python
from loguru import logger

# 开箱即用，无需任何配置
logger.info("服务启动成功")
logger.warning("内存使用率超过 80%")
logger.error("接口调用失败：超时")
logger.critical("数据库连接中断，服务停止")
```

输出效果：

```
2025-07-17 14:30:25.123 | INFO     | __main__:<module>:1 - 服务启动成功
2025-07-17 14:30:25.124 | WARNING  | __main__:<module>:2 - 内存使用率超过 80%
2025-07-17 14:30:25.125 | ERROR    | __main__:<module>:3 - 接口调用失败：超时
2025-07-17 14:30:25.126 | CRITICAL | __main__:<module>:4 - 数据库连接中断，服务停止
```

---

## 3. 日志级别

Loguru 提供 7 个日志级别，从低到高：

| 级别 | 方法 | 用途 | 示例场景 |
|------|------|------|---------|
| TRACE | `logger.trace()` | 最详细的调试信息 | 函数进入/退出、变量值变化 |
| DEBUG | `logger.debug()` | 调试信息 | SQL 语句打印、中间变量值 |
| INFO | `logger.info()` | 常规运行信息 | 服务启动、请求处理完成 |
| SUCCESS | `logger.success()` | 成功信息（Loguru 独有） | 数据同步完成、任务执行成功 |
| WARNING | `logger.warning()` | 警告信息 | 内存使用率高、配置项缺失使用默认值 |
| ERROR | `logger.error()` | 错误信息 | 接口调用失败、数据处理异常 |
| CRITICAL | `logger.critical()` | 严重错误 | 数据库连接中断、服务不可用 |

**级别过滤**：

```python
# 控制台只输出 INFO 及以上级别
logger.add(sys.stdout, level="INFO")
# 文件输出 DEBUG 及以上级别
logger.add("app.log", level="DEBUG")
```

---

## 4. 本项目日志实现

### 4.1 架构设计

```
┌─────────────────────────────────────────────────┐
│                  日志架构                         │
├─────────────────────────────────────────────────┤
│  conf/app_config.yaml                           │
│  └── logging: { file: {...}, console: {...} }   │
│                    ↓ 读取配置                    │
│  app/core/log.py                                │
│  ├── 日志格式定义                                │
│  ├── request_id 注入（通过 ContextVar）           │
│  ├── 控制台输出器（sink=sys.stdout）              │
│  └── 文件输出器（sink=logs/app.log）             │
│                    ↑ 使用                        │
│  所有业务模块: from loguru import logger         │
└─────────────────────────────────────────────────┘
```

### 4.2 日志格式

```python
log_format = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "      # 时间（绿色）
    "<level>{level: <8}</level> | "                          # 级别（按级别着色）
    "<magenta>request_id - {extra[request_id]}</magenta> | " # 请求ID（品红色）
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "  # 位置（青色）
    "<level>{message}</level>"                               # 消息内容（按级别着色）
)
```

**格式占位符说明**：

| 占位符 | 含义 | 示例 |
|--------|------|------|
| `{time:YYYY-MM-DD HH:mm:ss.SSS}` | 日志时间，精确到毫秒 | `2025-07-17 14:30:25.123` |
| `{level: <8}` | 日志级别，左对齐占 8 字符 | `INFO    ` |
| `{extra[request_id]}` | 自定义字段，请求唯一标识 | `a1b2c3d4-...` |
| `{name}` | 模块/文件名 | `main` |
| `{function}` | 函数名 | `test` |
| `{line}` | 行号 | `42` |
| `{message}` | 日志正文 | `服务启动成功` |

**颜色标记**：

| 标记 | 颜色 |
|------|------|
| `<green>...</green>` | 绿色 |
| `<magenta>...</magenta>` | 品红色 |
| `<cyan>...</cyan>` | 青色 |
| `<level>...</level>` | 自动按级别着色 |

### 4.3 核心代码

在 `data-agent/app/core/log.py` 中：

```python
import sys
from pathlib import Path
from loguru import logger
from app.core.context import request_id_ctx_var

# 自定义日志格式
log_format = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<magenta>request_id - {extra[request_id]}</magenta> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
    "<level>{message}</level>"
)

# request_id 注入函数
def inject_request_id(record):
    """为每条日志注入 request_id，实现请求链路追踪"""
    try:
        request_id = request_id_ctx_var.get()
    except Exception:
        request_id = uuid.uuid4()
    record["extra"]["request_id"] = request_id

# 移除默认输出器
logger.remove()

# 注入 request_id 补丁
logger = logger.patch(inject_request_id)

# 控制台输出器
if app_config.logging.console.enable:
    logger.add(
        sink=sys.stdout,
        level=app_config.logging.console.level,
        format=log_format
    )

# 文件输出器
if app_config.logging.file.enable:
    path = Path(app_config.logging.file.path)
    path.mkdir(parents=True, exist_ok=True)
    logger.add(
        sink=path / "app.log",
        level=app_config.logging.file.level,
        format=log_format,
        rotation=app_config.logging.file.rotation,
        retention=app_config.logging.file.retention,
        encoding="utf-8"
    )
```

---

## 5. 关键特性详解

### 5.1 request_id 注入 — 请求链路追踪

这是本项目日志系统最精妙的设计。在**多用户并发请求**的场景下，如何区分不同请求的日志？

**问题场景**：

```
[14:30:25] INFO  | 用户查询: 上个月销售额    ← 谁的请求？
[14:30:25] INFO  | 检索到表: fact_order     ← 谁的请求？
[14:30:25] INFO  | 生成SQL: SELECT ...      ← 谁的请求？
[14:30:26] INFO  | 用户查询: 本月新增用户    ← 另一个请求混在一起！
```

**解决方案**：使用 `ContextVar` + `logger.patch()` 为每条日志自动注入 request_id。

#### ContextVar（上下文变量）

```python
from contextvars import ContextVar

request_id_ctx_var = ContextVar("request_id", default=1)
```

`ContextVar` 是 Python 3.7+ 引入的**异步安全**变量存储机制：

- 每个异步任务有自己独立的上下文
- 不同协程之间互不干扰
- 请求 A 设置的 `request_id` 不会污染请求 B

**工作原理**：

```
请求1 (request_id="aaa")        请求2 (request_id="bbb")
     │                                │
     ├─ ContextVar.get() → "aaa"      ├─ ContextVar.get() → "bbb"
     │                                │
     ├─ logger.info("...")            ├─ logger.info("...")
     │  → request_id=aaa              │  → request_id=bbb
     │                                │
     └─ 互不干扰！                     └─ 互不干扰！
```

#### logger.patch()

```python
logger = logger.patch(inject_request_id)
```

`patch()` 方法会在**每条日志输出前**执行 `inject_request_id` 函数，将当前请求的 `request_id` 注入到日志的 `extra` 字段中。

#### 效果对比

**不使用 request_id**：

```
2025-07-17 14:30:25.123 | INFO     | main:test:42 - 开始查询
2025-07-17 14:30:25.124 | INFO     | main:test:43 - 开始查询  ← 分不清谁是谁
2025-07-17 14:30:25.125 | INFO     | agent:run:88 - 检索元数据
2025-07-17 14:30:25.126 | INFO     | agent:run:89 - 检索元数据  ← 混在一起
```

**使用 request_id**：

```
2025-07-17 14:30:25.123 | INFO     | request_id - a1b2c3d4 | main:test:42 - 开始查询
2025-07-17 14:30:25.124 | INFO     | request_id - e5f6g7h8 | main:test:43 - 开始查询
2025-07-17 14:30:25.125 | INFO     | request_id - a1b2c3d4 | agent:run:88 - 检索元数据
2025-07-17 14:30:25.126 | INFO     | request_id - e5f6g7h8 | agent:run:89 - 检索元数据
                         ↑ 一目了然！可以通过 request_id 过滤出单个请求的完整链路
```

### 5.2 rotation — 日志文件分割

```python
rotation="10 MB"       # 单个文件达到 10MB 时自动分割
rotation="00:00"       # 每天凌晨 0 点自动分割
rotation="1 week"      # 每周自动分割
```

分割后的文件命名示例：

```
app.log              ← 当前日志
app.log.2025-07-15   ← 历史日志（自动归档）
app.log.2025-07-14
```

### 5.3 retention — 日志保留策略

```python
retention="7 days"    # 只保留最近 7 天的日志
retention="10"        # 只保留最近 10 个日志文件
```

避免日志文件无限堆积占用磁盘空间。

### 5.4 sink — 输出目标

```python
# 控制台
logger.add(sink=sys.stdout, level="INFO")

# 文件
logger.add(sink="app.log", level="DEBUG")

# 网络（发送到日志收集服务）
logger.add(sink="http://log-server:8080/logs")

# 自定义函数
def my_sink(message):
    send_to_wechat(message)  # 发送到微信
logger.add(sink=my_sink, level="ERROR")
```

---

## 6. 完整测试示例

```python
import asyncio
from contextvars import ContextVar

request_id_ctx_var = ContextVar("request_id", default=1)

async def graph(request: str):
    id = request_id_ctx_var.get()
    logger.info(f"处理请求: {request}, request_id: {id}")

async def test1():
    request_id_ctx_var.set("111111111")
    await asyncio.sleep(1)
    await graph("request-1")

async def test2():
    request_id_ctx_var.set("2222222222")
    await asyncio.sleep(1)
    await graph("request-2")

async def main():
    # 并发执行两个请求
    await asyncio.gather(test1(), test2())

asyncio.run(main())
```

输出（两个请求的日志不会串）：

```
2025-07-17 14:30:25.123 | INFO     | request_id - 111111111 | main:graph:5 - 处理请求: request-1
2025-07-17 14:30:25.124 | INFO     | request_id - 2222222222 | main:graph:5 - 处理请求: request-2
```

---

## 7. 配置参数说明

```yaml
logging:
  file:
    enable: true          # 是否启用文件日志
    level: INFO           # 文件日志级别（DEBUG/INFO/WARNING/ERROR/CRITICAL）
    path: logs            # 日志文件存储目录
    rotation: "10 MB"     # 日志分割规则（大小/时间）
    retention: "7 days"   # 日志保留时长
  console:
    enable: true          # 是否启用控制台日志
    level: INFO           # 控制台日志级别
```

---

## 8. 注意事项

### 8.1 循环导入问题

日志模块 `app/core/log.py` 引用了 `conf` 中的 `app_config`，而其他模块引用 `logger`。如果 `conf` 模块也引用了 `logger`，就会形成循环导入：

```
app/core/log.py → conf/app_config.py → app/core/log.py  ← 循环导入！
```

**解决方案**：
- 保持 `conf/app_config.py` 不引用任何业务模块
- 日志模块只被引用，不引用其他业务模块（除了 conf）

### 8.2 生产环境建议

- 控制台日志级别设为 `INFO` 或 `WARNING`
- 文件日志级别设为 `DEBUG`（便于事后排查）
- 合理设置 `rotation` 和 `retention`，避免磁盘爆满
- 敏感信息（如密码、API Key）不要写入日志

---

## 9. 总结

| 概念 | 说明 |
|------|------|
| Loguru | 新一代 Python 日志库，开箱即用，配置简洁 |
| 日志级别 | TRACE < DEBUG < INFO < SUCCESS < WARNING < ERROR < CRITICAL |
| `logger.remove()` | 移除默认输出器 |
| `logger.add()` | 添加自定义输出器（控制台、文件、网络等） |
| `logger.patch()` | 日志输出前注入自定义信息（如 request_id） |
| `ContextVar` | 异步安全的上下文变量，每个协程独立 |
| `rotation` | 日志文件自动分割策略 |
| `retention` | 日志文件自动清理策略 |
| `sink` | 日志输出目标 |

**在本项目中的核心价值**：提供统一的日志管理方案，通过 `request_id` 实现多用户并发请求的链路追踪，配合控制台和文件双输出，确保开发调试和生产运维都能高效定位问题。\