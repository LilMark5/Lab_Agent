# 第 08 章 · Pydantic 数据契约

## 开篇：为什么需要「契约」

没有 Pydantic 的接口长这样：

```python
@app.post("/reservation")
def create(data: dict):
    lab_id = data.get("lab_id")
    if lab_id is None:
        raise ...("缺少 lab_id")
    if not isinstance(lab_id, int):
        try:
            lab_id = int(lab_id)
        except ValueError:
            raise ...("lab_id 必须是整数")
    start = data.get("start_time")
    if start is None:
        raise ...
    # 还要校验时间格式、校验 end > start、校验 remark 长度...
    # 30 行过去了，业务代码还没开始
```

**问题**：

1. 校验代码和业务代码混在一起
2. 每个接口都要重复写一遍
3. 没有 Swagger 文档（前端不知道该传什么）
4. 容易漏校验（比如忘了检查 `remark` 长度）

**Pydantic 的解法**：把校验声明成**类型注解**，让它自动生成校验逻辑和文档。

```python
class ReservationCreateRequest(BaseModel):
    lab_id: int
    date: str
    start_time: str
    end_time: str
    remark: str | None = None
```

这 6 行等价于上面 30 行，而且：
- 类型错误自动返回 422
- 自动有 Swagger 文档
- 可在多处复用
- 可用于工具参数 schema（Agent 场景）

**这就是「数据契约」**：一次声明，处处生效。

---

## 一、Pydantic v2 的核心变化

> ⚠️ **版本提示**：项目用的是 **Pydantic v2**（实测 2.14.1）。v1 和 v2 的 API 差异很大，网上的教程很多还是 v1 写法。面试时说清楚版本。

| 特性 | v1 | v2 |
|---|---|---|
| 校验器 | `@validator` | `@field_validator` |
| ORM 模式 | `class Config: orm_mode = True` | `model_config = ConfigDict(from_attributes=True)` |
| 导出 | `.dict()` | `.model_dump()` |
| 解析 | `.parse_obj()` | `.model_validate()` |
| 核心实现 | Python | **Rust**（快 5-50 倍） |

**项目里的 v2 写法**（`schemas/reservation.py`）：

```python
class ReservationResponse(BaseModel):
    id: int
    user_id: int
    ...
    model_config = ConfigDict(from_attributes=True)   # ← v2 的 ORM 模式
```

> 💡 **面试话术**：「我用的是 Pydantic v2，ORM 模式是 `model_config = ConfigDict(from_attributes=True)`，不是 v1 的 `orm_mode`。v2 的核心校验逻辑用 Rust 重写了，性能提升明显。如果从 v1 迁移，要注意 `@validator` 改成 `@field_validator`、`.dict()` 改成 `.model_dump()`。」

---

## 二、基础用法：类型即校验

### 2.1 类型注解驱动

```python
from pydantic import BaseModel

class ReservationCreateRequest(BaseModel):
    lab_id: int                    # 必填，自动转 int（"1" → 1）
    equipment_id: int | None = None  # 可选，默认 None
    date: str                      # 必填字符串
    start_time: str
    end_time: str
    remark: str | None = None      # 可选
```

**自动做了什么**：

| 输入 | 结果 |
|---|---|
| `{"lab_id": "1", ...}` | ✅ `"1"` 转成 `1`（宽松转换） |
| `{"lab_id": "abc", ...}` | ❌ 422「lab_id: Input should be a valid integer」 |
| `{"lab_id": 1}`（缺 date） | ❌ 422「date: Field required」 |
| `{"lab_id": 1, "date": "2025-01-17", ...}` | ✅ |

> ⚠️ **注意**：Pydantic v2 默认是**宽松转换**——字符串 `"1"` 会转成整数 `1`。如果你要严格模式（拒绝类型不符），用 `StrictInt` 或设 `model_config = ConfigDict(strict=True)`。

### 2.2 Field 的常用约束

```python
from pydantic import BaseModel, Field

class LabCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="实验室名称")
    capacity: int = Field(..., gt=0, le=200, description="容纳人数")
    location: str = Field(default="", max_length=100)
    tags: list[str] = Field(default_factory=list)
```

