# 21 RAG 生成质量评估（RAGAS）

对应代码：[evaluate_generation.py](../backend/evaluate_generation.py)、
[eval_dataset.py](../backend/eval_dataset.py)。

姊妹篇：[07 RAG 深入浅出](07-rag-deep-dive.md) 讲检索怎么搭，
[15 Milvus 与混合检索](15-milvus-hybrid-search.md) 讲召回怎么融合，
本篇讲**怎么证明这套 RAG 的答案是对的**。

## 1. 为什么检索指标不够

项目原本只有检索侧指标：Hit@K / MRR / nDCG（见 `backend/evaluate_rag.py`）。
但检索指标满分不等于答案能用。两种典型翻车：

- 召回的块**确实包含答案**，但模型回答时把数字读错了、或者把两个实验室的开放时间串了。
- **召回的块里根本没有答案**（用户问了个知识库覆盖不到的问题），模型不承认，
  顺手编一个看起来很合理的答案。这种情况 Hit@K 是 0，但它在检索指标里和
  「没搜到但老实说没搜到」完全无法区分——而这两者对用户是天壤之别。

所以需要答案侧指标。RAGAS 是目前社区最通用的选择。

## 2. 四个指标分别在算什么

| 指标 | 一句话 | 需要标准答案？ | 适用用例 |
| --- | --- | --- | --- |
| faithfulness | 答案里的每句话，是否都能在召回的上下文里找到依据 | 否 | 全部 |
| answer_relevancy | 答案是否正面回答了问题，而不是答非所问 | 否 | 事实类 |
| context_precision | 有用的召回内容有没有排到前面（**看排序，不看比例**） | 是 | 事实类 |
| context_recall | 标准答案里的信息有多少被召回覆盖 | 是 | 事实类 |

实现上都是「让大模型当裁判」，RAGAS 负责把裁判的判断折算成 0~1 的分数。
所以**衡量的是模型判断，不是客观真值**——这点后面第 6 节有专门的验证方法。

### context_precision 的口径陷阱（最容易误读）

它是 **average precision**，衡量**排序质量**，不是「相关块占比」。

实测（喂同一个问题「人工智能实验室周末几点开放？」，标准答案
「周末 09:00 开放，17:00 关闭」）：

| 上下文组成 | context_precision |
| --- | --- |
| 1 条相关 | 1.000 |
| 2 条完全无关 | 0.000 |
| 相关排第 1，后面跟 2 条无关 | **1.000** |
| 2 条无关在前，相关排第 3 | 0.333 |

也就是说：**唯一相关的那条只要排在第 1 位就是满分，后面跟多少条无关块都不扣分。**

本项目 `top_k=3` 的实际召回经常是「1 条相关 + 2 条无关但排序靠后」，
于是 context_precision 长期贴近 1.0。它说明的是**排序没问题**，
**不说明**「召回很干净」。想知道召回了多少垃圾要看别的口径
（比如自己统计每个块的相关性比例）。

## 3. 数据集长什么样

题目统一放在 `backend/eval_dataset.py`，检索评估和生成评估**共用同一批问题**，
否则两个分数没法互相印证。

每条用例四个字段：

```python
{
    "question": "机器人实验室周末开放吗？",
    "ground_truth": "不开放。机器人实验室只在周一至周五 08:30-18:00 开放，周末不开放。",
    "expected_source": "开放时间",   # 应命中的文档名；None 表示知识库答不了
    "category": "factual",          # factual=资料里有答案；refusal=应当拒答
}
```

当前 14 条 = 12 条事实类 + 2 条拒答类。

**为什么要专门留拒答类用例**：RAG 最危险的失败不是「答得不好」，而是
「没有依据还答得理直气壮」。用「Wi-Fi 密码是多少」「单次预约最长几小时」
这种知识库明确没覆盖的问题，才能测出模型会不会编。

## 4. 怎么跑

```powershell
cd backend
pip install -r requirements-eval.txt      # 只需装一次
.\.venv-clean\Scripts\python.exe evaluate_generation.py
```

常用参数：

```powershell
# 只跑前 3 条，改完 prompt 冒烟用（全量一次约 5 分钟）
.\.venv-clean\Scripts\python.exe evaluate_generation.py --limit 3
# 调并发（默认 3，遇到限流就调小）
.\.venv-clean\Scripts\python.exe evaluate_generation.py --concurrency 1
```

结果明细落到 `backend/eval_reports/generation.json`（已加入 `.gitignore`，
含每条的召回块、生成的答案、各项分数与异常），
**权威分数记在本篇文档里**，跑分产物不进版本库。

## 5. 实测结果

环境：`deepseek-v4-flash` + `BAAI/bge-small-zh-v1.5`，
检索 `top_k=3`，hybrid + rerank 全开，14 条用例。

同一配置**连续跑了三轮**，把三轮都列出来（原因见第 6 节，这不是排版冗余）：

