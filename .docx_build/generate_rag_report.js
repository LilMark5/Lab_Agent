// 生成《河北东方学院实验（训）报告》——RAG 检索增强升级
const fs = require("fs");
const {
  Document,
  Packer,
  Paragraph,
  TextRun,
  Table,
  TableRow,
  TableCell,
  WidthType,
  AlignmentType,
  ShadingType,
  VerticalAlign,
} = require("docx");

const BODY = "宋体";
const CODE = "Consolas";
const TOTAL = 9026;

function p(text, opts = {}) {
  return new Paragraph({
    alignment: opts.align || AlignmentType.LEFT,
    spacing: { line: 360, before: opts.before ?? 40, after: opts.after ?? 40 },
    indent: opts.indent ? { firstLine: 420 } : undefined,
    children: [
      new TextRun({
        text,
        font: opts.font || BODY,
        size: opts.size || 21,
        bold: !!opts.bold,
      }),
    ],
  });
}

function h(text, size = 24) {
  return new Paragraph({
    spacing: { before: 160, after: 80, line: 360 },
    children: [new TextRun({ text, font: BODY, size, bold: true })],
  });
}

function code(lines) {
  return lines.map(
    (line) =>
      new Paragraph({
        spacing: { line: 260, before: 0, after: 0 },
        shading: { type: ShadingType.CLEAR, fill: "F5F5F5" },
        indent: { left: 240 },
        children: [new TextRun({ text: line || " ", font: CODE, size: 18 })],
      })
  );
}

function cell(text, width, opts = {}) {
  const children = Array.isArray(text)
    ? text
    : [
        new Paragraph({
          alignment: opts.align || AlignmentType.LEFT,
          children: [
            new TextRun({
              text,
              font: opts.font || BODY,
              size: opts.size || 21,
              bold: !!opts.bold,
            }),
          ],
        }),
      ];
  return new TableCell({
    width: { size: width, type: WidthType.DXA },
    columnSpan: opts.span,
    verticalAlign: VerticalAlign.CENTER,
    shading: opts.fill ? { type: ShadingType.CLEAR, fill: opts.fill } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children,
  });
}

const W1 = 1500;
const W2 = 3013;
const W3 = 1500;
const W4 = 3013;