| 参数 | 作用 |
|---|---|
| `...`（Ellipsis） | 必填 |
| `default=xxx` | 默认值 |
| `default_factory=list` | 可变默认值（**必须用 factory！**） |
| `min_length` / `max_length` | 字符串长度 |
| `gt` / `ge` / `lt` / `le` | 数值比较 |
| `pattern` | 正则 |
| `description` | **Swagger 文档 + 给模型看的说明** |
| `examples` | 示例值 |

> ⚠️ **坑**：`tags: list[str] = []` 是**错的**——Python 的可变默认参数陷阱，所有实例共享同一个 list。必须用 `Field(default_factory=list)`。

### 2.3 为什么 `description` 在 Agent 场景特别重要

回看第 6 章：工具参数用 Pydantic 声明时，`description` 会变成**发给模型的 schema 的一部分**。

```python
class CreateReservationInput(BaseModel):
    lab_id: int = Field(description="实验室 ID，必须是 search_labs 返回的 id 字段")
    start_time: str = Field(description="开始时间，格式 YYYY-MM-DD HH:MM:SS")

@tool(args_schema=CreateReservationInput)
def create_reservation(lab_id: int, start_time: str) -> str: ...
```

模型看到的 schema：

```json
{
  "lab_id": {"type": "integer", "description": "实验室 ID，必须是 search_labs 返回的 id 字段"},
  "start_time": {"type": "string", "description": "开始时间，格式 YYYY-MM-DD HH:MM:SS"}
}
```

**这一个 `description` 能大幅减少模型编造参数格式的概率。**

> 💡 **面试话术**：「Pydantic 的 Field description 在 Agent 场景有双重价值——它既生成 Swagger 文档给前端看，又生成工具 schema 给模型看。我在工具参数里会写清楚格式要求，比如『时间格式 YYYY-MM-DD HH:MM:SS』，这样模型编错格式的概率明显下降。一份声明，两处受益。」

---

## 三、自定义验证器

### 3.1 字段级验证

```python
from pydantic import BaseModel, field_validator

class ReservationCreateRequest(BaseModel):
    date: str
    start_time: str
    end_time: str

    @field_validator("date")
    @classmethod
    def check_date_format(cls, v: str) -> str:
        from datetime import datetime
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("日期格式必须是 YYYY-MM-DD")
        return v
```

**关键点**：

| 点 | 说明 |
|---|---|
| `@classmethod` | v2 **必须**加，否则报错 |
| `raise ValueError` | Pydantic 会捕获并转成 422 |
| 返回处理后的值 | 可以做清洗（比如 strip、lower） |

### 3.2 跨字段验证（模型级）

这是项目里真正需要的：`end_time` 必须晚于 `start_time`。

```python
from pydantic import BaseModel, model_validator

class ReservationCreateRequest(BaseModel):
    date: str
    start_time: str
    end_time: str

    @model_validator(mode="after")
    def check_time_order(self):
        if self.start_time >= self.end_time:
            raise ValueError("开始时间必须早于结束时间")
        return self
```

| 模式 | 时机 | 用途 |
|---|---|---|
| `mode="before"` | 在字段解析**之前** | 预处理原始数据（比如合并字段） |
| `mode="after"` | 在字段解析**之后** | 跨字段验证（最常用） |

**对比两种做法**：

```python
# 做法一：Pydantic 里验证（推荐）
@model_validator(mode="after")
def check_time_order(self):
    if self.start_time >= self.end_time:
        raise ValueError("开始时间必须早于结束时间")

# 做法二：Service 里验证
def create_reservation(db, user, data):
    if data.start_time >= data.end_time:
        raise BusinessException(message="开始时间必须早于结束时间")
```

**什么时候用哪个？**

| 场景 | 放哪 | 理由 |
|---|---|---|
| 纯格式校验（类型、长度、格式） | Pydantic | 自动 422，不占业务代码 |
| 不依赖 DB 的业务规则（end > start） | **Pydantic 更好** | 早失败，省一次 DB 查询 |
| 依赖 DB 的规则（实验室是否存在） | Service | Pydantic 拿不到 DB |

> ⚠️ **项目现状**：项目把「开始时间早于结束时间」这类校验放在了 Service 层（`reservation_service.py`）。这可以接受，但更优解是放 Pydantic —— 因为能在进入 Service 之前就拒绝，省掉一次数据库查询。这是个可以改进的点。

