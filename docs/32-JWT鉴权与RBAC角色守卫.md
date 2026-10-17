# 32 · JWT 鉴权与 RBAC 角色守卫

> **速成定位**：安全题必考。面试官问「你怎么保证接口不被越权」「token 被篡改怎么办」「前后端鉴权怎么配合」，全在这一篇。
> **一句话**：密码用 bcrypt 加盐慢哈希存储；登录签发 JWT（服务端不存会话）；接口按需要声明 `get_current_user`（登录）或 `get_current_admin`（管理员）；前端再加一道路由守卫做体验拦截。

---

## 目录

1. [认证 vs 授权](#1-认证-vs-授权)
2. [密码存储：为什么必须是 bcrypt](#2-密码存储)
3. [JWT 结构与防篡改原理](#3-jwt-结构与防篡改原理)
4. [JWT vs Session](#4-jwt-vs-session)
5. [RBAC：两层鉴权依赖](#5-rbac两层鉴权依赖)
6. [前端配合：路由守卫 + 拦截器](#6-前端配合)
7. [最小可运行骨架](#7-最小可运行骨架)
8. [项目里对应哪块代码](#8-项目里对应哪块代码)
9. [面试高频问答](#9-面试高频问答)
10. [速记卡](#10-速记卡)

---

## 1. 认证 vs 授权

这两个词面试时必须分清：

| 概念 | 英文 | 回答的问题 | 本项目实现 |
| --- | --- | --- | --- |
| **认证** | Authentication (AuthN) | 「你是谁？」 | 登录 + JWT |
| **授权** | Authorization (AuthZ) | 「你能做什么？」 | `role` 字段 + `get_current_admin` |

典型错误：把「没登录」和「没权限」混为一谈。本项目分开处理：

- 没登录 / token 失效 → **HTTP 401**（`get_current_user` 抛 `HTTPException(401)`）
- 登录了但不是管理员 → **业务 403**（`get_current_admin` 抛 `BusinessException(code=403)`）

---

## 2. 密码存储

### 为什么不能明文 / MD5

| 方案 | 问题 |
| --- | --- |
| 明文 | 数据库一泄露，所有账号直接失守 |
| MD5 / SHA1 | **快哈希**，GPU 每秒可算几十亿次，彩虹表秒破 |
| 加固定盐的 SHA256 | 盐固定则所有用户共用，撞库仍有效 |
| **bcrypt** | ✅ **慢哈希 + 每用户随机盐**，且可配置计算代价（cost）随硬件升级提高 |

### bcrypt 的两个关键性质

1. **自带随机盐**：`bcrypt.gensalt()` 每次生成不同盐，所以**两个相同密码的密文不同**，无法撞库比对。
2. **故意慢**：内部做大量迭代（Blowfish 密钥扩展），把单次校验拖到百毫秒级。对正常登录无感，对暴力破解是灾难。

本项目 `app/utils/password.py`：

```python
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False        # 密文格式异常时视为校验失败，不让异常外泄
```

**注意**：`verify_password` 里没有 `==` 比较——因为盐不同，`hashpw` 结果不同，必须用 `checkpw`（它从密文里取出盐重新计算）。

---

## 3. JWT 结构与防篡改原理

### 3.1 三段结构

```
eyJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoxLCJleHAiOjE3NjE9fQ.8Zq3k...
└──── header ─────┘└──────── payload ────────┘└─ signature ─┘
```

本项目生成的 payload（`utils/jwt.py:17`）：

```python
payload = {"user_id": user_id, "exp": expire}     # exp 是标准声明：过期时间
```

- **header**：`{"alg": "HS256", "typ": "JWT"}`
- **payload**：业务声明（user_id）+ 标准声明（exp）
- **signature**：`HMAC-SHA256(base64(header) + "." + base64(payload), 密钥)`

### 3.2 为什么改不了

签名是用**服务端密钥**算的。攻击者改了 payload（比如把 `user_id` 改成管理员 ID），但没有密钥，算不出匹配的新签名 → 服务端 `jwt.decode` 验签失败 → 抛异常 → 401。

```python
def decode_access_token(token: str) -> dict:
    """解析令牌。无效、过期、篡改都会抛出异常，由调用方捕获。"""
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
```

> **面试必答**：「JWT 的 payload 只是 **base64 编码，不是加密**，任何人都能解码看到内容。所以**绝不能把密码、手机号等敏感信息放进 payload**。我里面只放了 `user_id` 和 `exp`。」

### 3.3 「算法」参数的安全意义

`algorithms=[settings.JWT_ALGORITHM]` 必须**显式指定**。如果省略（用库的默认行为），历史上出现过 `alg: none` 攻击——攻击者把 header 的 alg 改成 `none` 让服务端跳过验签。**显式白名单算法**就是防这个的。

---

## 4. JWT vs Session

| | JWT（本项目） | Session + Cookie |
| --- | --- | --- |
| 服务端状态 | **无状态**，不存会话 | 存 session（内存/Redis） |
| 扩展性 | 多实例直接水平扩展 | 需要共享 session 存储 |
| 吊销 | **难**：签发后到过期前一直有效 | 易：删服务端 session 即失效 |
| 适合 | 前后端分离、微服务、AI 后端 | 传统 SSR 网站 |

**本项目的取舍**：前后端分离 + 前端用 `Authorization` 头而非 Cookie（所以 CORS 可以关掉 `allow_credentials`），JWT 是自然选择。

**代价与补救**（面试主动说）：
- JWT 无法即时吊销 → 本项目用较短有效期（默认 24 小时，`JWT_EXPIRE_HOURS`）。
- 真正需要即时下线（踢人）时，生产方案是**短期 access token + 长期 refresh token + Redis 黑名单**。

---

## 5. RBAC：两层鉴权依赖

### 5.1 第一层：登录即可（`get_current_user`）

`dependencies/auth.py:21-47`：

```python
def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    try:
        payload = decode_access_token(token)          # 验签 + 过期检查
    except Exception:
        raise HTTPException(401, "登录已失效，请重新登录")

    user_id = payload.get("user_id")
    if not user_id:
        raise HTTPException(401, "无效的登录凭证")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(401, "用户不存在")
    if user.status != 1:
        raise HTTPException(401, "用户被禁用")
    return user
```

**四个检查点**（背下来）：token 可解析 → payload 有 user_id → 用户仍存在 → 用户未被禁用。

> **面试点**：为什么要查库而不是只信 token？因为用户可能已被禁用/删除，token 本身还没过期。**token 只证明身份，不证明当前仍有效**。

### 5.2 第二层：管理员（`get_current_admin`）

```python
def get_current_admin(current_user: User = Depends(get_current_user)) -> User:
    """管理员鉴权：先登录，再判断角色。"""
    if current_user.role != "admin":
        raise BusinessException(message="无权限访问", code=403)
    return current_user
```

这就是**依赖嵌套**：先跑 `get_current_user`（含查库），再判角色。路由上只写一行：

```python
current_user: User = Depends(get_current_admin)
```

### 5.3 一个真实修复过的越权漏洞（重要面试素材）

知识库接口（上传/列表/删除/检索）原本只用了 `get_current_user`，意味着**任何登录的普通学生都能上传文档污染 RAG 语料、删除知识库**。这是代码审查发现的阻断级缺陷（B1），已全部改为 `get_current_admin`。

> **面试话术**：「我在自审时发现知识库 4 个接口漏了管理员校验，低权限用户可以污染 RAG 语料——这对 RAG 系统是致命的，因为脏语料会直接进模型上下文。已修复并补了测试。」

同理前端 `router/index.js` 原本只判断 token 不判断角色，已补 `meta.admin` 守卫。

---

## 6. 前端配合

**重要认知**：前端守卫只是**用户体验**，真正的鉴权**永远在后端**。前端拦不住人直接调接口。

### 6.1 路由守卫（`frontend/src/router/index.js:70-83`）

```js
router.beforeEach((to) => {
  const token = getToken()
  if (!to.meta.public && !token) {
    return { path: '/login', query: { redirect: to.fullPath } }   // 未登录 → 登录页
  }
  if (to.path === '/login' && token) {
    return { path: '/manager/home' }                              // 已登录别回登录页
  }
  if (to.meta.admin && getUser()?.role !== 'admin') {
    return { path: '/manager/home' }                              // 非管理员 → 首页
  }
  return true
})
```

三个管理页标了 `meta: { admin: true }`：`user`（用户管理）、`audit-reservation`（预约审核）、`kb-manage`（知识库管理）。

### 6.2 axios 拦截器（`frontend/src/utils/request.js`）

请求拦截：自动带 token

```js
config.headers.Authorization = `Bearer ${token}`
```

响应拦截：统一处理业务码

```js
if (res.code === 200) return res
if (res.code === 401) { logout(); ElMessage.error('登录已失效') }
else ElMessage.error(res.message)
return Promise.reject(...)
```

HTTP 401 时还会跳转登录页：`window.location.href = '/login'`。

---

## 7. 最小可运行骨架

`pip install pyjwt bcrypt` 后可直接运行，演示**注册哈希 → 登录签发 → 验签 → 越权拦截**全流程。

```python
"""最小骨架：bcrypt 密码哈希 + JWT 签发/验签 + 两级鉴权。"""

import datetime as dt

import bcrypt
import jwt

SECRET = "demo-secret-change-me"     # 生产必须换成足够长的随机值并放环境变量
ALGO = "HS256"
EXPIRE_HOURS = 24

# ============ 模拟「数据库」 ============
DB = {"users": {}}        # username -> {"id", "password_hash", "role", "status"}
_seq = {"id": 0}


# ============ 1. 密码：bcrypt 加盐慢哈希 ============
def hash_password(password: str) -> str:
    """每次 gensalt 都不同 → 相同密码的密文也不同。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """必须用 checkpw：它从密文里取盐重算，不能用 == 比较。"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


# ============ 2. JWT 签发与验签 ============
def create_access_token(user_id: int) -> str:
    """payload 只放非敏感信息：user_id + 过期时间。"""
    expire = dt.datetime.now() + dt.timedelta(hours=EXPIRE_HOURS)
    return jwt.encode({"user_id": user_id, "exp": expire}, SECRET, algorithm=ALGO)


def decode_access_token(token: str) -> dict:
    """algorithms 必须显式白名单，防止 alg:none 绕过验签。"""
    return jwt.decode(token, SECRET, algorithms=[ALGO])


# ============ 3. 业务：注册 / 登录 ============
class BizError(Exception):
    def __init__(self, message, code=500):
        self.message, self.code = message, code


def register(username: str, password: str, role: str = "student"):
    if username in DB["users"]:
        raise BizError("账号已存在")
    _seq["id"] += 1
    DB["users"][username] = {
        "id": _seq["id"],
        "password_hash": hash_password(password),
        "role": role,
        "status": 1,
    }


def login(username: str, password: str) -> str:
    """账号不存在与密码错误【统一提示】，防止账号枚举。"""
    user = DB["users"].get(username)
    if not user or not verify_password(password, user["password_hash"]):
        raise BizError("账号或密码错误")
    if user["status"] != 1:
        raise BizError("账号被禁用")
    return create_access_token(user["id"])


# ============ 4. 两级鉴权依赖（模拟 FastAPI 的 Depends） ============
def get_current_user(token: str) -> dict:
    """第一层：只要登录即可。"""
    try:
        payload = decode_access_token(token)      # 验签 + 过期检查
    except jwt.PyJWTError:
        raise BizError("登录已失效，请重新登录", code=401)

    user_id = payload.get("user_id")
    if not user_id:
        raise BizError("无效的登录凭证", code=401)

    # 关键：不能只信 token，还要查库确认用户仍有效（可能被禁用/删除）
    user = next((u for u in DB["users"].values() if u["id"] == user_id), None)
    if not user:
        raise BizError("用户不存在", code=401)
    if user["status"] != 1:
        raise BizError("用户被禁用", code=401)
    return user


def get_current_admin(token: str) -> dict:
    """第二层：先登录，再判角色。"""
    user = get_current_user(token)                  # 依赖嵌套
    if user["role"] != "admin":
        raise BizError("无权限访问", code=403)       # 403 是授权失败，不是 401
    return user


# ============ 5. 自测 ============
if __name__ == "__main__":
    register("alice", "123456")                     # 普通学生
    register("root", "admin123", role="admin")      # 管理员

    t_alice = login("alice", "123456")
    t_root = login("root", "admin123")
    print("登录成功，token 前 25 位:", t_alice[:25], "...")

    # (1) 正常访问
    print("alice 访问普通接口:", get_current_user(t_alice)["role"])

    # (2) 越权：普通学生访问管理员接口
    try:
        get_current_admin(t_alice)
    except BizError as e:
        print(f"✅ 越权被拦截: code={e.code} {e.message}")

    # (3) 篡改 token：把 user_id 改成管理员 id
    import base64, json
    head, payload_b64, sig = t_alice.split(".")
    payload = json.loads(base64.urlsafe_b64decode(payload_b64 + "=="))
    payload["user_id"] = 2                                        # 想冒充管理员
    forged_payload = base64.urlsafe_b64encode(
        json.dumps(payload).encode()).decode().rstrip("=")
    forged = f"{head}.{forged_payload}.{sig}"                     # 签名还是旧的
    try:
        get_current_user(forged)
    except BizError as e:
        print(f"✅ 篡改 token 被拦截: code={e.code} {e.message}")
```

**预期输出**：

```text
登录成功，token 前 25 位: eyJhbGciOiJIUzI1NiIsInR5c...
alice 访问普通接口: student
✅ 越权被拦截: code=403 无权限访问
✅ 篡改 token 被拦截: code=401 登录已失效，请重新登录
```

**第 4 行是核心**：payload 改了但签名对不上，验签直接失败——这就是 JWT 防篡改的实证。

---

## 8. 项目里对应哪块代码

### 8.1 后端

| 关注点 | 文件:行 | 内容 |
| --- | --- | --- |
| 密码哈希 | `utils/password.py:10-12` | `bcrypt.hashpw` + `gensalt()` |
| 密码校验 | `utils/password.py:15-22` | `bcrypt.checkpw`，`ValueError` 兜底返回 False |
| 签发 token | `utils/jwt.py:14-20` | payload = `{user_id, exp}` |
| 验签 token | `utils/jwt.py:23-27` | `algorithms=[ALGO]` 显式白名单 |
| 登录 | `services/auth_service.py:13-24` | **统一错误提示防账号枚举** |
| 注册 | `services/auth_service.py:27-43` | `role="student"`（**注册不能提权**） |
| 第一层鉴权 | `dependencies/auth.py:21-47` | 验签 → user_id → 存在 → 未禁用 |
| 第二层鉴权 | `dependencies/auth.py:50-56` | `role != "admin"` → 403 |
| OAuth2 声明 | `dependencies/auth.py:18` | `OAuth2PasswordBearer(tokenUrl="/api/auth/login")` |
| 知识库接口 | `api/kb.py` | 4 个接口全部 `get_current_admin`（修复后的） |

### 8.2 前端

| 关注点 | 文件:行 | 内容 |
| --- | --- | --- |
| 路由守卫 | `router/index.js:70-83` | 未登录 → login；`meta.admin` 非管理员 → home |
| 管理页标记 | `router/index.js:30 / 49 / 56` | `user` / `audit-reservation` / `kb-manage` |
| 请求带 token | `utils/request.js:12-18` | `Authorization: Bearer <token>` |
| 401 处理 | `utils/request.js:22-27 / 34-38` | logout + 提示 + 跳登录页 |
| 角色来源 | `utils/user.js` | `getUser()` 从 localStorage 读用户对象 |

### 8.3 配置（`config.py`）

```python
JWT_SECRET_KEY: str = "dev-only-secret-key-change-me-in-production"
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_HOURS: int = 24
```

> **面试必须主动说**：「默认密钥是开发用的占位值，注释里明确写了生产必须换成足够长的随机值并放进环境变量，不进代码仓库。」

---

## 9. 面试高频问答

**Q1：JWT 被篡改了怎么办？**
> 改不了。签名是 `HMAC-SHA256(header.payload, 服务端密钥)` 算出来的，攻击者没有密钥，改了 payload 就对不上签名，`jwt.decode` 抛异常返回 401。另外我在 decode 时显式传了 `algorithms=[HS256]`，防止历史上的 `alg: none` 绕过验签攻击。

**Q2：JWT 里能放敏感信息吗？**
> 不能。payload 只是 base64 编码不是加密，任何人都能解码看到。我里面只放 `user_id` 和 `exp`。

**Q3：JWT 怎么注销 / 踢人下线？**
> 这正是 JWT 的弱点：签发后在过期前一直有效。本项目用较短有效期（24 小时）控制风险。生产要做到即时下线，方案是**短期 access token + refresh token + Redis 黑名单**，或者改用服务端 session 存储。

**Q4：为什么不用 Session？**
> 前后端分离、可能多实例部署，Session 需要服务端共享存储（Redis），而 JWT 无状态可以直接水平扩展。代价是无法即时吊销，我通过缩短有效期来缓解。

**Q5：为什么登录失败要统一提示「账号或密码错误」？**
> 防止**账号枚举**。如果分别提示「账号不存在」和「密码错误」，攻击者就能据此批量探测哪些账号已注册，再针对性撞库。统一提示后攻击者无法区分。

**Q6：token 有效但用户被禁用了怎么办？**
> token 只证明「签发时是谁」，不证明「现在仍有效」。所以 `get_current_user` 会**查库**确认用户存在且 `status == 1`，这两个检查不能省。

**Q7：注册接口能不能提权成管理员？**
> 不能。`register` 里硬编码 `role="student"`，角色不接受前端传入。管理员账号由初始化种子数据（`init_data.py`）创建。

**Q8：401 和 403 的区别，你们怎么用的？**
> 401 是**认证**失败（没登录/token 失效/用户被禁用），403 是**授权**失败（登录了但角色不够）。本项目 `get_current_user` 抛 HTTP 401，`get_current_admin` 抛业务异常 code=403。

**Q9：前端做了路由守卫，后端还需要鉴权吗？**
> 绝对需要。前端守卫只是用户体验（不展示不该看的页面、避免跳转到登录页），攻击者可以直接用 curl 调接口绕过前端。**真正的鉴权永远在后端**，这是本项目修过的一个真实认知点——知识库接口曾只靠前端隐藏，后端漏了 admin 校验。

**Q10：密钥怎么管理？**
> 放在 `.env` 里由 `pydantic-settings` 读取，不进代码仓库（`.gitignore` 忽略 `.env`），`.env.example` 只给占位说明。生产用环境变量注入。

---

## 10. 速记卡

```text
AuthN(你是谁) vs AuthZ(你能做什么) → 401 vs 403

密码：bcrypt 慢哈希 + 每用户随机盐
      相同密码密文不同 → 必须用 checkpw，不能 ==
      不用 MD5/SHA(快哈希,彩虹表可破)

JWT = header.payload.signature
  payload 只 base64 不加密 → 只放 user_id + exp，禁放敏感信息
  防篡改：改 payload → 签名对不上 → 401
  decode 必须显式 algorithms=[HS256]（防 alg:none）
  缺点：无法即时吊销 → 短有效期 / refresh token + Redis 黑名单

两级依赖：
  get_current_user  → 验签/查库/状态检查 → 401
  get_current_admin → 再判 role != "admin" → 403

安全细节：
  登录统一提示「账号或密码错误」防账号枚举
  注册硬编码 role="student" 防提权
  密钥进 .env，不进仓库

前端：路由守卫(体验) + axios 拦截器(带 token / 401 跳登录)
      ⚠️ 真鉴权永远在后端
```
