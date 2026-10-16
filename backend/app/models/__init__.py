"""ORM 模型包。

导入顺序会影响外键关系的注册。`main.py` 在 create_all 前显式导入所有模型，
因此 SQLAlchemy 才知道需要创建哪些表。
"""
