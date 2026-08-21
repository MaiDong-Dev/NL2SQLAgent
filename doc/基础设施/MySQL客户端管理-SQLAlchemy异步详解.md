# MySQL 客户端管理 — SQLAlchemy 异步详解

## 1. SQLAlchemy 概述

[SQLAlchemy](https://www.sqlalchemy.org/) 是 **Python 生态中最主流的 ORM（Object Relational Mapper，对象关系映射）框架**，也是 Python 官方推荐的数据库操作工具之一。

它的核心定位是 **"数据库交互的抽象层"**——让开发者用 Python 对象的方式操作数据库，无需直接编写原生 SQL，同时保留对原生 SQL 的灵活支持。

### 1.1 ORM 是什么？

举个例子，假设数据库有一张 `user` 表：

```sql
CREATE TABLE user (
    id INT PRIMARY KEY,
    name VARCHAR(50),
    age INT
);
```

**不用 ORM（原生 SQL）**：

```python
# 写 SQL 字符串，容易出错，没有类型提示
result = await session.execute(text("SELECT * FROM user WHERE id = 1"))
row = result.fetchone()
print(row[1])  # 这是什么字段？需要看数据库定义才知道
```

**用 ORM（SQLAlchemy）**：

```python
# 用 Python 对象操作，有类型提示，IDE 自动补全
user = await session.get(User, 1)
print(user.name)  # IDE 可以自动补全 .name！
```

### 1.2 SQLAlchemy 核心架构

```
┌─────────────────────────────────────┐
│          SQLAlchemy ORM             │
│  (实体类、Session、关系映射)          │
├─────────────────────────────────────┤
│          SQLAlchemy Core            │
│  (Engine、Connection、SQL表达式)      │
├─────────────────────────────────────┤
│         DBAPI 驱动层                 │
│  (asyncmy / pymysql / psycopg2...)  │
├─────────────────────────────────────┤
│          MySQL / PostgreSQL...       │
└─────────────────────────────────────┘
```

- **ORM 层**：最上层，开发者直接操作 Python 对象
- **Core 层**：中间层，负责 SQL 生成、连接池管理、事务管理
- **DBAPI 驱动层**：最底层，真正与数据库通信的驱动

---

## 2. 本项目中的 MySQL 客户端

### 2.1 为什么用异步？

本项目使用 **异步 MySQL 驱动（asyncmy）**，原因如下：

- 项目基于 **FastAPI**（异步 Web 框架）
- 智能体工作流涉及大量并发的数据库查询
- 异步 I/O 能大幅提升吞吐量，避免线程阻塞

### 2.2 驱动选择

| 驱动 | 类型 | 适用场景 |
|------|------|---------|
| `pymysql` | 同步 | 普通脚本、Flask 项目 |
| `asyncmy` | 异步 | FastAPI、高性能异步项目 ✅ |
| `aiomysql` | 异步 | 备选方案 |

本项目选择 `asyncmy`，因为它是目前 Python 异步 MySQL 驱动中性能最好的。

### 2.3 连接 URL 格式

```
mysql+asyncmy://用户名:密码@主机:端口/数据库名?charset=utf8mb4
```

示例：

```python
f"mysql+asyncmy://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"
```

实际拼接结果：

```
mysql+asyncmy://atguigu:Atguigu.123@localhost:3306/meta?charset=utf8mb4
```

---

## 3. 核心组件详解

### 3.1 AsyncEngine — 异步引擎

`AsyncEngine` 是 SQLAlchemy 异步操作的核心，负责管理数据库连接池。

```python
from sqlalchemy.ext.asyncio import create_async_engine

self.engine = create_async_engine(
    self._get_url(),       # 数据库连接地址
    pool_size=10,          # 连接池最大连接数
    pool_pre_ping=True     # 使用前检测连接是否存活
)
```

#### 参数详解

**`pool_size=10`**

连接池会预先创建（或按需创建）最多 10 个数据库连接并维护。当程序需要访问数据库时：

1. 从池中获取空闲连接
2. 执行 SQL 操作
3. 归还连接到池中

**为什么需要连接池？**

创建数据库连接是非常昂贵的操作（TCP 三次握手、MySQL 认证、SSL 协商等），通常需要 50ms~200ms。如果每次请求都新建连接，性能会极差。连接池通过复用连接，将连接开销降到几乎为零。

**`pool_pre_ping=True`**

这是连接池的"心跳检测"开关。开启后，每次从连接池获取连接时，会先执行一个轻量级的 `SELECT 1` 操作，验证连接是否有效。

**核心作用**：解决"失效连接"问题。

MySQL 默认 `wait_timeout` 为 8 小时。如果连接长时间空闲，MySQL 服务端会主动断开连接，但客户端连接池还拿着旧连接。当程序用这个失效连接执行 SQL 时，就会报错：

```
MySQL server has gone away
```

开启 `pool_pre_ping=True` 后：
- 每次取连接前先检测可用性
- 如果连接失效，自动丢弃并创建新连接
- 保证程序拿到的一直是可用连接

---

### 3.2 AsyncSession — 异步会话

`AsyncSession` 是 SQLAlchemy 中操作数据库的"工作单元"，所有查询、增删改操作都在 Session 中进行。

```python
async with AsyncSession(engine, autoflush=True, expire_on_commit=False) as session:
    result = await session.execute(text("SELECT * FROM fact_order LIMIT 10"))
    rows = result.mappings().fetchall()
```

#### 参数详解

**`autoflush`（默认 True）**

控制执行查询时，是否自动将当前会话中未提交的修改先同步到数据库（但不提交事务）。

**比喻理解**：

| 操作 | 类比 |
|------|------|
| 在 Session 中修改数据 | 在草稿纸上写内容 |
| `flush` | 把草稿纸内容誊抄到数据库的临时区域（未最终确认） |
| `commit` | 盖章确认，修改永久生效 |
| `autoflush=True` | 每次查询前，自动先把草稿纸内容誊抄好，保证查到的是最新数据 |

**`autobegin`（默认 True）**

控制 Session 是否自动为首次数据库操作开启事务，无需手动调用 `session.begin()`。

**`expire_on_commit`（默认 True）**

控制 `session.commit()` 后，ORM 对象是被标记为"过期"。

| 设置 | 提交后行为 | 适用场景 |
|------|-----------|---------|
| `expire_on_commit=True`（默认） | 提交后对象过期，再次访问属性时自动查询数据库获取最新值 | 同步场景，需要最新数据 |
| `expire_on_commit=False` | 提交后对象不过期，直接使用内存中的值 | **异步场景（必须）** |

> ⚠️ **重要**：在异步场景下必须设置为 `expire_on_commit=False`。
>
> 原因：如果设置为 `True`，提交后对象过期，再次访问属性时会触发一次 I/O 请求重新查询。但在异步函数中，这个 I/O 操作需要 `await` 关键字，而访问对象属性（如 `user.name`）并不是一个可等待的协程，无法添加 `await`，因此会导致错误。

**理解案例**：

```python
# 场景一：expire_on_commit=False
session.expire_on_commit = False
user = await session.get(User, 1)
print(user.name)  # 张三

user.name = "李四"
await session.commit()

print(user.name)  # 还是内存里的旧数据 "李四"（实际数据库中已经是 "李四" 了）
# 如果其他进程修改了数据库，这里不会感知到

# 场景二：expire_on_commit=True（同步场景）
session.expire_on_commit = True
user = await session.get(User, 1)
print(user.name)  # 张三

user.name = "李四"
await session.commit()

print(user.name)  # 自动重新去数据库查询，输出 "李四"
```

---

### 3.3 async_sessionmaker — 会话工厂

`async_sessionmaker` 是一个会话工厂函数，用于批量创建配置一致的 Session 实例。

```python
from sqlalchemy.ext.asyncio import async_sessionmaker

self.session_factory = async_sessionmaker(
    bind=self.engine,            # 绑定异步引擎
    autoflush=False,             # 关闭自动刷新
    expire_on_commit=False       # 提交后不自动过期
)
```

**使用方式**：

```python
# 方式一：with 语句（推荐，自动管理会话生命周期）
async with self.session_factory() as session:
    result = await session.execute(text("SELECT * FROM ..."))

# 方式二：手动创建（需要手动关闭）
session = self.session_factory()
try:
    result = await session.execute(text("SELECT * FROM ..."))
finally:
    await session.close()
```

**参数说明**：

| 参数 | 本项目设置 | 原因 |
|------|-----------|------|
| `autoflush=False` | 关闭 | 只有手动调用 `session.flush()` 或 `commit()` 时才同步，避免不必要的 I/O |
| `expire_on_commit=False` | 关闭 | 异步场景必须关闭，否则属性访问会触发隐式 I/O |

---

## 4. 完整客户端代码

本项目在 `data-agent/app/clients/mysql_client_manager.py` 中实现了 MySQL 客户端管理器：

```python
from typing import Union
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine, async_sessionmaker

class MysqlClientManager:
    def __init__(self, db_config: DBConfig):
        self.db_config = db_config
        self.engine: Union[AsyncEngine, None] = None
        self.session_factory = None

    def _get_url(self):
        return (
            f"mysql+asyncmy://{self.db_config.user}:{self.db_config.password}"
            f"@{self.db_config.host}:{self.db_config.port}/{self.db_config.database}"
            f"?charset=utf8mb4"
        )

    def init(self):
        self.engine = create_async_engine(
            self._get_url(),
            pool_size=10,
            pool_pre_ping=True
        )
        self.session_factory = async_sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False
        )

    async def close(self):
        await self.engine.dispose()

# 创建两个全局实例：一个连接 DW 数据仓库，一个连接 Meta 元数据库
dw_mysql_client_manager = MysqlClientManager(app_config.db_dw)
meta_mysql_client_manager = MysqlClientManager(app_config.db_meta)
```

**为什么有两个客户端管理器？**

- `dw_mysql_client_manager`：连接**数据仓库（DW）**，存储业务数据（订单表、用户表等）
- `meta_mysql_client_manager`：连接**元数据库（Meta）**，存储表结构、字段信息、指标定义等元数据

---

## 5. SQLAlchemy 实体类（ORM Model）

### 5.1 DeclarativeBase — 声明式基类

`DeclarativeBase` 是 SQLAlchemy 2.0 官方推荐的唯一基类，所有数据库模型都必须继承它。

```python
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass
```

**作用**：
- 统一管理所有表结构
- 统一连接、元数据管理
- 提供 ORM 映射能力
- 这是 SQLAlchemy 2.0 的标准写法

### 5.2 实体类示例

```python
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

class TableInfoMySQL(Base):
    __tablename__ = "table_info"

    id: Mapped[str] = mapped_column(
        String(64), primary_key=True, comment="表编号"
    )
    name: Mapped[str | None] = mapped_column(
        String(128), comment="表名称"
    )
    role: Mapped[str | None] = mapped_column(
        String(32), comment="表类型(fact/dim)"
    )
    description: Mapped[str | None] = mapped_column(
        Text, comment="表描述"
    )
```

**关键点**：

| 语法 | 说明 |
|------|------|
| `Mapped[str]` | 类型注解，表示该字段在 Python 中的类型 |
| `mapped_column(...)` | 列定义，配置数据库列的类型、约束、注释 |
| `__tablename__` | 指定对应的数据库表名 |
| `str \| None` | Python 3.10+ 的联合类型语法，表示可为空 |
| `JSON` 类型 | 用于存储 JSON 格式的示例数据和别名 |

---

## 6. 查询结果处理

```python
async with session_factory() as session:
    result = await session.execute(text("SELECT * FROM fact_order LIMIT 10"))

    # 方式一：fetchall() 返回元组列表 [(), (), ()]
    rows = result.fetchall()
    print(rows[0])       # (1, '张三', ...)
    print(rows[0][0])    # 1  （按索引访问，不直观）

    # 方式二：mappings().fetchall() 返回字典列表 [{}, {}, {}]
    rows = result.mappings().fetchall()
    print(rows[0])       # {'id': 1, 'name': '张三', ...}
    print(rows[0]['id']) # 1  （按键名访问，更直观）
```

**推荐使用 `mappings().fetchall()`**，因为字典结构更易于阅读和调试。

---

## 7. 总结

| 组件 | 作用 |
|------|------|
| `create_async_engine` | 创建异步数据库引擎，管理连接池 |
| `pool_size=10` | 连接池最大连接数 |
| `pool_pre_ping=True` | 使用前心跳检测，自动替换死连接 |
| `async_sessionmaker` | 会话工厂，批量创建 Session |
| `autoflush=False` | 手动控制刷新时机 |
| `expire_on_commit=False` | 异步场景必须关闭，避免隐式 I/O |
| `DeclarativeBase` | ORM 实体类基类 |
| `mapped_column` | 定义数据库列 |
| `mappings().fetchall()` | 以字典列表形式获取查询结果 |