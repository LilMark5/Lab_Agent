# 第 32 章 · JWT 与 RBAC：前后端双重鉴权

> **这一章要回答的核心问题**：JWT 凭什么防篡改？bcrypt 为什么"慢"反而好？后端校验了前端还要校验吗？那个"知识库接口普通用户也能调"的越权漏洞是怎么修的？

---

## 32.1 引子：一个真实的安全漏洞

本项目代码审查时发现的 **B1 缺陷**（`docs/23-代码审查报告.md`）：

```python
# 修复前：知识库接口用 get_current_user
@router.post("/documents")
async def upload_document(
    current_user: User = Depends(get_current_user),   # ❌ 任何登录用户
    ...
)
```

**问题**：知识库管理（上传、删除文档）是**管理员功能**，但接口只校验了"已登录"，没校验"是管理员"。

**后果**：任何一个普通学生用户，只要拿到自己的 token，就能：
- 上传任意文档到知识库（污染 RAG 的检索源！）
- 删除知识库文档

**这在 RAG 系统里尤其危险** —— 因为知识库内容会直接进入模型的上下文。恶意用户上传一份"实验室 24 小时开放"的假文档，Agent 就会给出错误答案。这是**数据投毒攻击**。

**修复**（B1）：

```python
@router.post("/documents")
async def upload_document(
    current_user: User = Depends(get_current_admin),   # ✅ 必须是管理员
    ...
)
```

同时前端也加了守卫（B2），这是本章的主题之一。

---

## 32.2 认证 vs 授权：两个不同的问题

先厘清概念，这两个词经常被混用：

| 概念 | 英文 | 回答的问题 | 本项目实现 |
|---|---|---|---|
| **认证** | Authentication / AuthN | **你是谁？** | JWT 登录 |
| **授权** | Authorization / AuthZ | **你能做什么？** | `role == "admin"` 判断 |

**一个常见的错误**：只做了认证，就以为安全了。

"已登录" ≠ "能操作这个资源"。上面的 B1 漏洞正是这个错误。

---

## 32.3 JWT：凭什么防篡改

### 32.3.1 结构

一个 JWT 长这样（三段，用 `.` 分隔）：

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoxLCJleHAiOjE3NjA2ODk2MDB9.Hx8k...
   ↑ 第1段：Header             ↑ 第2段：Payload              ↑ 第3段：Signature
```

三段都是 Base64 编码：

**Header**（算法和类型）：
```json
{"alg": "HS256", "typ": "JWT"}
```

**Payload**（实际数据）：
```json
{"user_id": 1, "exp": 1760689600}
```

**Signature**（签名）：
```
HMACSHA256(
  base64url(header) + "." + base64url(payload),
  secret_key              ← ★ 只有服务端知道
)
```

### 32.3.2 防篡改的原理

**关键：Payload 是 Base64 编码，不是加密。** 任何人都能解码看到内容：

```python
import base64
base64.b64decode("eyJ1c2VyX2lkIjoxLCJleHAiOjE3NjA2ODk2MDB9")
# → {"user_id": 1, "exp": 1760689600}
```

**那安全在哪？** 在**签名**。

假设我是 `user_id=1` 的普通用户，我想改成管理员。第一步是改 Payload。但本项目用的是**角色字段在数据库里**（`user.role`），Payload 里只有 `user_id`——所以我要把 `user_id` 改成管理员的 ID（比如 2）：

```
改前：{"user_id": 1, "exp": ...}
改后：{"user_id": 2, "exp": ...}
```

**但是**：签名是用 `secret_key` 对原始 Payload 算的。我改了 Payload，签名就对不上了。而我不知道 `secret_key`，**无法重新生成有效的签名**。

服务端验签时会发现不匹配 → 抛异常 → 401。

> **面试可以现场演示**：把 Payload 里的 `user_id` 改掉，用 `jwt.decode` 验签，会抛 `InvalidSignatureError`。这是 JWT 防篡改的最好证明。

### 32.3.3 JWT 的三个常见误解

**误解 1："JWT 是加密的，安全"**

❌ 错。Payload 是 Base64，**可解码**。所以**绝不能放敏感信息**（密码、身份证号、密钥）。

**误解 2："JWT 存在 localStorage 就安全"**

⚠️ 有 XSS 风险。localStorage 里的 token 能被 JS 读取，XSS 攻击就能偷走。

| 存储位置 | XSS 风险 | CSRF 风险 | 本项目 |
|---|---|---|---|
| localStorage | ❌ 高 | ✅ 低 | ✅ 用的这个 |
| Cookie (HttpOnly) | ✅ 低 | ❌ 高（需 CSRF token） | |

本项目用 localStorage（配合 DOMPurify 防 XSS，第 31 章）。

**误解 3："JWT 能主动失效"**

❌ 难。JWT 是无状态的，服务端不存 token。**签发后到过期前一直有效**——即使用户登出、被禁用。

**本项目的缓解**（`dependencies/auth.py:38-46`）：

```python
user = db.query(User).filter(User.id == user_id).first()
if not user:
    raise HTTPException(...detail="用户不存在")