const infoTable = new Table({
  width: { size: TOTAL, type: WidthType.DXA },
  columnWidths: [W1, W2, W3, W4],
  rows: [
    new TableRow({
      children: [
        cell("学院", W1, { bold: true, fill: "F2F2F2" }),
        cell("人工智能学院", W2),
        cell("专业", W3, { bold: true, fill: "F2F2F2" }),
        cell("软件工程", W4),
      ],
    }),
    new TableRow({
      children: [
        cell("班级", W1, { bold: true, fill: "F2F2F2" }),
        cell("23-1", W2),
        cell("学号", W3, { bold: true, fill: "F2F2F2" }),
        cell("235150201019", W4),
      ],
    }),
    new TableRow({
      children: [
        cell("姓名", W1, { bold: true, fill: "F2F2F2" }),
        cell("马凯", W2),
        cell("指导教师", W3, { bold: true, fill: "F2F2F2" }),
        cell("刘建国", W4),
      ],
    }),
    new TableRow({
      children: [
        cell("课程名称", W1, { bold: true, fill: "F2F2F2" }),
        cell("智能体开发实践", W2),
        cell("实验/训名称", W3, { bold: true, fill: "F2F2F2" }),
        cell("基于 RAG 检索增强升级", W4),
      ],
    }),
    new TableRow({
      children: [
        cell("实验/训目的", W1, { bold: true, fill: "F2F2F2" }),
        cell(
          [
            p("1. 理解检索增强生成（RAG）的基本架构，区分原生大模型生成和检索增强生成的区别。", { size: 21 }),
            p("2. 掌握文档分块、文本向量化、向量库存储、语义检索、提示词组装、大模型生成的完整链路。", { size: 21 }),
            p("3. 验证 RAG 可以降低大模型幻觉，让模型基于私有文档给出回答，而不只是依赖预训练知识。", { size: 21 }),
            p("4. 观察分块大小、检索数量 top-k 对问答效果的影响。", { size: 21 }),
          ],
          W2 + W3 + W4,
          { span: 3 }
        ),
      ],
    }),
    new TableRow({
      children: [
        cell("实验/训设施/器材", W1, { bold: true, fill: "F2F2F2" }),
        cell(
          [
            p("1. 计算机（Windows 10/11，16GB 内存以上）；", { size: 21 }),
            p("2. PyCharm / VS Code、Python 3.11；", { size: 21 }),
            p("3. ChromaDB / Milvus（Milvus Lite）、Redis（可选）。", { size: 21 }),
          ],
          W2 + W3 + W4,
          { span: 3 }
        ),
      ],
    }),
    new TableRow({
      children: [
        cell("实验/训内容、步骤、分析及总结", TOTAL, {
          span: 4,
          bold: true,
          fill: "F2F2F2",
        }),
      ],
    }),
    new TableRow({
      children: [
        cell(
          [
            h("一、实验内容"),
            p("本实验在智能实验室预约系统上完成 RAG（检索增强生成）升级。此前 AI 助手只能依赖大模型自身的预训练知识，问“计算机实验室几点开门”“设备损坏怎么办”时会编造答案；接入 RAG 后，助手先从本地知识库检索资料，再依据资料回答。", { indent: true }),
            p("知识库位于 backend/data/kb，共四篇 Markdown：预约规则、开放时间、安全规范、设备使用说明。向量模型使用本地 BAAI/bge-small-zh-v1.5，向量库支持 ChromaDB 与 Milvus（Milvus Lite）双后端，检索环节在向量召回之外增加了 BM25 关键词召回、RRF 融合与 bge-reranker 重排，并用 Redis 缓存相似问题。", { indent: true }),
            p("本次实验重点验证四件事：分块策略、向量化与入库、检索质量（含 top-k 影响）、以及 RAG 对降低幻觉的实际效果。", { indent: true }),

            h("二、实验目的"),
            p("1. 理解 RAG 的“检索 + 增强 + 生成”三段式架构，明确它与原生大模型生成的本质区别：原生生成只依赖训练时记住的知识，RAG 则在生成前动态注入外部文档。", { indent: true }),
            p("2. 动手实现完整链路：文档分块 → 文本向量化 → 向量库存储 → 语义检索 → 提示词组装 → 大模型生成。", { indent: true }),
            p("3. 通过对照实验验证 RAG 降低幻觉：同一个问题，无资料时模型可能编造时间，有资料时能给出知识库中的准确时间。", { indent: true }),
            p("4. 调整分块大小与 top-k，观察它们对检索命中率和回答准确率的影响，理解检索参数不是越大越好。", { indent: true }),

            h("三、实验步骤"),
            p("步骤 1：准备知识库。在 backend/data/kb 下建立 4 篇 Markdown，一篇文档作为一个知识片段，例如：", { indent: true }),
            ...code([
              "# 实验室开放时间",
              "- 计算机实验室：周一至周五 08:00-21:00，周末 09:00-17:00",
              "- 化学实验室：周一至周五 08:30-18:00，周末不开放",
              "开放时间内仍需先预约并审核通过，不能直接进入。",
            ]),
            p("分块策略说明：本项目文档很短，采用“一篇文档即一个 chunk”，不强行切分；如果文档很长，应按语义段落切分并保留一定 overlap，避免把一句话切断。", { indent: true }),
            p("步骤 2：文本向量化。使用 sentence-transformers 加载 bge-small-zh-v1.5，把文档和问题映射成同一向量空间中的向量：", { indent: true }),
            ...code([
              "from sentence_transformers import SentenceTransformer",
              "model = SentenceTransformer(\"BAAI/bge-small-zh-v1.5\")",
              "doc_vecs = model.encode(docs, normalize_embeddings=True)",
              "query_vec = model.encode(query, normalize_embeddings=True)",
            ]),
            p("说明：归一化后向量点积等于余弦相似度，值越接近 1 表示语义越相近。", { indent: true }),
            p("步骤 3：向量库存储。以 Milvus Lite 为例，定义主键、向量列、原文列，建立索引后写入文档：", { indent: true }),
            ...code([
              "schema.add_field(\"pk\", DataType.VARCHAR, is_primary=True, max_length=128)",
              "schema.add_field(\"embedding\", DataType.FLOAT_VECTOR, dim=384)",
              "schema.add_field(\"text\", DataType.VARCHAR, max_length=8192)",
              "index_params.add_index(field_name=\"embedding\", index_type=\"FLAT\", metric_type=\"COSINE\")",
              "client.create_collection(collection_name=\"lab_kb\", schema=schema, index_params=index_params)",
              "client.upsert(collection_name=\"lab_kb\", data=rows)",
            ]),
            p("步骤 4：混合检索。只做向量检索容易漏掉精确词，只做关键词检索又不理解同义改写，因此两路都召回，再用 RRF 按名次融合，最后用交叉编码器重排：", { indent: true }),
            ...code([
              "vector_hits = vector_store.search(query, top_k=5)   # 语义召回",
              "keyword_hits = bm25_search(query, top_k=5)          # 关键词召回",
              "merged = rrf_fusion(vector_hits, keyword_hits)      # 按名次融合",
              "merged = rerank(query, merged)                      # 交叉编码器精排",
            ]),
            p("步骤 5：提示词组装与生成。把检索到的资料拼进 system 提示，并明确约束模型“依据资料回答、不要编造”：", { indent: true }),
            ...code([
              "system_prompt = SYSTEM_PROMPT + \"\\n\\n以下是检索到的实验室资料：\\n\" + knowledge",
              "res = client.chat.completions.create(",
              "    model=settings.LLM_MODEL,",
              "    messages=[{\"role\": \"system\", \"content\": system_prompt}, *history],",
              ")",
            ]),
            p("步骤 6：检索评估。编写 evaluate_rag.py，对标注好的问题计算 hit@2，并对比纯向量召回与混合召回：", { indent: true }),
            ...code([
              "for question, expected in LABELED_CASES:",
              "    hits = hybrid_search(question, top_k=3)",
              "    hit = expected in [source_of(h) for h in hits[:2]]",
              "    print(question, \"hit@2=\", hit)",
            ]),
            p("步骤 7：启动与验证。重启后端后依次验证：问“计算机实验室几点开门”应答出 08:00-21:00；问“设备损坏怎么办”应答立即停用并联系管理员；问“预约之后可以取消吗”应区分待审核与已通过。修改知识库文档后需删除 data/chroma（或重建 Milvus 集合）再重启，否则仍是旧向量。", { indent: true }),

            h("四、实验分析"),
            p("1. 原生生成与 RAG 的对照。未接入 RAG 时，问“计算机实验室几点开门”，模型会给出一个看似合理但没有依据的时间；接入 RAG 后，检索命中了“开放时间.md”，回答与文档一致。这验证了 RAG 的作用：把“模型记忆”变成“有出处的回答”。", { indent: true }),
            p("2. 分块大小的影响。本项目文档只有几条规则，整篇作为一个 chunk 就能完整保留语义；如果按固定字数硬切，可能把“开放时间”和“注意事项”拆散，检索到一半信息反而答错。结论是：分块要跟随文档语义结构，太小会丢上下文，太大会引入噪声并占用上下文窗口。", { indent: true }),
            p("3. top-k 的影响。top-k 太小（如 top-1）时，一旦第一名不是目标文档就会答错；本项目取 top-5 召回再用 rerank 精排，最终只把 top-2 拼进提示词，兼顾召回率和上下文长度。top-k 一味增大也会把无关文档带进来，干扰模型判断。", { indent: true }),
            p("4. 混合检索的价值。向量检索解决“开放时间”与“几点开门”这种语义相近但用词不同的情况；BM25 解决“bge”“MCP”这类专有名词的精确匹配；RRF 只看名次、不依赖两路分数尺度，融合更稳定；rerank 用交叉编码器对“问题+文档”成对打分，进一步把真正相关的文档排到前面。", { indent: true }),
            p("5. 降低幻觉的机制。RAG 从两个方向降低幻觉：一是把私有资料作为证据注入上下文，二是用提示词约束模型“只依据资料回答、资料没有就说明查不到”。在本项目中，问实时空位时模型会提示去“实验室列表”查看，而不是编造一个空闲实验室。", { indent: true }),
            p("6. 遇到的问题与解决。其一，首次运行需要下载向量模型，国内直连 HuggingFace 很慢或失败，配置 HF_ENDPOINT=https://hf-mirror.com 后解决；其二，修改知识库后旧答案不变，原因是向量库没有重建，删除 data/chroma 或重建 Milvus 集合后恢复；其三，pymilvus 会读取同名环境变量 MILVUS_URI，与本地 Milvus Lite 的文件路径冲突，改名为 MILVUS_LOCAL_URI 后解决；其四，虚拟环境中混入 Python 3.14 的二进制包，导致 numpy、pydantic_core 导入失败，重建干净的 Python 3.11 环境后解决。", { indent: true }),
            p("7. 测试结果。知识库 4 篇文档、4 条标注问题，评估脚本输出 hit@2 结果；实际问答中“开放时间”“安全规范”“取消规则”均能引用对应文档回答，说明检索链路有效。", { indent: true }),

            h("五、实验总结"),
            p("通过本次实验，我完整走通了 RAG 的六个环节：文档分块、文本向量化、向量库存储、语义检索、提示词组装、大模型生成，并在此基础上增加了 BM25、RRF 与 rerank，形成混合检索方案。", { indent: true }),
            p("最大的体会是：RAG 的效果不取决于“用了哪个向量库”，而取决于检索质量。分块策略、top-k、是否混合检索、是否重排，都会直接影响最终回答。工程上还要考虑知识库更新、缓存失效、评估指标和成本控制。", { indent: true }),
            p("后续可以继续完善：支持文档增量更新与向量库热更新；引入查询改写与多路召回；用 RAGAS 等框架补充 faithfulness、recall 等指标；接入 Langfuse 追踪每次检索与生成；以及把知识库管理做成后台，方便非技术人员维护。", { indent: true }),
          ],
          TOTAL,
          { span: 4 }
        ),
      ],
    }),
    new TableRow({
      children: [
        cell("教师评阅意见", W1 + W3, { span: 2, bold: true, fill: "F2F2F2" }),
        cell("", W2 + W4, { span: 2 }),
      ],
    }),
    new TableRow({
      children: [
        cell("实验/训成绩（百分制）", W1 + W3, { span: 2, bold: true, fill: "F2F2F2" }),
        cell("指导教师签字：", W2 + W4, { span: 2 }),
      ],
    }),
  ],
});

const doc = new Document({
  styles: {
    default: { document: { run: { font: BODY, size: 21 } } },
  },
  sections: [
    {
      properties: {
        page: { margin: { top: 1000, bottom: 1000, left: 1100, right: 1100 } },
      },
      children: [
        new Paragraph({
          alignment: AlignmentType.CENTER,
          spacing: { after: 80 },
          children: [
            new TextRun({
              text: "河北东方学院实验（训）报告",
              font: BODY,
              size: 28,
              bold: true,
            }),
          ],
        }),
        new Paragraph({
          spacing: { after: 120 },
          children: [
            new TextRun({
              text: "实验/训地点：A-402        日期：2026年10月15日",
              font: BODY,
              size: 21,
            }),
          ],
        }),
        infoTable,
      ],
    },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  const out = process.argv[2] || "rag-report.docx";
  fs.writeFileSync(out, buf);
  console.log("written:", out, buf.length, "bytes");
});