---

## 四、请求模型与响应模型分离（重要原则）

### 4.1 为什么不能共用一个模型

```python
# ❌ 错误做法：一个模型走天下
class Reservation(BaseModel):
    id: int
    user_id: int
    lab_id: int
    status: int
    created_at: datetime

@app.post("/reservation")
def create(data: Reservation):     # ← 用户可以传 id、status、created_at！
    ...
```

**这是严重的安全漏洞**：用户可以构造 JSON 传入 `status: 1`（已审核）或伪造 `user_id`。

### 4.2 正确的分离

```python
# 请求：只包含用户可以传的字段
class ReservationCreateRequest(BaseModel):
    lab_id: int
    equipment_id: int | None = None
    date: str
    start_time: str
    end_time: str
    remark: str | None = None

# 响应：包含前端需要展示的字段
class ReservationResponse(BaseModel):
    id: int
    user_id: int
    user_name: str | None = None      # ← 联查出来的
    lab_id: int
    lab_name: str | None = None       # ← 联查出来的
    status: int
    model_config = ConfigDict(from_attributes=True)
```

**注意 `ReservationCreateRequest` 里没有 `user_id`** —— 用户身份从 JWT 里拿（`current_user.id`），**绝不能信任客户端传的**。

> ⚠️ **这是越权漏洞的头号来源**。第 32 章会讲这个项目里修过的类似问题。

### 4.3 `from_attributes=True`：ORM 对象转响应模型

```python
class ReservationResponse(BaseModel):
    id: int
    user_id: int
    ...
    model_config = ConfigDict(from_attributes=True)

# 用法：直接传 ORM 对象
reservation = db.query(Reservation).first()
return ReservationResponse.model_validate(reservation)   # ← ORM 对象 → Pydantic
```

**没有 `from_attributes=True` 会怎样？**

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for ReservationResponse
  Input should be a valid dictionary or instance of ReservationResponse
```

因为 Pydantic 默认只接受 dict，不接受任意对象。`from_attributes=True` 告诉它「从属性读取」。

### 4.4 响应模型的字段过滤

```python
@router.get("", response_model=ApiResponse[list[ReservationResponse]])
def list_mine(...): ...
```

`response_model` 的作用：

1. **过滤字段**：即使你返回了完整 ORM 对象，也只会输出 `ReservationResponse` 里声明的字段
2. **Swagger 文档**：前端能看到响应结构
3. **序列化**：自动处理 datetime → ISO 字符串

> ⚠️ **坑**：如果 ORM 对象有懒加载字段（比如 `reservation.user`），在 `response_model` 序列化时可能触发 `DetachedInstanceError`（Session 已关闭）。解法是在 service 里显式加载（`joinedload`）或者提前转成 dict。

---

## 五、嵌套模型与复用

### 5.1 嵌套

```python
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]      # ← 嵌套
    thread_id: str | None = None
    include_uploaded: bool = True
```

请求体：

```json
{
  "messages": [
    {"role": "user", "content": "有哪些实验室"}
  ],
  "thread_id": "t-001",
  "include_uploaded": true
}
```

### 5.2 继承复用

```python
class ReservationBase(BaseModel):
    lab_id: int
    date: str
    start_time: str
    end_time: str

class ReservationCreateRequest(ReservationBase):
    """创建请求：继承基础字段，加 remark。"""
    remark: str | None = None

class ReservationUpdateRequest(ReservationBase):
    """更新请求：所有字段可选。"""
    lab_id: int | None = None
    date: str | None = None
    start_time: str | None = None
    end_time: str | None = None
```

**更新模型为什么要全部改成可选？** 因为 PATCH 语义：只传要改的字段。

**更优雅的写法**：

```python
class ReservationUpdateRequest(BaseModel):
    """全部字段可选。"""
    lab_id: int | None = None
    date: str | None = None
    ...
