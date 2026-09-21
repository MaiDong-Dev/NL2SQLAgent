# Python 面向对象编程（OOP）详解

## 1. 什么是面向对象编程？

面向对象编程（Object-Oriented Programming，简称 OOP）是一种**以"对象"为中心的编程范式**。它将现实世界中的事物抽象为程序中的"对象"，每个对象包含**数据（属性）**和**行为（方法）**。

### 1.1 面向过程 vs 面向对象

| 维度 | 面向过程 | 面向对象 |
|------|---------|---------|
| 核心思想 | 事情该怎么做（步骤） | 谁来做（对象） |
| 基本单元 | 函数 | 类/对象 |
| 数据与行为 | 分离 | 封装在一起 |
| 复用方式 | 复制代码 / 函数调用 | 继承 / 组合 |
| 典型场景 | 简单脚本、一次性任务 | 大型项目、团队协作 |

**举例理解**：造一辆汽车

- 面向过程：先造发动机 → 再造轮子 → 再装底盘 → 再装外壳 → ...
- 面向对象：分别定义发动机类、轮子类、底盘类，组装成汽车对象

---

## 2. 核心概念

### 2.1 类（Class）与 对象（Instance）

**类**是对象的"蓝图/模板"，**对象**是类的"具体实例"。

```python
# 类：狗的蓝图
class Dog:
    # 类属性（所有实例共享）
    species = "犬科"

    # 初始化方法（构造器）
    def __init__(self, name: str, age: int):
        # 实例属性（每个实例独有）
        self.name = name
        self.age = age

    # 实例方法
    def bark(self):
        return f"{self.name} 说：汪汪！"

    def info(self):
        return f"{self.name}，{self.age}岁，属于{self.species}"

# 创建对象（实例化）
dog1 = Dog("旺财", 3)
dog2 = Dog("小白", 1)

print(dog1.bark())   # 旺财 说：汪汪！
print(dog2.info())   # 小白，1岁，属于犬科
```

### 2.2 三大特性

#### 2.2.1 封装（Encapsulation）

将数据（属性）和操作数据的方法捆绑在一起，对外隐藏内部实现细节。

```python
class BankAccount:
    def __init__(self, owner: str, balance: float = 0):
        self.owner = owner
        self.__balance = balance  # 私有属性（双下划线开头）

    def deposit(self, amount: float):
        """存款（对外暴露的安全接口）"""
        if amount <= 0:
            raise ValueError("存款金额必须大于0")
        self.__balance += amount
        return f"存款成功，余额：{self.__balance}"

    def withdraw(self, amount: float):
        """取款（对外暴露的安全接口）"""
        if amount <= 0:
            raise ValueError("取款金额必须大于0")
        if amount > self.__balance:
            raise ValueError("余额不足")
        self.__balance -= amount
        return f"取款成功，余额：{self.__balance}"

    def get_balance(self):
        """查看余额（只读）"""
        return self.__balance

# 使用
account = BankAccount("张三", 1000)
print(account.deposit(500))    # 存款成功，余额：1500
# account.__balance = 99999    # ❌ 无法直接修改私有属性！
print(account.get_balance())   # 1500
```

**Python 中的访问控制约定**：

| 命名方式 | 含义 | 示例 |
|---------|------|------|
| `name` | 公开属性 | `self.name` |
| `_name` | 受保护属性（约定，不强制） | `self._name` |
| `__name` | 私有属性（名称改写机制） | `self.__balance` |

#### 2.2.2 继承（Inheritance）

子类继承父类的属性和方法，并可以扩展或重写。

```python
# 父类（基类）
class Animal:
    def __init__(self, name: str):
        self.name = name

    def speak(self):
        return f"{self.name} 发出了声音"

# 子类（派生类）
class Dog(Animal):
    def speak(self):  # 重写父类方法
        return f"{self.name} 说：汪汪！"

    def fetch(self):  # 扩展新方法
        return f"{self.name} 去捡球了！"

class Cat(Animal):
    def speak(self):
        return f"{self.name} 说：喵喵！"

# 多态：同一个方法名，不同行为
animals = [Dog("旺财"), Cat("咪咪"), Animal("未知")]
for animal in animals:
    print(animal.speak())

# 输出：
# 旺财 说：汪汪！
# 咪咪 说：喵喵！
# 未知 发出了声音
```

