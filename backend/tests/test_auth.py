"""鉴权依赖测试：管理员角色判断。"""

from types import SimpleNamespace

import pytest

from app.common.exceptions import BusinessException
from app.dependencies import auth


def test_get_current_admin_allows_admin():
    admin = SimpleNamespace(id=1, role="admin")
    assert auth.get_current_admin(admin) is admin


def test_get_current_admin_rejects_non_admin():
    student = SimpleNamespace(id=2, role="student")
    with pytest.raises(BusinessException) as exc:
        auth.get_current_admin(student)
    assert exc.value.code == 403