```

然后 service 里：

```python
def update_reservation(db, rid, data: ReservationUpdateRequest):
    reservation = db.query(Reservation).get(rid)
    # 只更新传了的字段
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(reservation, field, value)
```

**`exclude_unset=True` 是关键**：只导出用户**显式传了**的字段，没传的不导出（避免把 None 覆盖上去）。

---

## 六、Pydantic 在 Agent 场景的三个特殊用法

### 用法 1：工具参数 Schema（前面讲过）

```python
from langchain_core.tools import tool
from pydantic import BaseModel, Field

class SearchLabsInput(BaseModel):
    keyword: str = Field(default="", description="实验室名称关键词，留空查全部")

@tool(args_schema=SearchLabsInput)
def search_labs(keyword: str = "") -> str:
    """..."""
```

### 用法 2：结构化输出（Structured Output）

让模型输出符合某个 schema 的 JSON：

```python
class LabQueryIntent(BaseModel):
    """解析用户意图。"""
    intent: str = Field(description="意图：search / reserve / cancel / question")
    lab_name: str | None = Field(default=None, description="提到的实验室名称")
    date: str | None = Field(default=None, description="提到的日期")
    confidence: float = Field(description="置信度 0-1")

structured_llm = llm.with_structured_output(LabQueryIntent)
result = await structured_llm.ainvoke("明天A301有空吗")
# result 是 LabQueryIntent 实例
```

**这在 Agent 场景非常有用**：把模型的非结构化输出变成可编程的对象。

> ⚠️ **注意**：`with_structured_output` 依赖模型的 function calling 能力，不是所有模型都支持好。 DeepSeek、GPT-4 系列支持较好。

### 用法 3：配置管理（第 7 章讲过）

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    LLM_API_KEY: str = ""
    MAX_CONTEXT_TOKENS: int = 4000
    class Config:
        env_file = ".env"
```

---

## 七、最小可运行骨架

