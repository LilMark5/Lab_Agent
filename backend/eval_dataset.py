"""RAG 评估数据集（检索侧与生成侧共用）。

每条用例统一带四个字段：

- ``question``：用户问题。
- ``ground_truth``：标准答案。RAGAS 里 context_precision / context_recall 这类
  需要 reference 的指标要用它。
- ``expected_source``：检索时应当命中的知识库文档名（不含 ``.md``）。
  仅仅服务检索指标；为 ``None`` 表示这是「知识库答不了」的边界用例，
  不计入 Hit@K / MRR / nDCG。
- ``category``：``factual``（资料里有答案）或 ``refusal``（应当坦承资料里没有，
  而不是编造）。

为什么单独抽成一个文件：检索评估（``evaluate_rag.py``）和生成评估
（``evaluate_generation.py``）必须问同一批问题，两个分数才能互相印证；
各写一份必然随时间发散，最后没人知道哪个分数对应哪套题。
"""

CASES: list[dict] = [
    # ---------- 开放时间.md ----------
    {
        "question": "人工智能实验室周末几点开放？",
        "ground_truth": "人工智能实验室周末 09:00 开放，17:00 关闭。",
        "expected_source": "开放时间",
        "category": "factual",
    },
    {
        "question": "机器人实验室周末开放吗？",
        "ground_truth": (
            "不开放。机器人实验室只在周一至周五 08:30-18:00 开放，周末不开放。"
        ),
        "expected_source": "开放时间",
        "category": "factual",
    },
    {
        "question": "云计算实验室的开放时间是几点到几点？",
        "ground_truth": "云计算实验室周一至周日 08:00-20:00 开放。",
        "expected_source": "开放时间",
        "category": "factual",
    },
    {
        "question": "开放时间内我可以直接进实验室吗？",
        "ground_truth": (
            "不可以。即使在开放时间内，也仍然需要先预约并审核通过，不能直接进入。"
        ),
        "expected_source": "开放时间",
        "category": "factual",
    },
    # ---------- 预约规则.md ----------
    {
        "question": "预约提交之后马上就可以用了吗？",
        "ground_truth": (
            "不是。提交后状态为待审核，必须等管理员通过以后才能使用。"
        ),
        "expected_source": "预约规则",
        "category": "factual",
    },
    {
        "question": "已经通过的预约还能取消吗？",
        "ground_truth": (
            "可以。待审核和已通过的预约，本人都可以取消；已被拒绝的预约不能取消。"
        ),
        "expected_source": "预约规则",
        "category": "factual",
    },
    {
        "question": "怎么提交一次实验室预约？",
        "ground_truth": (
            "登录后打开实验室列表，选择实验室或设备，填写日期和时段，然后提交。"
        ),
        "expected_source": "预约规则",
        "category": "factual",
    },
    # ---------- 设备使用.md ----------
    {
        "question": "预约设备的时候需要注意什么？",
        "ground_truth": (
            "预约设备时必须同时选择所属实验室；设备与实验室绑定，约了设备则该时段内"
            "对应的实验室也会被占用；使用前要检查设备外观与状态，结束后按规范登记。"
        ),
        "expected_source": "设备使用",
        "category": "factual",
    },
    {
        "question": "我只预约设备、不选实验室可以吗？",
        "ground_truth": "不可以。预约设备时必须同时选择设备所属的实验室。",
        "expected_source": "设备使用",
        "category": "factual",
    },
    # ---------- 安全规范.md ----------
    {
        "question": "设备突然坏了应该怎么处理？",
        "ground_truth": (
            "应立即停用该设备，并联系实验室管理员，不要自行拆修。"
        ),
        "expected_source": "安全规范",
        "category": "factual",
    },
    {
        "question": "实验室里可以吃零食吗？",
        "ground_truth": "不可以。严禁把零食带进实验区域。",
        "expected_source": "安全规范",
        "category": "factual",
    },
    {
        "question": "离开实验室之前要做什么？",
        "ground_truth": "离开前要关闭电源、水源，并清理台面。",
        "expected_source": "安全规范",
        "category": "factual",
    },
    # ---------- 边界用例：知识库没有答案，考的是「不编造」 ----------
    {
        "question": "实验室的 Wi-Fi 密码是多少？",
        "ground_truth": (
            "知识库里没有 Wi-Fi 密码相关信息，正确做法是说明资料中没有该信息，"
            "不要编造一个密码。"
        ),
        "expected_source": None,
        "category": "refusal",
    },
    {
        "question": "单次预约最长可以约几个小时？",
        "ground_truth": (
            "知识库没有规定单次预约的时长上限，正确做法是说明资料里没有相关规定，"
            "建议咨询管理员，不要编造一个时长。"
        ),
        "expected_source": None,
        "category": "refusal",
    },
]


def factual_cases() -> list[dict]:
    """只取「资料里有答案」的用例，检索指标用这批。"""
    return [case for case in CASES if case["expected_source"]]


def labeled_pairs() -> list[tuple[str, str]]:
    """给检索评估用的 (问题, 应命中文档名) 列表。"""
    return [(case["question"], case["expected_source"]) for case in factual_cases()]