if user.status != 1:
    raise HTTPException(...detail="用户被禁用")
```

**每次请求都查数据库验证用户状态** —— 这样"禁用用户"能立即生效。

**代价**：每次请求多一次 DB 查询（失去了 JWT"无状态"的部分优势）。

**权衡**：对于用户量不大的系统，这个代价完全可以接受，换来"能立即禁用用户"的能力。**这是一个务实的取舍**。

> **面试话术**："JWT 的一大问题是签发后无法主动失效。我们的处理是**每次请求都查一次数据库验证用户状态**（是否存在、是否被禁用），这样能立即生效。代价是每次请求多一次 DB 查询，失去了 JWT 完全无状态的优势——但对我们这个规模的系统，这个代价完全可以接受，换来的是'管理员能立即封禁用户'这个必要能力。
>
> 如果需要完全无状态 + 能失效，方案是维护一个 token 黑名单（Redis，带 TTL），但那又引入了状态。"

### 32.3.4 项目实现

`app/utils/jwt.py`（全文 28 行）：

```python
def create_access_token(user_id: int) -> str:
    """为指定用户生成访问令牌。"""
    expire = datetime.now() + timedelta(hours=settings.JWT_EXPIRE_HOURS)
    payload = {"user_id": user_id, "exp": expire}
    return jwt.encode(
        payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )


def decode_access_token(token: str) -> dict:
    """解析令牌。无效、过期、篡改都会抛出异常，由调用方捕获。"""
    return jwt.decode(
        token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
    )
```

**三个要点**：

**① `exp` 字段**

PyJWT 会自动校验 `exp`（过期时间），过期抛 `ExpiredSignatureError`。不需要自己判断。

**② `algorithms=[settings.JWT_ALGORITHM]` 是个列表**

这是 PyJWT 的安全要求。历史上有个著名漏洞：**攻击者把 header 里的 `alg` 改成 `none`**，如果服务端不限制算法，就会接受无签名的 token。

显式指定 `algorithms=["HS256"]` 杜绝了这个攻击。✅

**③ 异常由调用方捕获**

```python
def decode_access_token(token: str) -> dict:
    # 不 try/except，直接抛
```

调用方（`dependencies/auth.py:25-30`）：

```python
try:
    payload = decode_access_token(token)
except Exception:
    raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
```

**为什么不在这里 try？** 因为 `decode_access_token` 是工具函数，不该决定"失败了给用户看什么"。**异常处理的策略属于调用方**（API 层才知道要返回什么 HTTP 状态码）。这是分层的原则。

---

## 32.4 bcrypt：为什么"慢"反而安全

### 32.4.1 为什么不能用 MD5/SHA256

```python
# ❌ 错误做法
import hashlib
hash = hashlib.md5(password.encode()).hexdigest()
```

**两个致命问题**：

**问题 1：彩虹表**

MD5("123456") = `e10adc3949ba59abbe56e057f20f883e` —— 这个值是**固定**的。攻击者预先算好几十亿个常见密码的哈希，建一张表（彩虹表），拿到你的哈希直接反查。

**问题 2：快**

MD5 太快了。现代 GPU 每秒能算**几百亿次** MD5。即使加了盐，暴力破解一个 8 位密码也只要几小时。

### 32.4.2 bcrypt 的两个特性

**特性 1：自带随机盐**

```python
bcrypt.hashpw(b"123456", bcrypt.gensalt())
# → $2b$12$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy
#                ↑ 盐在这里

