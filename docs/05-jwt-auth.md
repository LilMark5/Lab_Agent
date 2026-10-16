# 05 · JWT 鉴权：一次登录如何保护所有接口

## 1. 为什么不用 Session + Cookie？

传统 Web 常用服务端 Session + Cookie。但在前后端分离、多服务、移动端场景，
Session 需要服务端共享存储，扩展麻烦。

JWT 是无状态的：用户信息（claims）放在 token 里，服务端只负责验签。
任何持有同一密钥的服务都能验证 token，适合微服务。

## 2. JWT 的结构

JWT 由三部分组成，用 `.` 连接：

```text
header.payload.signature
```

- header：算法信息，如 `{"alg":"HS256"}`。
- payload：业务信息，如 `{"user_id":1,"exp":...}`。
- signature：用密钥对前两部分签名，防止篡改。

注意：JWT 默认只是 Base64URL 编码，不是加密。**不要放密码等敏感信息。**

## 3. 登录流程

```text
前端提交 username + password
  -> 后端查用户
  -> bcrypt 校验密码
  -> 生成 token
  -> 返回 {token, user}
  -> 前端 localStorage 保存
```

本项目：

```python
token = create_access_token(user.id)
```

`create_access_token` 里：

```python
payload = {"user_id": user_id, "exp": expire}
return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
```

## 4. 访问受保护接口

前端请求拦截器自动加头：

```js
config.headers.Authorization = `Bearer ${token}`
```

后端用 `OAuth2PasswordBearer` 从请求头取 token：

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")
```

然后 `decode_access_token` 验签并取出 `user_id`，从数据库加载用户。

## 5. 为什么要查一次数据库？

有些教程只解析 token 就直接信任里面的 user_id。但本项目还会查数据库：

```python
user = db.query(User).filter(User.id == user_id).first()
if user.status != 1:
    raise HTTPException(...)
```

这样能及时感知“用户被禁用、被删除”的状态变化。否则已经签发的 token
在过期前仍然有效。

## 6. bcrypt 为什么安全？

不要明文存密码，也不要只存 MD5。bcrypt 的特点：

- 带随机盐：同样密码每次哈希结果不同。
- 计算慢：增加暴力破解成本。
- 不可逆：只能校验，不能还原。

本项目把 bcrypt 密文存进数据库：

```python
password=hash_password(data.password)
```

登录时：

```python
verify_password(data.password, user.password)
```

## 7. 前端存储 token 的权衡

本项目为了简单用 localStorage。它的风险是：如果页面存在 XSS，攻击者可以偷走 token。

更安全的方案：

- HttpOnly Cookie + CSRF 防护。
- 或短 token + refresh token，并缩短有效期。

对于学习项目，理解“前端能改 token、后端必须独立验签”更重要。

## 8. 检查清单

- JWT 是加密还是签名？
- `Authorization: Bearer xxx` 中 Bearer 是什么？
- 为什么解析 token 后还要查数据库？
- bcrypt 和 MD5 的核心区别是什么？