| 指标 | 第 1 轮 | 第 2 轮 | 第 3 轮 |
| --- | --- | --- | --- |
| faithfulness（事实类 12） | 1.0000 | 1.0000 | 0.9659 |
| faithfulness（拒答类 2） | 0.8750 | 0.9166 | 0.7500 |
| answer_relevancy（12） | 0.8679 | 0.8554 | 0.8755 |
| context_precision（12） | 0.9861 | 0.9861 | 0.9861 |
| context_recall（12） | 1.0000 | 1.0000 | 1.0000 |

> 第 1 轮是在修正指标适用口径之前跑的（当时拒答类也算 `answer_relevancy`，
> 恒得 0，把总均值拖到 0.7439）。表里只取可对比的事实类数字。

怎么读这组数：

- **context_recall 三轮都是 1.0000**：标准答案里的信息全部被召回覆盖。
  这条最稳，因为它实际由检索结果决定，而语料小、召回全。
- **context_precision 三轮都是 0.9861**：只有一条用例掉了分，排序整体没问题。
  注意这是**看排序**的指标，不代表召回很干净（见第 2 节）。
- **faithfulness 三轮从 1.0000 滑到 0.9659**：这是最需要解释的一项。
  第 3 轮有 3 条事实类用例低于满分（0.9333 / 0.8571 / 0.8），
  **我逐条人工核对过召回块和答案，这 3 条的每一句话都确实有依据**——
  比如「设备突然坏了应该怎么处理」的回答几乎逐字来自检索到的《安全规范.md》，
  却被判 0.8。也就是说，**这些扣分是裁判的误判，不是模型的幻觉**。
- **answer_relevancy 0.8554~0.8755**：唯一稳定偏低的一项。
  抽查发现主要来自「答案里额外补充了资料出处和解释」——RAGAS 由答案反推问题时，
  这些补充内容会稀释与原问题的相似度。属于指标口径与「带引用」prompt 之间的摩擦。

**结论：**

- `context_recall` / `context_precision` 三轮**完全一致**——它们由检索结果决定，
  可复现，可以当硬指标用。
- `answer_relevancy` 的**均值**稳定（0.8554~0.8755），但用例级会抖
  （曾有用例从 0.777 掉到 0.632）。
- `faithfulness` 波动最大，同一段答案重复调用就能差 0.5，**必须当成有误差带的
  测量值来看，不能当成精确值**。

### 检索指标已经饱和（天花板效应）

同一批题目跑 `evaluate_rag.py`，三种检索策略全都满分：

```
策略：vector         Hit@1=12/12  Hit@3=12/12  MRR=1.000  nDCG@3=1.000
策略：hybrid         Hit@1=12/12  Hit@3=12/12  MRR=1.000  nDCG@3=1.000
策略：hybrid+rerank  Hit@1=12/12  Hit@3=12/12  MRR=1.000  nDCG@3=1.000
```

**这不是好事，是语料太小**：内置知识库只有 4 篇 Markdown，
而脚本按 `top_k=5` 召回，等于每次都把整个知识库捞回来，
所以「命中」几乎是必然的。**当前 4 篇文档规模下，检索策略之间没有可测量的差异。**
要真正比较 vector / hybrid / rerank，得先准备一个几十篇以上的评测语料，
并加入故意设计的关键词陷阱（同义词、专有名词、跨文档干扰）。
这是下一步该做的事，不是当前指标能回答的问题。

## 6. 怎么确认这些分数可信

分数由大模型裁判给出，所以必须验证裁判本身有没有判别力。
方法：构造已知答案的对照输入，看分数会不会朝预期方向动。

实测（同一模型同一配置）：

| 构造的输入 | 期望 | 实测 |
| --- | --- | --- |
| 上下文全相关 + 正确且有据的答案 | 高 | faithfulness = 1.000 |
| 上下文全相关 + 含编造内容的答案 | 低 | faithfulness = **0.000** |
| 全部无关的上下文 | 低 | context_precision = **0.000** |
| 1 条相关（排第一） | 高 | context_precision = 1.000 |
| 2 条无关在前、相关排第 3 | 中低 | context_precision = 0.333 |

四项全部朝预期方向动，说明指标有判别力，**分数不是包装错误造成的假分**。
反之，如果编造答案也能拿满分，那所有分数都不能信——这类「裁判自检」
应该成为评估脚本的一部分。

### 分数存在 run-to-run 波动，且比想象中大

第 5 节的三轮差异不是偶发。做一个更极端的对照：**同一个问题、同一段上下文、
一字不改的同一段答案**，只重复调用 `faithfulness.ascore()` 三次：

| 答案写法 | 三次得分 |
| --- | --- |
| 只写答案正文 | 0.75 / 1.00 / 0.50 |
| 答案正文 + 末尾「根据《安全规范.md》」 | 1.00 / 0.80 / 1.00 |

**输入完全没变，分数却能在 0.5~1.0 之间乱跳。** `temperature=0` 完全压不住，
因为 faithfulness 是「先拆句、再逐句判是否有据」的多步链路，
每一步的措辞微调都会传导到最终分数。