#### 2.2.3 多态（Polymorphism）

同一个接口，不同对象表现不同行为。Python 天然支持"鸭子类型"（Duck Typing）：

> "如果它走起来像鸭子，叫起来像鸭子，那它就是鸭子。"

```python
# 不关心对象的类型，只关心对象是否有需要的方法
def make_sound(animal):
    print(animal.speak())

# 任何有 speak() 方法的对象都可以传入
make_sound(Dog("旺财"))   # 旺财 说：汪汪！
make_sound(Cat("咪咪"))   # 咪咪 说：喵喵！

# 甚至不是 Animal 子类的对象也可以
class Robot:
    def speak(self):
        return "哔哔哔..."

make_sound(Robot())       # 哔哔哔...
```

---

## 3. Python 特有的 OOP 特性

### 3.1 dataclass — 数据类

`dataclass` 是 Python 3.7+ 引入的装饰器，**自动生成** `__init__`、`__repr__`、`__eq__` 等方法，专为**数据载体**设计。

```python
from dataclasses import dataclass

# 传统写法（繁琐）
class User:
    def __init__(self, name: str, age: int, email: str):
        self.name = name
        self.age = age
        self.email = email

    def __repr__(self):
        return f"User(name={self.name}, age={self.age}, email={self.email})"

    def __eq__(self, other):
        if not isinstance(other, User):
            return False
        return self.name == other.name and self.age == other.age and self.email == other.email

# dataclass 写法（简洁）
@dataclass
class User:
    name: str
    age: int
    email: str

# 自动生成了 __init__, __repr__, __eq__
user1 = User("张三", 25, "zhangsan@example.com")
user2 = User("张三", 25, "zhangsan@example.com")
print(user1)           # User(name='张三', age=25, email='zhangsan@example.com')
print(user1 == user2)  # True
```

**dataclass 高级用法**：

```python
from dataclasses import dataclass, field
from typing import List

@dataclass
class Student:
    name: str
    age: int
    # 可变默认值需要用 field(default_factory=...)
    scores: List[float] = field(default_factory=list)
    # 不参与比较的字段
    id: int = field(compare=False, default=0)

    # 计算属性（post_init）
    def __post_init__(self):
        self.average = sum(self.scores) / len(self.scores) if self.scores else 0
```

**在本项目中的应用**：配置管理中的 `AppConfig` 类就是使用 `@dataclass` 定义的：

```python
@dataclass
class DBConfig:
    host: str
    port: int
    user: str
    password: str
    database: str

@dataclass
class AppConfig:
    logging: LoggingConfig
    db_meta: DBConfig
    db_dw: DBConfig
    qdrant: QdrantConfig
    embedding: EmbeddingConfig
    es: ESConfig
    llm: LLMConfig
```

### 3.2 TypedDict — 类型化字典

`TypedDict` 为字典提供**类型提示**，让 IDE 能自动补全字段名，同时保持字典的灵活性。

```python
from typing import TypedDict

class Person(TypedDict):
    name: str
    age: int
    city: str

# 使用方式与普通字典一样
person: Person = {
    "name": "张三",
    "age": 25,
    "city": "北京"
}

print(person["name"])  # IDE 可以自动补全 "name"！
```

**在本项目中的应用**：LangGraph 的 State 和 Context 定义：

```python
class DataAgentState(TypedDict):
    """智能体工作流状态"""
    user_query: str
    keywords: list[str]
    recalled_tables: list[dict]
    recalled_columns: list[dict]
    recalled_metrics: list[dict]
    generated_sql: str
    error: str | None
    query_result: list[dict]

class DataAgentContext(TypedDict):
    """智能体运行上下文（静态依赖）"""
    pass
```

### 3.3 `__init__` vs `__post_init__`

```python
from dataclasses import dataclass

@dataclass
class Rectangle:
    width: float
    height: float
    area: float = 0  # 由 post_init 计算

    def __post_init__(self):
        """在所有字段初始化完成后自动调用"""
        self.area = self.width * self.height
```

