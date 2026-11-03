"""初始化演示数据。

为了方便学习，项目第一次启动时自动创建：
- 管理员账号 admin / 123456
- 学生账号 student / 123456
- 四个示例实验室及若干设备
"""

from app.database import SessionLocal
from app.models.equipment import Equipment
from app.models.lab import Lab
from app.models.user import User
from app.utils.password import hash_password


def seed_if_empty() -> None:
    db = SessionLocal()
    try:
        if not db.query(User).first():
            admin = User(
                username="admin",
                password=hash_password("123456"),
                name="管理员",
                role="admin",
                status=1,
            )
            student = User(
                username="student",
                password=hash_password("123456"),
                name="学生示例",
                role="student",
                status=1,
            )
            db.add_all([admin, student])

        if not db.query(Lab).first():
            labs = [
                Lab(
                    name="人工智能实验室",
                    location="实验楼 A301",
                    capacity=30,
                    open_time="08:00",
                    close_time="21:00",
                    description="配备 GPU 服务器，适合深度学习与模型训练。",
                    status=1,
                ),
                Lab(
                    name="机器人实验室",
                    location="实验楼 B205",
                    capacity=20,
                    open_time="08:30",
                    close_time="18:00",
                    description="提供机械臂、移动机器人等实验平台。",
                    status=1,
                ),
                Lab(
                    name="云计算实验室",
                    location="实验楼 C102",
                    capacity=40,
                    open_time="08:00",
                    close_time="20:00",
                    description="云主机与大数据集群实验环境。",
                    status=1,
                ),
                Lab(
                    name="软件工程实验室",
                    location="实验楼 D401",
                    capacity=35,
                    open_time="08:00",
                    close_time="21:00",
                    description="软件开发、测试与项目管理实训室。",
                    status=1,
                ),
            ]
            db.add_all(labs)
            db.flush()

            if not db.query(Equipment).first():
                db.add_all(
                    [
                        Equipment(
                            lab_id=labs[0].id,
                            name="RTX4090 服务器",
                            spec="24G 显存",
                            quantity=4,
                            description="深度学习训练显卡。",
                            status=1,
                        ),
                        Equipment(
                            lab_id=labs[0].id,
                            name="机械臂",
                            spec="六轴",
                            quantity=2,
                            description="机器人控制实验。",
                            status=1,
                        ),
                        Equipment(
                            lab_id=labs[1].id,
                            name="NAO 机器人",
                            spec="V6",
                            quantity=2,
                            description="人形机器人编程。",
                            status=1,
                        ),
                        Equipment(
                            lab_id=labs[2].id,
                            name="云主机集群",
                            spec="16C/64G",
                            quantity=8,
                            description="云计算虚拟化实验。",
                            status=1,
                        ),
                        Equipment(
                            lab_id=labs[3].id,
                            name="工位电脑",
                            spec="i7/32G",
                            quantity=35,
                            description="软件开发工作站。",
                            status=1,
                        ),
                    ]
                )

        db.commit()
    finally:
        db.close()