```python
"""
pydantic_demo.py —— Pydantic v2 核心用法
运行：pip install "pydantic>=2" && python pydantic_demo.py
演示：类型校验、Field 约束、自定义验证器、请求响应分离、ORM 模式
"""
from datetime import datetime
from typing import ClassVar

from pydantic import (
    BaseModel, ConfigDict, Field,
    ValidationError, field_validator, model_validator,
)

# ══════════════════════════════════════════════════════════
# 1. 基础：类型即校验
# ══════════════════════════════════════════════════════════

class SimpleRequest(BaseModel):
    lab_id: int
    date: str
    remark: str | None = None

def demo_basic():
    print("【1. 基础校验】")
    cases = [
        {"lab_id": 1, "date": "2025-01-17"},
        {"lab_id": "1", "date": "2025-01-17"},        # 字符串会被转换
        {"lab_id": "abc", "date": "2025-01-17"},      # 转换失败
        {"lab_id": 1},                                 # 缺必填字段
    ]
    for c in cases:
        try:
            r = SimpleRequest(**c)
            print(f"  ✅ {c} → lab_id={r.lab_id}({type(r.lab_id).__name__})")
        except ValidationError as e:
            errs = [f"{err['loc'][-1]}: {err['msg']}" for err in e.errors()]
            print(f"  ❌ {c} → {'; '.join(errs)}")
    print()

# ══════════════════════════════════════════════════════════
# 2. Field 约束
# ══════════════════════════════════════════════════════════

class LabCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, description="实验室名称")
    capacity: int = Field(..., gt=0, le=200, description="容纳人数")
    tags: list[str] = Field(default_factory=list, description="标签")

def demo_field():
    print("【2. Field 约束】")
    cases = [
        {"name": "A301", "capacity": 20},
        {"name": "", "capacity": 20},           # 名称太短
        {"name": "A301", "capacity": 0},        # 容量必须 > 0
        {"name": "A301", "capacity": 500},      # 容量超过上限
        {"name": "A301", "capacity": 20, "tags": ["生物", "显微"]},
    ]
    for c in cases:
        try:
            r = LabCreate(**c)
            print(f"  ✅ {c} → {r.name} 容量{r.capacity} 标签{r.tags}")
        except ValidationError as e:
            errs = [f"{err['loc'][-1]}: {err['msg']}" for err in e.errors()]
            print(f"  ❌ {c} → {'; '.join(errs)}")

    # ⚠️ 可变默认值陷阱
    a = LabCreate(name="A", capacity=10)
    b = LabCreate(name="B", capacity=10)
    a.tags.append("测试")
    print(f"  ⚠️ 可变默认值检查：a.tags={a.tags}, b.tags={b.tags}")
    print(f"     {'❌ 共享了！' if b.tags else '✅ 独立（用了 default_factory）'}\n")

# ══════════════════════════════════════════════════════════
# 3. 自定义验证器
# ══════════════════════════════════════════════════════════

class ReservationCreate(BaseModel):
    date: str
    start_time: str
    end_time: str

    @field_validator("date")
    @classmethod
    def check_date(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("日期格式必须是 YYYY-MM-DD")
        return v

    @model_validator(mode="after")
    def check_time_order(self):
        if self.start_time >= self.end_time:
            raise ValueError("开始时间必须早于结束时间")
        return self

def demo_validator():
    print("【3. 自定义验证器】")
    cases = [
        {"date": "2025-01-17", "start_time": "14:00", "end_time": "17:00"},
        {"date": "2025/01/17", "start_time": "14:00", "end_time": "17:00"},  # 格式错
        {"date": "2025-01-17", "start_time": "17:00", "end_time": "14:00"},  # 顺序错
    ]
    for c in cases:
        try:
            r = ReservationCreate(**c)
            print(f"  ✅ {c} → {r.date} {r.start_time}-{r.end_time}")
        except ValidationError as e:
            errs = [f"{err['loc'][-1] or '模型'}: {err['msg']}" for err in e.errors()]
            print(f"  ❌ {c} → {'; '.join(errs)}")
    print()

# ══════════════════════════════════════════════════════════
# 4. 请求响应分离（安全关键）
# ══════════════════════════════════════════════════════════

class ReservationCreateRequest(BaseModel):
    """请求：只有用户能传的字段。注意没有 user_id 和 status！"""
    lab_id: int
    date: str

class ReservationResponse(BaseModel):
    """响应：包含前端要展示的字段。"""
    id: int
    user_id: int
    lab_id: int
    status: int
    model_config = ConfigDict(from_attributes=True)

def demo_separation():
    print("【4. 请求响应分离】")
    # 模拟恶意请求：试图伪造 user_id 和 status
    malicious = {"lab_id": 1, "date": "2025-01-17", "user_id": 999, "status": 1}
    r = ReservationCreateRequest(**malicious)
    print(f"  恶意请求: {malicious}")
    print(f"  解析结果: {r.model_dump()}")
    print(f"  ✅ user_id 和 status 被丢弃了（未在模型中声明）")
    print(f"  ✅ 真实 user_id 从 JWT 里取，绝不信客户端\n")

# ══════════════════════════════════════════════════════════
# 5. ORM 模式（from_attributes）
# ══════════════════════════════════════════════════════════

class FakeReservation:
    """模拟 SQLAlchemy ORM 对象。"""
    def __init__(self):
        self.id = 1
        self.user_id = 42
        self.lab_id = 1
        self.status = 0
        self._internal = "不该暴露的内部字段"

def demo_orm_mode():
    print("【5. ORM 模式】")
    orm_obj = FakeReservation()

    # 没有 from_attributes 的模型
    class NoOrm(BaseModel):
        id: int
        user_id: int
    try:
        NoOrm.model_validate(orm_obj)
    except ValidationError as e:
        print(f"  ❌ 没有 from_attributes: {e.errors()[0]['msg'][:50]}...")

    # 有 from_attributes
    r = ReservationResponse.model_validate(orm_obj)
    print(f"  ✅ 有 from_attributes: {r.model_dump()}")
    print(f"  ✅ 只输出声明的字段，_internal 不会被带出去\n")

# ══════════════════════════════════════════════════════════
# 6. Agent 场景：工具参数 schema
# ══════════════════════════════════════════════════════════

def demo_tool_schema():
    print("【6. 工具参数 schema（给模型看）】")

    class CreateReservationInput(BaseModel):
        lab_id: int = Field(description="实验室 ID，必须是 search_labs 返回的 id")
        start_time: str = Field(description="开始时间，格式 YYYY-MM-DD HH:MM:SS")
        end_time: str = Field(description="结束时间，格式 YYYY-MM-DD HH:MM:SS")

    schema = CreateReservationInput.model_json_schema()
    print("  生成的 JSON Schema：")
    for name, prop in schema["properties"].items():
        print(f"    {name}:")
        print(f"      type: {prop.get('type')}")
        print(f"      description: {prop.get('description')}")
    print(f"    required: {schema.get('required')}")
    print("\n  ✅ 这份 schema 会发给模型，description 帮它填对参数\n")

# ══════════════════════════════════════════════════════════
# 7. exclude_unset：部分更新
# ══════════════════════════════════════════════════════════

class UpdateRequest(BaseModel):
    lab_id: int | None = None
    date: str | None = None
    remark: str | None = None

def demo_exclude_unset():
    print("【7. exclude_unset：PATCH 语义】")
    req = UpdateRequest(date="2025-01-18")   # 只传了 date

    print(f"  model_dump()              → {req.model_dump()}")
    print(f"  model_dump(exclude_unset=True) → {req.model_dump(exclude_unset=True)}")
    print("  ✅ 只更新传了的字段，不会把 None 覆盖上去\n")

# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Pydantic v2 核心用法演示")
    print("=" * 60 + "\n")
    demo_basic()
    demo_field()
    demo_validator()
    demo_separation()
    demo_orm_mode()
    demo_tool_schema()
    demo_exclude_unset()
```