---

## 4. 设计模式速览

### 4.1 单例模式（Singleton）

确保一个类只有一个实例。本项目中的客户端管理器就是单例模式：

```python
# 全局唯一实例
dw_mysql_client_manager = MysqlClientManager(app_config.db_dw)
meta_mysql_client_manager = MysqlClientManager(app_config.db_meta)
qdrant_client_manager = QdrantClientManager(app_config.qdrant)
es_client_manager = ESClientManager(app_config.es)
embedding_client_manager = EmbeddedClientManager(app_config.embedding)
```

### 4.2 延迟初始化（Lazy Initialization）

不在构造时创建资源，而是显式调用 `init()` 方法：

```python
class MysqlClientManager:
    def __init__(self, db_config: DBConfig):
        self.db_config = db_config
        self.engine = None      # 延迟创建
        self.session_factory = None

    def init(self):             # 显式初始化
        self.engine = create_async_engine(self._get_url(), ...)
        self.session_factory = async_sessionmaker(bind=self.engine, ...)

    async def close(self):      # 显式清理
        await self.engine.dispose()
```

### 4.3 工厂模式（Factory）

`async_sessionmaker` 就是一个工厂函数：

```python
# session_factory 是一个工厂，每次调用创建新的 Session
async with session_factory() as session:
    result = await session.execute(...)
```

---

## 5. 特殊方法（魔术方法）

| 方法 | 触发时机 | 用途 |
|------|---------|------|
| `__init__` | 对象创建时 | 初始化实例属性 |
| `__str__` | `print(obj)` | 用户友好的字符串表示 |
| `__repr__` | `repr(obj)` | 开发者友好的字符串表示 |
| `__eq__` | `obj1 == obj2` | 相等比较 |
| `__len__` | `len(obj)` | 长度 |
| `__getitem__` | `obj[key]` | 索引访问 |
| `__enter__` / `__exit__` | `with obj:` | 上下文管理器 |
| `__aenter__` / `__aexit__` | `async with obj:` | 异步上下文管理器 |

```python
class Vector:
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y

    def __add__(self, other):
        """重载 + 运算符"""
        return Vector(self.x + other.x, self.y + other.y)

    def __str__(self):
        return f"Vector({self.x}, {self.y})"

    def __repr__(self):
        return f"Vector(x={self.x}, y={self.y})"

v1 = Vector(1, 2)
v2 = Vector(3, 4)
v3 = v1 + v2  # 自动调用 __add__
print(v3)     # Vector(4, 6)
```

---

## 6. 在本项目中的 OOP 实践

本项目大量运用了 OOP 思想：

| 位置 | 模式 | 说明 |
|------|------|------|
| `app/conf/app_config.py` | dataclass | 配置实体类 |
| `app/clients/mysql_client_manager.py` | 单例 + 延迟初始化 | MySQL 客户端管理 |
| `app/clients/qdrant_client_manager.py` | 单例 + 延迟初始化 | Qdrant 客户端管理 |
| `app/clients/es_client_manager.py` | 单例 + 延迟初始化 | ES 客户端管理 |
| `app/clients/embedding_client_manager.py` | 单例 + 延迟初始化 | Embedding 客户端管理 |
| `app/models/*.py` | ORM 实体类 | 数据库表映射 |
| `app/agent/state.py` | TypedDict | 智能体工作流状态 |
| `app/agent/context.py` | TypedDict | 智能体运行上下文 |

---

## 7. 总结

| 概念 | 一句话解释 |
|------|-----------|
| 类 | 对象的蓝图/模板 |
| 对象 | 类的具体实例 |
| 封装 | 隐藏内部实现，暴露安全接口 |
| 继承 | 子类复用父类代码 |
| 多态 | 同一接口，不同实现 |
| dataclass | 自动生成 `__init__` 等的数据类 |
| TypedDict | 带类型提示的字典 |
| `__init__` | 对象初始化方法 |
| `__post_init__` | dataclass 初始化后钩子 |

OOP 的核心价值在于**用人类理解世界的方式组织代码**，让大型项目更易于理解、维护和扩展。\