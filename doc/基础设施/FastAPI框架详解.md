# FastAPI 框架详解

## 1. FastAPI 概述

[FastAPI](https://fastapi.org.cn/) 是一个**现代、高性能的 Python Web 框架**，用于构建 RESTful API。它基于 Python 3.7+ 的类型提示（Type Hints），自动生成交互式 API 文档，性能媲美 Node.js 和 Go。

### 1.1 为什么选择 FastAPI？

| 特性 | 说明 |
|------|------|
| **极高性能** | 基于 Starlette 和 Pydantic，性能与 Node.js/Go 相当 |
| **自动文档** | 自动生成 Swagger UI 和 ReDoc 交互式文档 |
| **类型安全** | 基于 Python 类型提示，自动校验请求参数 |
| **异步支持** | 原生 `async/await`，支持高并发 |
| **编辑器支持** | IDE 自动补全、类型检查 |
| **标准化** | 完全兼容 OpenAPI 和 JSON Schema |

### 1.2 与其他框架对比

| 框架 | 异步支持 | 自动文档 | 类型校验 | 性能 | 学习曲线 |
|------|---------|---------|---------|------|---------|
| **FastAPI** | ✅ 原生 | ✅ 自动 | ✅ 自动 | ⭐⭐⭐⭐⭐ | 低 |
| Flask | ❌ 需插件 | ❌ 需插件 | ❌ 手动 | ⭐⭐⭐ | 极低 |
| Django REST | ❌ 3.1+ 支持 | ❌ 需插件 | ❌ 手动 | ⭐⭐⭐ | 高 |
| Sanic | ✅ 原生 | ❌ 需插件 | ❌ 手动 | ⭐⭐⭐⭐ | 中 |

---

## 2. 快速入门

### 2.1 最小应用

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get("/items/{item_id}")
async def read_item(item_id: int, q: str = None):
    return {"item_id": item_id, "q": q}
```

**启动**：

```bash
fastapi dev main.py
# 或
uvicorn main:app --reload
```

**访问**：
- API 接口：`http://127.0.0.1:8000`
- 交互式文档：`http://127.0.0.1:8000/docs`
- 备用文档：`http://127.0.0.1:8000/redoc`

### 2.2 请求方法

```python
@app.get("/users")           # 查询
@app.post("/users")          # 创建
@app.put("/users/{id}")      # 全量更新
@app.patch("/users/{id}")    # 部分更新
@app.delete("/users/{id}")   # 删除
```

---

## 3. 核心功能详解

### 3.1 路径参数与查询参数

```python
from fastapi import FastAPI

app = FastAPI()

# 路径参数：URL 路径的一部分
@app.get("/users/{user_id}")
async def get_user(user_id: int):  # 自动类型转换！
    return {"user_id": user_id}

# 查询参数：? 后面的部分
@app.get("/users")
async def list_users(
    page: int = 1,           # 默认值 1
    size: int = 10,          # 默认值 10
    keyword: str | None = None  # 可选参数
):
    return {"page": page, "size": size, "keyword": keyword}
```

**请求示例**：

```
GET /users/9527          → {"user_id": 9527}
GET /users?page=2&size=20&keyword=张三  → {"page": 2, "size": 20, "keyword": "张三"}
```

### 3.2 请求体（Request Body）

使用 Pydantic 模型定义请求体，自动校验：

```python
from pydantic import BaseModel
from fastapi import FastAPI

app = FastAPI()

class UserCreate(BaseModel):
    name: str
    age: int
    email: str

@app.post("/users")
async def create_user(user: UserCreate):
    # user 已被自动校验和转换
    return {"name": user.name, "age": user.age, "email": user.email}
```

**自动校验**：

```json
// 发送：
{"name": "张三", "age": "25", "email": "zhangsan@example.com"}
// age 自动从 "25"（字符串）转换为 25（整数）

// 发送非法数据：
{"name": "张三", "age": "不是数字", "email": "zhangsan@example.com"}
// 返回 422 错误，精确指出 age 字段类型错误
```

**在本项目中的应用**：

```python
# app/api/schemas/query_schema.py
from pydantic import BaseModel

class QuerySchema(BaseModel):
    query: str  # 接收用户输入的查询字符串
```

### 3.3 路由（Router）

大型应用用 `APIRouter` 拆分路由：

```python
# app/api/routers/user_router.py
from fastapi import APIRouter

user_router = APIRouter(prefix="/users", tags=["用户管理"])

@user_router.get("/")
async def list_users():
    return [{"id": 1, "name": "张三"}]

@user_router.post("/")
async def create_user(user: UserCreate):
    return {"id": 2, "name": user.name}
```

```python
# main.py
from fastapi import FastAPI
from app.api.routers.user_router import user_router

app = FastAPI()
app.include_router(user_router)
```

**在本项目中的应用**：

```python
# main.py
from app.api.routers.query_router import query_router

app = FastAPI()
app.include_router(query_router)
```

---

## 4. 高级特性

### 4.1 流式响应（StreamingResponse）

`StreamingResponse` 用于**边生成边返回数据**，而不是等全部生成完毕再返回。

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

async def fake_video_streamer():
    """模拟视频流"""
    for i in range(10):
        await asyncio.sleep(1)  # 模拟处理延时
        yield f"data: 第{i}帧视频数据\n\n"

@app.get("/video")
async def stream_video():
    return StreamingResponse(
        fake_video_streamer(),
        media_type="text/event-stream"  # 指定 SSE 协议
    )
```

**为什么需要流式响应？**

| 方式 | 用户体验 | 适用场景 |
|------|---------|---------|
| 一次性返回 | 等待全部完成后才显示 | 简单查询 |
| 流式响应 | 实时看到进度和中间结果 | AI 对话、大文件传输、实时进度 |

**在本项目中的应用**：NL2SQL 智能体工作流有 12 个节点，执行时间较长。通过流式响应，用户可以实时看到每个节点的执行状态。

### 4.2 SSE（Server-Sent Events）协议

SSE 是**服务器向客户端单向推送事件**的协议，基于 HTTP 长连接。

**SSE 数据格式**：

```
data: 第一条消息\n\n
data: 第二条消息\n\n
data: {"stage": "extract_keywords", "status": "done"}\n\n
```

**MIME 类型**：`text/event-stream`

```python
return StreamingResponse(
    stream_generator(),
    media_type="text/event-stream"
)
```

**SSE vs WebSocket**：

| 特性 | SSE | WebSocket |
|------|-----|-----------|
| 通信方向 | 单向（服务器→客户端） | 双向 |
| 协议 | HTTP | 独立协议（ws://） |
| 自动重连 | 浏览器原生支持 | 需手动实现 |
| 复杂度 | 简单 | 较复杂 |
| 适用场景 | 进度推送、通知 | 实时聊天、游戏 |

**在本项目中的应用**：后端通过 SSE 向前端推送智能体工作流的执行进度和 SQL 生成结果。

### 4.3 生命周期事件（Lifespan）

在应用启动/关闭时执行初始化/清理操作。

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行
    print("应用启动中...")
    await init_database()
    await init_clients()
    yield  # 应用运行中
    # 关闭时执行
    print("应用关闭中...")
    await close_clients()
    await close_database()

app = FastAPI(lifespan=lifespan)
```

**在本项目中的应用**：

```python
# app/core/lifespan.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时初始化所有客户端
    dw_mysql_client_manager.init()
    meta_mysql_client_manager.init()
    qdrant_client_manager.init()
    es_client_manager.init()
    embedding_client_manager.init()
    yield
    # 关闭时释放资源
    await dw_mysql_client_manager.close()
    await meta_mysql_client_manager.close()
    await qdrant_client_manager.close()
    await es_client_manager.close()
```

### 4.4 中间件（Middleware）

中间件在**请求到达路由之前**和**响应返回之前**执行，用于全局处理。

```python
from fastapi import FastAPI, Request
import time

app = FastAPI()

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    # 请求前
    start_time = time.time()

    response = await call_next(request)  # 执行实际的路由处理

    # 响应前
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    return response
```

**常见中间件用途**：

| 用途 | 说明 |
|------|------|
| CORS | 跨域资源共享 |
| 请求日志 | 记录每个请求的信息 |
| 认证鉴权 | 验证 JWT Token |
| 性能监控 | 记录请求处理时间 |
| 异常处理 | 统一异常拦截和格式化 |

**在本项目中的应用**：为每个请求注入 `request_id`，实现请求链路追踪。

### 4.5 依赖注入（Dependency Injection）

依赖注入是 FastAPI 最强大的特性之一，用于**复用逻辑**和**解耦代码**。

```python
from fastapi import FastAPI, Depends

app = FastAPI()

# 定义一个依赖
async def get_db():
    db = await create_connection()
    try:
        yield db
    finally:
        await db.close()

# 使用依赖
@app.get("/users")
async def list_users(db = Depends(get_db)):
    return await db.query("SELECT * FROM users")

# 依赖可以嵌套
async def get_current_user(token: str = Depends(verify_token)):
    return await decode_token(token)

@app.get("/me")
async def me(user = Depends(get_current_user)):
    return user
```

**依赖注入的优势**：

1. **代码复用**：`get_db` 可以在多个路由中复用
2. **自动清理**：`yield` 后的代码在请求结束后自动执行
3. **可测试**：可以轻松替换依赖（如用 Mock 数据库）
4. **分层解耦**：路由只关心业务逻辑，不关心依赖如何创建

**在本项目中的应用**：

```python
# app/api/dependencies.py
async def get_query_service():
    """提供查询服务实例"""
    return QueryService()

# app/api/routers/query_router.py
@query_router.post("/api/query")
async def query(
    query: QuerySchema,
    service: QueryService = Depends(get_query_service)
):
    return StreamingResponse(service.execute(query.query), media_type="text/event-stream")
```

---

## 5. 项目结构最佳实践

```
project/
├── main.py                  # 入口文件
├── app/
│   ├── api/
│   │   ├── routers/         # 路由（接口定义）
│   │   │   ├── user_router.py
│   │   │   └── query_router.py
│   │   ├── schemas/         # 请求/响应模型
│   │   │   └── query_schema.py
│   │   └── dependencies.py  # 依赖注入
│   ├── services/            # 业务逻辑层
│   │   └── query_service.py
│   ├── core/                # 核心基础设施
│   │   ├── lifespan.py      # 生命周期事件
│   │   ├── context.py       # 上下文变量
│   │   └── log.py           # 日志配置
│   └── clients/             # 外部服务客户端
│       └── mysql_client_manager.py
└── conf/                    # 配置文件
    └── app_config.yaml
```

**分层职责**：

| 层 | 职责 | 示例 |
|----|------|------|
| `routers/` | 定义 API 接口（URL、方法、参数） | `@router.post("/api/query")` |
| `schemas/` | 定义请求/响应数据结构 | `class QuerySchema(BaseModel)` |
| `services/` | 核心业务逻辑 | `class QueryService` |
| `dependencies.py` | 依赖注入（创建/管理服务实例） | `get_query_service()` |
| `core/` | 基础设施（日志、生命周期等） | `lifespan`, `logger` |

---

## 6. 常用响应类型

| 响应类 | 用途 | 示例 |
|--------|------|------|
| `JSONResponse` | 返回 JSON 数据 | `return {"msg": "ok"}` |
| `StreamingResponse` | 流式返回数据 | SSE 推送 |
| `FileResponse` | 返回文件下载 | 导出 Excel |
| `HTMLResponse` | 返回 HTML 页面 | 渲染模板 |
| `RedirectResponse` | 重定向 | 登录后跳转 |
| `PlainTextResponse` | 返回纯文本 | 返回日志 |

---

## 7. 总结

| 概念 | 一句话解释 |
|------|-----------|
| FastAPI | 现代、高性能的 Python Web 框架 |
| Pydantic | 数据校验与序列化（自动生成 JSON Schema） |
| `APIRouter` | 模块化路由拆分 |
| `StreamingResponse` | 流式响应，边生成边返回 |
| SSE | 服务器向客户端单向推送事件 |
| Lifespan | 应用启动/关闭时的生命周期钩子 |
| Middleware | 请求/响应的全局拦截处理 |
| Depends | 依赖注入，复用逻辑和解耦代码 |

**在本项目中的角色**：FastAPI 作为整个 NL2SQL 智能体的对外接口层，通过 SSE 流式响应用户查询，实时推送工作流执行进度，是连接前端和后端 AI 智能体的桥梁。\