---

## 八、项目代码定位

### 8.1 `schemas/reservation.py`

```python
class ReservationCreateRequest(BaseModel):
    lab_id: int
    equipment_id: int | None = None
    date: str
    start_time: str
    end_time: str
    remark: str | None = None
    # ✅ 没有 user_id（从 JWT 取）、没有 status（服务端定）
    # ✅ 没有 id（数据库自增）

class ReservationResponse(BaseModel):
    id: int
    user_id: int
    user_name: str | None = None       # 联查
    lab_id: int
    lab_name: str | None = None        # 联查
    equipment_id: int | None = None
    equipment_name: str | None = None
    type: str | None = None
    date: str
    start_time: str
    end_time: str
    remark: str | None = None
    status: int

    model_config = ConfigDict(from_attributes=True)   # ← v2 ORM 模式

class AuditReservationRequest(BaseModel):
    status: int  # 1 通过，2 拒绝
```

**注意**：`ReservationResponse` 里有 `user_name`、`lab_name` 这些**联查字段**。

这说明 service 层做了 join 或者二次查询来填充这些字段。为什么要放在响应模型里？因为前端列表页要显示「谁预约了哪个实验室」，如果只有 id，前端还要再发请求查名字。

### 8.2 `schemas/ai.py`

```python
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]
    thread_id: str | None = None
    include_uploaded: bool = True

class ApprovalResumeRequest(BaseModel):
    thread_id: str
    approved: bool
    include_uploaded: bool = True
```

**关键设计：`thread_id` 在请求体里，不在路径里。**

为什么不用 `/api/ai/chat/{thread_id}`？

因为 `thread_id` 是**可选的**（`None` 表示新建会话）。放在路径里就没法省略。

**而且 `thread_id` 是客户端生成的**（前端用 uuid），服务端不校验它属于谁——这其实是一个**潜在的越权风险**（第 32 章讨论）。

### 8.3 `config.py`

```python
class Settings(BaseSettings):
    ...
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
```

---

## 本章速记卡

1. **Pydantic v2**（不是 v1）。ORM 模式用 `ConfigDict(from_attributes=True)`，导出用 `.model_dump()`。
2. **类型注解即校验**。一次声明，自动 422 + Swagger 文档 + 复用。
3. **`Field(description=...)` 在 Agent 场景双重价值**：给前端看文档 + 给模型看参数说明。
4. **可变默认值必须用 `default_factory`**，不能用 `= []`。
5. **`@field_validator` 要加 `@classmethod`**（v2 强制）。
6. **`@model_validator(mode="after")`** 做跨字段验证。
7. **请求模型和响应模型必须分离** —— 否则用户能伪造 `status`、`user_id`。
8. **`from_attributes=True`** 才能从 ORM 对象转 Pydantic。
9. **`exclude_unset=True`** 实现 PATCH 语义（只更新传了的字段）。
10. **`response_model`** 三重作用：过滤字段、生成文档、序列化 datetime。

---

## 面试问答：数据校验