顺带说明：我原本怀疑是「回答要求注明出处」导致引用句被当成无据陈述，
上表专门做了对照——带引用和不带引用的分数区间重叠，**该猜想不成立**，
纯粹是裁判噪声。

**结论与操作建议**：

- 汇总均值仍有方向性意义（比如从 1.0 掉到 0.7 说明有系统性问题），
  但**单条用例的分数不要当真**，尤其不要因为一条从 1.0 掉到 0.8 就去改 prompt。
- 要比较两次改动的效果：固定数据集多跑几轮取均值，或只看
  「哪条用例从及格掉到不及格」这种结构性变化。
- **更根本的解法是把裁判换成更强的模型**。现在被测模型和裁判模型是同一个
  `deepseek-v4-flash`，让「考生自己阅卷」本身就容易不稳定。
  工程上应该用更强的模型（GPT-4 级）当裁判，被测模型随便换——
  `llm_factory` 的 client 参数独立传入，改起来只是一行。

## 7. 踩过的坑

### 7.1 ragas 0.4.3 与 langchain-community 0.4.x 不兼容（必踩）

`ragas/llms/base.py` 在模块顶层**无条件**执行：

```python
from langchain_community.chat_models.vertexai import ChatVertexAI
from langchain_community.llms import VertexAI
```

而 `langchain-community` 从 0.4.0 起把这两个模块拆去了独立包，
于是 `import ragas` 直接抛
`ModuleNotFoundError: No module named 'langchain_community.chat_models.vertexai'`。

**解法：钉 `langchain-community==0.3.31`**（见 `requirements-eval.txt`）。
它仍保留这两个模块（且是懒加载，不装 Google SDK 也能 import），
并且依赖声明是 `langchain-core>=0.3.78,<2.0.0`，
与本项目在用的 langchain-core 1.x / langgraph 1.x 兼容，**不需要降级任何现有依赖**。

不要试着把 langchain-core 降回 0.3.x 来迁就——那会把整个 LangGraph Agent 一起打回去。

### 7.2 RAGAS 默认 max_tokens=1024 会被思考 token 吃掉

`llm_factory` 默认 `max_tokens=1024`。结构化输出（instructor）加上
推理型模型的思考过程，很容易把预算耗尽，然后报：

```
instructor.v2.core.errors.IncompleteOutputException:
    The output is incomplete due to a max_tokens length limit.
```

**解法：`llm_factory(..., max_tokens=8192)`**（脚本里的 `RAGAS_MAX_TOKENS`）。

### 7.3 必须用异步客户端

`metric.ascore()` 内部走 `llm.agenerate()`，传同步的 `openai.OpenAI` 会报：

```
TypeError: Cannot use agenerate() with a synchronous client. Use generate() instead.
```

**解法：传 `openai.AsyncOpenAI`**，然后用 `asyncio.run()` 驱动。

### 7.4 嵌入模型直接复用本地的

不用接 OpenAI 的 embedding，也不用 LangChain 包装：

```python
from ragas.embeddings import HuggingFaceEmbeddings
embeddings = HuggingFaceEmbeddings(model=settings.EMBEDDING_MODEL)
```

它内部就是用 sentence-transformers 加载本地模型，
和项目检索用的是同一个 `BAAI/bge-small-zh-v1.5`，
既省一次下载，也保证评估和线上口径一致。

## 8. 与线上 Agent 的口径差异（别误读）

线上走的是 LangGraph Agent + 工具调用（`agent_service.py`），
本脚本刻意只跑「检索 → 有据作答」这一段，原因是
faithfulness / context_precision 都要求**上下文固定可复现**，
而 Agent 每轮调不调工具、调哪几个工具都可能不同，
分数抖动会掩盖真实问题。

所以本篇的分数衡量的是 **RAG 问答链路本身**，
**不包含**工具编排正确性、多轮记忆、人工审批这些 Agent 能力。
要评估 Agent 侧，需要另做一套以「工具调用轨迹」为对象的评估。

## 9. 下一步可以做什么

按性价比排序：

1. **扩充评测语料**：现在 4 篇文档让检索指标饱和，先造 30~50 篇，
   再谈 vector / hybrid / rerank 谁更好。
2. **换更强的裁判模型**（见第 6 节）：现在考生和裁判都是 `deepseek-v4-flash`，
   分数噪声很大。把裁判换成 GPT-4 级模型、给脚本加个 `--judge-model` 参数，
   是提升评估可信度性价比最高的一步。
3. **把评估接进流程**：改 prompt 或换模型后自动跑一遍，
   记录 faithfulness 有没有掉，比人工抽查可靠。
4. **评估 Agent 侧**：把工具选择准确率、参数正确率、审批触发率做成指标。
5. **降低 answer_relevancy 的口径摩擦**：把「引用来源」从答案正文里拆出去，
   或者改用 `ContextPrecisionWithoutReference` 这类不依赖反推问题的指标。
