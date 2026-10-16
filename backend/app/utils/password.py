"""密码加密与校验。

永远不要明文存储密码。bcrypt 是一种带盐的慢哈希算法，
即使两个用户密码相同，得到的密文也不同。
"""

import bcrypt


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