### Q1：「Pydantic 给你带来了什么？」

**满分答法**：

> 四个价值。
>
> **一是校验自动化**。类型、必填、长度、格式这些校验，用类型注解声明一次就行，不用在每个接口里手写。类型错误自动返回 422，错误信息还会指明是哪个字段。
>
> **二是文档自动生成**。Swagger 里能看到完整的请求/响应结构，前端不用问后端「该传什么」。
>
> **三是安全**。这个最重要——请求模型和响应模型分离，请求模型里只声明用户可以传的字段。比如创建预约的请求模型里没有 `user_id` 和 `status`，用户就算构造 JSON 伪造也会被丢弃。身份从 JWT 里取，状态由服务端定。
>
> **四是在 Agent 场景的特殊价值**：工具参数用 Pydantic 声明时，Field 的 description 会生成发给模型的 JSON Schema。我在里面写清格式要求，比如「时间格式 YYYY-MM-DD HH:MM:SS」，模型编错参数的概率明显下降。一份声明，既给前端看又给模型看。

---

### Q2：「请求模型和响应模型为什么要分开？」

**满分答法**（这题考安全意识）：

> 最核心的原因是安全。
>
> 如果共用一个模型，用户构造请求时可以传入他不应当控制的字段。比如创建预约时传 `status: 1`（已审核通过），或者传 `user_id: 999` 伪造成别人。这就是越权漏洞。
>
> 分开之后，请求模型只包含用户真正能决定的字段——实验室 ID、日期、时间段、备注。而 `user_id` 从 JWT 里取，`status` 由服务端设为 `pending`，`id` 由数据库自增。用户传了也会被 Pydantic 忽略（未声明的字段默认丢弃）。
>
> 另一个原因是**字段需求不同**。响应里经常需要联查字段，比如 `user_name`、`lab_name`——前端列表页要显示「谁预约了哪个实验室」，如果只给 id，前端还得再发请求查名字。所以响应模型比请求模型字段多，这是正常的。

---

### Q3：「跨字段验证怎么做？放在 Pydantic 还是 Service？」

**满分答法**：

> Pydantic 用 `@model_validator(mode="after")`，在所有字段解析完之后做跨字段检查。比如「结束时间必须晚于开始时间」。
>
> 放哪的判断标准：
>
> **纯格式校验**（类型、长度、正则）一定放 Pydantic，自动 422，不占业务代码。
>
> **不依赖数据库的业务规则**（比如 end > start）放 Pydantic 更好——能在进入 Service 之前就拒绝，省掉一次数据库查询和事务开销。
>
> **依赖数据库的规则**（实验室是否存在、时段是否冲突）必须放 Service，因为 Pydantic 拿不到数据库会话。
>
> 说实话我项目里把「时间先后顺序」这类校验放在了 Service 层，这可以接受但不是最优，更优解是放 Pydantic 提前失败。这是个可以改进的点。

---

### Q4：「Pydantic v1 和 v2 有什么区别？」

**满分答法**：

> 几个关键差异（我用的是 v2）：
>
> ORM 模式：v1 是 `class Config: orm_mode = True`，v2 是 `model_config = ConfigDict(from_attributes=True)`。
>
> 导出方法：v1 是 `.dict()`，v2 是 `.model_dump()`。v2 里 `.dict()` 还能用但已废弃，会警告。
>
> 验证器：v1 是 `@validator`，v2 是 `@field_validator`，而且 v2 强制要加 `@classmethod`。
>
> 跨字段验证：v1 是 `@root_validator`，v2 是 `@model_validator(mode="after")`。
>
> 最大的变化是**性能**：v2 的核心校验逻辑用 Rust 重写了，官方数据快 5 到 50 倍。对于高频接口这个差异很明显。

---

### Q5：「Pydantic 校验失败怎么返回给前端？」

**满分答法**：