bcrypt.hashpw(b"123456", bcrypt.gensalt())    # 再算一次
# → $2b$12$8fJ...   完全不同的结果！
```

**同一个密码，两次哈希结果不同** —— 因为盐是随机的，并且**盐存在结果里**。

这直接废掉了彩虹表（攻击者要为"每个盐"建一张表，不可行）。

**特性 2：故意慢（work factor）**

`bcrypt.gensalt()` 默认 cost=12，意味着 **2^12 = 4096 轮**迭代。

| 算法 | 单次耗时 | GPU 每秒 |
|---|---|---|
| MD5 | ~0.001ms | 几百亿次 |
| bcrypt (cost=12) | **~250ms** | 几千次 |

**慢了 10 万倍**，暴力破解变得不可行。

而且 cost 可以调——**硬件变快了就调高 cost**，这是"可进化的安全"。

> **面试金句**："bcrypt 的价值在于**慢**。MD5 太快了，GPU 每秒能算几百亿次，暴力破解几小时就能破。bcrypt 通过 4096 轮迭代把单次哈希拉到 250 毫秒，慢了十万倍，暴力破解就不可行了。而且它的 cost 参数可以随硬件进步调高——这是'可进化的安全'。
>
> 另外它自带随机盐并把盐存在结果里，同一个密码两次哈希结果不同，直接废掉了彩虹表攻击。"

### 32.4.3 项目实现

`app/utils/password.py`（全文 22 行）：

```python
def hash_password(password: str) -> str:
    """把明文密码加密成不可逆的密文。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    """校验明文密码是否与数据库里的密文匹配。"""
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except ValueError:
        return False
```

**注意 `except ValueError: return False`** —— 如果数据库里的 hash 格式不对（比如旧数据、被篡改），`checkpw` 会抛 `ValueError`。捕获后返回 `False`（**登录失败**而不是 500 错误）。

**这是安全上的正确做法**：不因为数据异常就崩溃，而是拒绝登录。

---

## 32.5 RBAC：基于角色的访问控制

### 32.5.1 项目实现（后端）

`dependencies/auth.py:50-56`：

```python
def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """管理员鉴权：先登录，再判断角色。"""
    if current_user.role != "admin":
        raise BusinessException(message="无权限访问", code=403)
    return current_user
```

**★ 依赖的嵌套** —— 这是 FastAPI 依赖注入最优雅的用法：

```python
def get_current_user(token = Depends(oauth2_scheme), db = Depends(get_db)) -> User
def get_current_admin(current_user: User = Depends(get_current_user)) -> User
```

`get_current_admin` **依赖** `get_current_user`。FastAPI 会先执行后者拿到 user，再传给前者做角色判断。

**在路由里用**：

```python
@router.post("/documents")
async def upload_document(
    current_user: User = Depends(get_current_admin),   # 一行搞定
    db: Session = Depends(get_db),
):
```

**好处**：
- 路由函数只声明"我要管理员"，不关心怎么校验
- 校验逻辑集中在一处，改一次全生效
- **不会漏**（忘记写 `Depends(get_current_admin)` 就是没有鉴权，一目了然）

### 32.5.2 为什么用 `BusinessException(code=403)` 而不是 `HTTPException`

```python
raise BusinessException(message="无权限访问", code=403)
```

**统一异常体系**（第 7 章）：`BusinessException` 会被全局 handler 捕获，转成统一响应格式：

```json
{"code": 403, "message": "无权限访问", "data": null}
```

而 `HTTPException` 会转成 FastAPI 的默认格式：

```json
{"detail": "无权限访问"}
```

**用统一的格式，前端处理更简单**（一个拦截器搞定所有错误）。

**但注意**：`get_current_user` 里用的是 `HTTPException`（401）。为什么不一致？

因为 401 的响应需要带 `WWW-Authenticate` 头（OAuth2 规范），`OAuth2PasswordBearer` 和 `HTTPException` 配合能自动生成。**这是一个可以规范化的不一致点**——如果追求完全统一，可以改成 `BusinessException(code=401)` 并手动加响应头。

> **面试可以说**："我们的 401 用 HTTPException（因为 OAuth2 规范需要 `WWW-Authenticate` 头，FastAPI 的 HTTPException 会自动加），403 用 BusinessException（统一响应格式）。这确实是一处不一致，可以规范化，但当前两种都能正常工作。"

### 32.5.3 前端守卫（B2 修复）

`frontend/src/router/index.js:68-82`：

```javascript
router.beforeEach((to) => {
  const token = getToken()
  // ① 未登录 → 去登录页（带 redirect 参数，登录后跳回）
  if (!to.meta.public && !token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  // ② 已登录访问登录页 → 回首页
  if (to.path === '/login' && token) {
    return { path: '/manager/home' }
  }
  // ③ 管理员专属页面：非 admin 重定向回首页
  if (to.meta.admin && getUser()?.role !== 'admin') {
    return { path: '/manager/home' }
  }
  return true
})
```

**路由配置**（`meta.admin`）：

```javascript
{
  path: 'kb-manage',
  name: 'KbManage',
  component: () => import('@/views/KbManage.vue'),
  meta: { admin: true }      // ★ 标记需要管理员
}
```

三个管理员页面：`user`（用户管理）、`audit-reservation`（预约审核）、`kb-manage`（知识库管理）。

---

## 32.6 前后端双重鉴权：为什么都要做

**这是面试必问的经典问题。**

### 32.6.1 只做前端守卫行不行？

**不行。**

前端守卫只是**隐藏入口**——路由不跳转，但：

```bash
# 用户直接用 curl 调接口，完全绕过前端
curl -X POST http://localhost:8000/api/kb/documents \
     -H "Authorization: Bearer <普通用户的token>" \
     -F "file=@恶意文档.pdf"
```

**前端的 JS 代码在用户浏览器里，用户可以不看、不执行、或者篡改。** 前端的任何校验都只是"用户体验优化"，不是安全边界。

> **核心原则**：**任何安全校验都必须在服务端。前端校验只是为了体验（不用等一个必然失败的请求）。**

### 32.6.2 只做后端校验行不行？

**技术上可以**（安全上没问题），**但体验差**：

- 普通用户能看到"知识库管理"菜单，点进去加载一半才报错
- 或者页面能打开，但所有操作都失败

**前端守卫的价值**：
- 不显示无权访问的菜单/路由
- 减少无意义的请求
- 更清晰的错误引导

### 32.6.3 本项目的完整防护

| 层 | 做什么 | 能不能单独挡住攻击 |
|---|---|---|
| **前端路由守卫** | 隐藏入口、重定向 | ❌ 不能（可绕过） |
| **后端 `get_current_user`** | 认证（你是谁） | ❌ 不够（B1 漏洞） |
| **后端 `get_current_admin`** | 授权（你能不能） | ✅ 能 |

**三层缺一不可**：前端管体验，后端管安全；后端里认证管身份、授权管权限。

> **面试金句**："前后端都要做，但目的不同。**前端守卫是体验优化**（隐藏入口、减少无效请求），**后端校验才是安全边界**——因为前端代码在用户浏览器里，可以被绕过。我们项目就真实踩过这个坑：知识库接口只校验了'已登录'没校验'是管理员'，普通用户能直接调 curl 上传文档污染 RAG 检索源。修复是后端改用 `get_current_admin`，同时前端补上 `meta.admin` 路由守卫。"

### 32.6.4 一个重要的补充：资源级授权

`role == "admin"` 是**角色级**（RBAC 的粗粒度）。但还有一类漏洞是**水平越权**：

```
用户 A 能看用户 A 的资料     ✅
用户 A 能改用户 A 的预约     ✅
用户 A 能改用户 B 的预约     ❌ 水平越权！
```

角色判断挡不住这个（A 和 B 都是 student）。

**正确的做法**：在查询里加**归属过滤**：

```python
# ❌ 只查 id，不查归属
reservation = db.query(Reservation).filter(Reservation.id == rid).first()

# ✅ 加上归属条件
reservation = db.query(Reservation).filter(
    Reservation.id == rid,
    Reservation.user_id == current_user.id,     # ★ 只能操作自己的
).first()
```

**这是一个非常常见的漏洞类型**。检查本项目的 `reservation_service` 时要注意这一点。

---

## 32.7 最小骨架：手写 JWT 与守卫

```python
"""
minimal_auth.py —— JWT 签发/验签 + 防篡改演示 + RBAC 依赖链
运行：pip install pyjwt bcrypt && python minimal_auth.py
"""
import base64
import json
import time

import jwt

SECRET = "my-secret-key"        # 生产环境要从环境变量读，绝不能硬编码
ALGO = "HS256"


# ── 1. 签发 ────────────────────────────────────────────────
def create_token(user_id: int, expire_hours: int = 24) -> str:
    payload = {"user_id": user_id, "exp": time.time() + expire_hours * 3600}
    return jwt.encode(payload, SECRET, algorithm=ALGO)


def decode_token(token: str) -> dict:
    """★ algorithms 必须显式指定（防止 alg=none 攻击）。"""
    return jwt.decode(token, SECRET, algorithms=[ALGO])


# ── 2. 演示：JWT 可解码但不可篡改 ──────────────────────────
def peek(token: str):
    """任何人都能解码 Payload（Base64，不是加密）。"""
    part = token.split(".")[1]
    part += "=" * (-len(part) % 4)          # Base64 padding
    return json.loads(base64.urlsafe_b64decode(part))


def tamper(token: str, new_user_id: int) -> str:
    """攻击者尝试篡改 user_id。"""
    header, payload, sig = token.split(".")
    data = peek(token)
    data["user_id"] = new_user_id
    new_payload = base64.urlsafe_b64encode(
        json.dumps(data).encode()).decode().rstrip("=")
    return f"{header}.{new_payload}.{sig}"     # 签名还是旧的


# ── 3. RBAC：依赖链模拟 ────────────────────────────────────
USERS = {1: {"id": 1, "role": "student"}, 2: {"id": 2, "role": "admin"}}


def get_current_user(token: str) -> dict:
    """模拟 FastAPI 依赖：解析 token → 查库 → 检查状态。"""
    try:
        payload = decode_token(token)
    except Exception as exc:
        raise PermissionError(f"登录已失效：{type(exc).__name__}")
    uid = payload.get("user_id")
    user = USERS.get(uid)
    if not user:
        raise PermissionError("用户不存在")
    if user.get("status", 1) != 1:
        raise PermissionError("用户被禁用")
    return user


def get_current_admin(token: str) -> dict:
    """★ 依赖嵌套：先 get_current_user，再判断角色。"""
    user = get_current_user(token)
    if user["role"] != "admin":
        raise PermissionError("无权限访问")
    return user


if __name__ == "__main__":
    print("=" * 62)
    print("【① 签发与解码】")
    t = create_token(1)
    print(f"  token: {t[:50]}...")
    print(f"  Payload（任何人可解码）: {peek(t)}")
    print("  ⚠ 所以 Payload 里绝不能放敏感信息")

    print("\n【② 正常验签】")
    print(f"  结果: {decode_token(t)}")

    print("\n【③ ★ 防篡改演示：把 user_id 从 1 改成 2（管理员）】")
    bad = tamper(t, 2)
    print(f"  篡改后 Payload: {peek(bad)}")
    try:
        decode_token(bad)
        print("  ❌ 验签通过（不应该！）")
    except Exception as exc:
        print(f"  ✅ 验签失败：{type(exc).__name__}: {exc}")
        print("     → 攻击者不知道 secret，无法重新生成有效签名")

    print("\n【④ 过期 token】")
    expired = jwt.encode({"user_id": 1, "exp": time.time() - 10}, SECRET, algorithm=ALGO)
    try:
        decode_token(expired)
    except Exception as exc:
        print(f"  ✅ {type(exc).__name__}: {exc}")

    print("\n【⑤ RBAC 依赖链】")
    student_token = create_token(1)
    admin_token = create_token(2)

    for name, tok in [("普通用户", student_token), ("管理员", admin_token)]:
        print(f"\n  {name}:")
        try:
            print(f"    get_current_user → {get_current_user(tok)}")
        except PermissionError as e:
            print(f"    get_current_user → ❌ {e}")
        try:
            print(f"    get_current_admin → {get_current_admin(tok)}")
        except PermissionError as e:
            print(f"    get_current_admin → ❌ {e}")

    print("\n【⑥ 水平越权演示】")
    print("  角色判断挡不住'改别人的预约'：")
    print("    ❌ db.query(Reservation).filter(id == rid)")
    print("    ✅ db.query(Reservation).filter(id == rid, user_id == current_user.id)")
```

**预期输出（关键部分）**：

```
【③ ★ 防篡改演示：把 user_id 从 1 改成 2（管理员）】
  篡改后 Payload: {'user_id': 2, 'exp': ...}
  ✅ 验签失败：InvalidSignatureError: Signature verification failed
     → 攻击者不知道 secret，无法重新生成有效签名

【⑤ RBAC 依赖链】
  普通用户:
    get_current_user → {'id': 1, 'role': 'student'}
    get_current_admin → ❌ 无权限访问
  管理员:
    get_current_user → {'id': 2, 'role': 'admin'}
    get_current_admin → {'id': 2, 'role': 'admin'}
```

---

## 32.8 面试问答

### Q1：JWT 的原理？凭什么防篡改？

**答**：JWT 是三段 Base64：`header.payload.signature`。

**关键点是 Payload 只是 Base64 编码，不是加密**——任何人都能解码看到内容。所以安全不在"看不见"，而在**签名**：signature 是用服务端密钥（secret）对前两段算的 HMAC。

攻击者改了 Payload（比如把 user_id 改成管理员的），签名就对不上了。而他不知道 secret，**无法重新生成有效签名**。服务端验签失败 → 401。

这也说明：**JWT 里绝不能放敏感信息**（密码、身份证）。我们只放 `user_id` 和 `exp`。

另外 `algorithms` 必须显式指定（我们写 `algorithms=[JWT_ALGORITHM]`）——历史上有个漏洞是攻击者把 header 的 `alg` 改成 `none` 来绕过签名。

### Q2：JWT 登出后还能用吗？

**答**：能，这是 JWT 的固有问题——**无状态，签发后到过期前一直有效**。

我们的缓解是**每次请求都查一次数据库验证用户状态**（是否存在、`status != 1` 则拒绝）。这样管理员禁用用户能立即生效。

代价是每次请求多一次 DB 查询，失去了 JWT 完全无状态的优势。但对我们这个规模，这个代价完全可接受，换来"能立即封禁"这个必要能力。

如果要完全无状态又能失效，方案是维护 token 黑名单（Redis + TTL），但那又引入了状态——本质上是个取舍。

### Q3：为什么用 bcrypt 不用 MD5？

**答**：两个原因。

**一是 MD5 太快**。现代 GPU 每秒能算几百亿次 MD5，暴力破解一个 8 位密码只要几小时。bcrypt 通过 4096 轮迭代（cost=12）把单次哈希拉到 250 毫秒，慢了十万倍，暴力破解就不可行了。而且 cost 可以随硬件进步调高——这是"可进化的安全"。

**二是彩虹表**。MD5("123456") 的值是固定的，攻击者预先算好几十亿个常见密码的哈希建表，拿到哈希直接反查。bcrypt 自带随机盐且把盐存在结果里，**同一个密码两次哈希结果不同**，彩虹表就废了。

### Q4：后端校验了，前端还需要校验吗？

**答**：需要，但**目的不同**。

**后端校验是安全边界，前端校验是体验优化。** 前端代码在用户浏览器里，可以被绕过（直接 curl 调接口），所以任何安全校验都必须在服务端。前端守卫的价值是隐藏入口、减少无效请求、给出更清晰的引导。

我们项目真实踩过这个坑：知识库接口只用了 `get_current_user`（只校验已登录），没校验管理员角色。结果普通用户能直接用 curl 上传文档**污染 RAG 检索源**——这在 RAG 系统里尤其危险，因为知识库内容会直接进入模型上下文（数据投毒）。

修复是后端改用 `get_current_admin`，同时前端补上 `meta.admin` 路由守卫。

### Q5：RBAC 怎么实现的？

**答**：用 FastAPI 的依赖嵌套：

```python
def get_current_user(token = Depends(oauth2_scheme), db = Depends(get_db)) -> User
def get_current_admin(current_user: User = Depends(get_current_admin)) -> User
```

`get_current_admin` 依赖 `get_current_user`，FastAPI 先执行后者再执行前者。路由里只要写 `Depends(get_current_admin)` 一行。

好处是：路由只声明"我要管理员"不关心怎么校验；校验逻辑集中一处；**不容易漏**（没写 Depends 就是没鉴权，一目了然）。

### Q6：角色判断够吗？还有什么漏洞？

**答**：角色级授权（RBAC）不够，还有**水平越权**问题。

`role == "admin"` 只能区分"管理员 vs 普通用户"，挡不住"用户 A 改用户 B 的预约"——因为 A 和 B 角色相同。

正确的做法是在查询里加**归属过滤**：

```python
db.query(Reservation).filter(
    Reservation.id == rid,
    Reservation.user_id == current_user.id,     # ★ 只能操作自己的
)
```

只按 id 查不查归属，是这类系统最常见的漏洞之一。

### Q7：401 和 403 的区别？你们怎么处理的？

**答**：401 是"未认证"（不知道你是谁），403 是"已认证但无权限"（知道你是谁，但你不该访问）。

我们 401 用 `HTTPException`（配合 `OAuth2PasswordBearer` 会自动加 `WWW-Authenticate` 头，符合 OAuth2 规范），403 用 `BusinessException(code=403)`（走统一响应格式，前端一个拦截器处理）。

这确实是一处不一致（两种异常类型），可以规范化，但当前两种都能正常工作。

---

## 32.9 速记卡

> **认证（你是谁）+ 授权（你能做什么）。前端管体验，后端管安全。**

**JWT 三段**：header.payload.signature（都是 Base64）

**★ 防篡改靠签名**：Payload 可解码（**不加密**），改了签名对不上（攻击者无 secret）

**三误解**：不是加密 / localStorage 有 XSS 风险 / **不能主动失效**

**★ `algorithms=[...]` 必须显式指定**（防 `alg=none` 攻击）

**失效方案**：每次请求查库验证 `status` → 能立即封禁（代价：多一次查询）

**bcrypt**：**慢**（cost=12，250ms）+ **随机盐**（同密码不同结果）
- 慢 → 防暴力破解；盐 → 防彩虹表

**RBAC 依赖嵌套**：`get_current_admin` Depends `get_current_user`

**★ 越权类型**：
- **垂直越权**：普通用户做管理员的事 → `get_current_admin` 挡
- **水平越权**：用户 A 操作用户 B 的数据 → **归属过滤**挡（`user_id == current_user.id`）

**前后端双重**：前端 `meta.admin` + `beforeEach`（体验）；后端 `get_current_admin`（安全）

**B1/B2 缺陷**：知识库接口漏了角色校验 → 普通用户能污染 RAG 检索源

**代码位置**：
- JWT：`app/utils/jwt.py`
- 密码：`app/utils/password.py`
- 依赖：`app/dependencies/auth.py`
- 前端守卫：`frontend/src/router/index.js:68-82`

---

## 32.10 延伸思考

1. **如果要实现"记住我"（30 天免登录），JWT 怎么做？**
   提示：签发一个 `exp` 更长的 token（30 天）。风险是 token 被盗后有效期长。更好的方案是 **refresh token** 机制：access token 短（1 小时）+ refresh token 长（30 天，存在 HttpOnly Cookie），用 refresh 换新的 access。refresh token 可以被服务端主动失效。

2. **`get_current_user` 每次查库，能否优化？**
   提示：加缓存（Redis，`user:{id}` → `{role, status}`，TTL 5 分钟）。权衡：缓存期间用户被禁用不会立即生效（最多延迟 5 分钟）。**对于安全相关的状态，缓存要谨慎**。

3. **前端把 role 存在 localStorage 里（`getUser()?.role`），用户手动改了会怎样？**
   提示：前端守卫会失效（用户能看到管理员页面），但**后端校验仍然有效**——所有管理员接口的请求都会被拒。这正是"前端校验只是体验"的最好证明。但要注意：页面能打开却所有操作失败，体验很差，所以前端守卫还是有价值的。

---

**下一章**：第 33 章 · 前端 Vue3 工程——对话界面怎么搭？审批确认框怎么和 Agent 的 interrupt 联动？