> FastAPI 默认抛 `RequestValidationError`，返回 422，body 里是一个 `detail` 数组，每项有 `loc`（字段路径）、`msg`（错误信息）、`type`（错误类型）。
>
> 这个结构前端处理起来麻烦，所以我**注册了自定义异常处理器做格式化**：提取每项的最后一个 loc 元素作为字段名，拼成「字段名: 错误信息」的字符串，用分号分隔，然后包进统一的 `{code, message, data}` 结构。
>
> 这样前端拦截器里一个 `ElMessage.error(res.message)` 就能显示「lab_id: field required；start_time: invalid format」。
>
> 需要注意 422 的语义是「请求格式正确但内容校验失败」，和 400（请求本身有问题）略有区别，但对外统一用 422 就行，前端按「参数错误」处理。

---

### Q6：「有没有 Pydantic 解决不了的场景？」

**满分答法**（这题考边界认知）：

> 有，主要是两类。
>
> **一是依赖外部状态的校验**。Pydantic 是纯函数式的，它拿不到数据库会话、拿不到当前用户。所以「实验室是否存在」「时段是否冲突」这类必须在 Service 层做。
>
> **二是动态 schema**。如果你的字段结构是根据运行时数据决定的（比如用户自定义的元数据字段），静态模型就不好表达。可以用 `model_config = ConfigDict(extra="allow")` 允许额外字段，或者用 `Json[dict]` 类型存一个自由的字典。
>
> 另外 Pydantic 不适合做「业务逻辑」——它是数据校验层，不是业务层。我见过有人把复杂的业务规则塞进 validator 里，导致模型变得很难维护。我的原则很简单：validator 只做「这个数据本身是否合法」，业务规则留到 Service。

---

## 常见坑

### 坑 1：可变默认值用 `= []`

所有实例共享同一个 list。用 `Field(default_factory=list)`。

### 坑 2：请求响应共用一个模型

越权漏洞。用户能伪造 `status`、`user_id`。

### 坑 3：`@field_validator` 忘了加 `@classmethod`

v2 会报错。

### 坑 4：忘了 `from_attributes=True`

ORM 对象转 Pydantic 时报错「Input should be a valid dictionary」。

### 坑 5：懒加载字段在序列化时报错

Session 已关闭时访问 `obj.relationship` 会抛 `DetachedInstanceError`。要么用 `joinedload` 预加载，要么在 service 里先转成 dict。

### 坑 6：`model_dump()` 把 None 也导出

做 PATCH 更新时会把没传的字段覆盖成 None。用 `exclude_unset=True`。

### 坑 7：以为未声明的字段会报错

默认是**忽略**（`extra="ignore"`），不是报错。要报错得设 `extra="forbid"`。

### 坑 8：datetime 序列化格式不一致

Pydantic 默认输出 ISO 格式，前端要注意时区。

---

## 动手练习

### 练习 1（必做）

跑通第七节的 `pydantic_demo.py`，重点观察：

1. 字符串 `"1"` 被自动转成整数
2. 可变默认值陷阱的验证结果
3. 恶意请求里的 `user_id` 和 `status` 是否被丢弃
4. 工具 schema 的生成结果

### 练习 2

给 `ReservationCreateRequest` 加上验证器：

```python
@field_validator("date")
@classmethod
def check_date(cls, v): ...   # 必须是 YYYY-MM-DD

@model_validator(mode="after")
def check_time_order(self): ...  # start < end
```

然后用 curl 测试非法输入，看返回的 422 信息。

### 练习 3

打开项目里的 schemas，检查：

1. 所有请求模型里有没有 `user_id`、`status`、`id` 这类不该让用户传的字段？
2. 响应模型有没有 `from_attributes=True`？
3. 有没有可以合并复用的重复定义？

### 练习 4（进阶）

用 `with_structured_output` 让模型输出结构化意图：

```python
class Intent(BaseModel):
    intent: str = Field(description="search/reserve/question")
    lab_name: str | None = None
    date: str | None = None

structured = llm.with_structured_output(Intent)
# 测试几个用户输入，看解析准确率
```

---

## 下一章

**第 09 章 · 依赖注入**

Pydantic 解决了「数据形状」，依赖注入解决「组件怎么组装」。

`get_db`、`get_current_user`、`admin_only` 这些 `Depends(...)` 背后，是一套完整的解析机制。理解它，你才能写出可测试、可复用、可组合的组件。

下一章讲：依赖树的解析过程、依赖缓存的坑、怎么用依赖注入做测试替换（这是很多人不知道的技巧）、以及「为什么依赖注入比全局变量好」。
