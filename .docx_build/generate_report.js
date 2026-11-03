// 生成《河北东方学院实验（训）报告》Word 文档
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
  BorderStyle,
  ShadingType,
  VerticalAlign,
} = require("docx");

const BODY = "宋体";
const CODE = "Consolas";
const TOTAL = 9026;

// 普通正文段落
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
        color: opts.color || "000000",
      }),
    ],
  });
}

// 标题段落
function h(text, size = 24) {
  return new Paragraph({
    spacing: { before: 160, after: 80, line: 360 },
    children: [
      new TextRun({ text, font: BODY, size, bold: true }),
    ],
  });
}

// 代码块：每行一个 Paragraph，使用等宽字体
function code(lines) {
  return lines.map(
    (line) =>
      new Paragraph({
        spacing: { line: 260, before: 0, after: 0 },
        shading: { type: ShadingType.CLEAR, fill: "F5F5F5" },
        indent: { left: 240 },
        children: [
          new TextRun({
            text: line || " ",
            font: CODE,
            size: 18,
          }),
        ],
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
    shading: opts.fill
      ? { type: ShadingType.CLEAR, fill: opts.fill }
      : undefined,
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
        cell("基于 LangChain/LangGraph 的智能实验室预约 Agent 开发", W4),
      ],
    }),
    new TableRow({
      children: [
        cell("实验/训目的", W1, { bold: true, fill: "F2F2F2" }),
        cell(
          [
            p("1. 理解原生调用大模型 API 与基于 LangChain 框架开发 LLM 应用的区别，掌握其组件化、流水线式设计理念。", { size: 21 }),
            p("2. 掌握 LangChain 核心组件：模型（Models）、提示（Prompts）、输出解析器、记忆、链、工具与智能体。", { size: 21 }),
            p("3. 掌握基于 LangGraph 的 ReAct Agent 编排方法，理解状态（State）、节点（Node）、边（Edge）与工具循环。", { size: 21 }),
            p("4. 掌握 RAG 检索增强、Tool Calling、MCP 工具协议与 SSE 流式输出在真实项目中的落地方式。", { size: 21 }),
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
            p("2. PyCharm / VS Code、Python 3.11、Node.js 18；", { size: 21 }),
            p("3. MySQL/PostgreSQL、Redis、Docker（可选）。", { size: 21 }),
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
            // 一、实验内容
            h("一、实验内容"),
            p("本实验以“智能实验室预约系统”为载体，完成从传统业务系统到 AI Agent 应用的升级。系统包含学生与管理员两类角色，业务闭环为：登录 → 查看实验室与设备 → 提交预约 → 管理员审核 → 学生查看或取消预约。", { indent: true }),
            p("在业务系统之上叠加 AI 能力，采用 LangChain + LangGraph 构建可解释的 Agent：模型自主决定是否调用工具，工具复用后端已有的业务 Service，实现“查知识库、查数据库、写预约”三类能力。", { indent: true }),
            p("项目技术栈：前端 Vue3 + Vite + Element Plus；后端 Python + FastAPI + SQLAlchemy；数据库 SQLite/PostgreSQL；缓存 Redis；向量库 ChromaDB/Milvus；AI 部分使用 LangChain、LangGraph、RAG（混合检索 + rerank）、Tool Calling、MCP 与 SSE。", { indent: true }),
            p("本次实验重点抽取项目中的“最小骨架”：工具定义、LangGraph ReAct 图、RAG 检索与 SSE 流式输出，理解每个环节的输入输出与职责边界。", { indent: true }),

            // 二、实验目的
            h("二、实验目的"),
            p("1. 理解 LangChain 不是大模型，而是应用编排中间件：模型负责生成，LangChain 负责把提示、工具、检索、记忆组织成可复用流程。", { indent: true }),
            p("2. 掌握 Tool Calling 机制：模型只输出“调用哪个函数、传什么参数”，真正执行函数的是后端代码。", { indent: true }),
            p("3. 掌握 LangGraph 的 State/Node/Edge 模型，能够用条件边实现 ReAct 的“思考—行动—观察”循环。", { indent: true }),
            p("4. 掌握 RAG 的向量召回、关键词召回、RRF 融合与 rerank 精排，理解混合检索为何比单一检索稳定。", { indent: true }),
            p("5. 掌握 SSE 流式输出，让前端实时看到 Agent 的思考与工具调用过程。", { indent: true }),

            // 三、实验步骤
            h("三、实验步骤"),
            p("步骤 1：环境准备。使用 Python 3.11 创建虚拟环境，安装 FastAPI、LangChain、LangGraph、ChromaDB、sentence-transformers、MCP 等依赖，并在 .env 中配置大模型密钥与向量模型镜像。", { indent: true }),
            p("步骤 2：定义工具（最小骨架）。使用 LangChain 的 @tool 装饰器，把业务函数暴露给模型，docstring 会自动生成工具的 JSON Schema：", { indent: true }),
            ...code([
              "from langchain_core.tools import tool",
              "",
              "@tool",
              "def list_open_labs(keywords: str = \"\") -> str:",
              "    \"\"\"查询当前开放中的实验室列表。\"\"\"",
              "    return json.dumps(query_labs(keywords), ensure_ascii=False)",
            ]),
            p("步骤 3：构建 LangGraph ReAct Agent。用 StateGraph 把“调模型”和“执行工具”两个节点连成循环，由条件边判断是否还需要调用工具：", { indent: true }),
            ...code([
              "llm = ChatOpenAI(model=..., temperature=0, streaming=True).bind_tools(tools)",
              "",
              "def agent_node(state):",
              "    return {\"messages\": [llm.invoke(state[\"messages\"])]}",
              "",
              "graph = StateGraph(MessagesState)",
              "graph.add_node(\"agent\", agent_node)",
              "graph.add_node(\"tools\", ToolNode(tools))",
              "graph.add_edge(START, \"agent\")",
              "graph.add_conditional_edges(\"agent\", tools_condition)",
              "graph.add_edge(\"tools\", \"agent\")",
              "agent = graph.compile()",
            ]),
            p("步骤 4：接入 RAG 混合检索。先把知识库文档向量化，检索时同时做向量召回与 BM25 关键词召回，用 RRF 融合排序，再用交叉编码器 rerank：", { indent: true }),
            ...code([
              "vector_hits = vector_store.search(query, top_k=5)   # 语义召回",
              "keyword_hits = bm25_search(query, top_k=5)          # 关键词召回",
              "merged = rrf_fusion(vector_hits, keyword_hits)      # RRF 融合",
              "merged = rerank(query, merged)                      # 精排",
              "context = \"\\n\\n\".join(hit[\"doc\"] for hit in merged[:2])",
            ]),
            p("步骤 5：接入 MCP。把实验室查询能力封装成独立 MCP Server，Agent 通过适配器加载标准工具，实现工具与业务解耦。", { indent: true }),
            p("步骤 6：SSE 流式输出。LangGraph 执行时监听内部事件，把工具开始/结束与模型逐字输出转成 SSE 帧推给前端：", { indent: true }),
            ...code([
              "async for event in agent.astream_events(inputs, version=\"v2\"):",
              "    if event[\"event\"] == \"on_tool_start\":",
              "        yield sse({\"type\": \"tool_start\", \"name\": event[\"name\"]})",
              "    elif event[\"event\"] == \"on_chat_model_stream\":",
              "        yield sse({\"type\": \"token\", \"content\": chunk_text(event)})",
            ]),
            p("步骤 7：启动与验证。后端执行 uvicorn app.main:app 启动，前端 npm run dev 启动，使用 admin/123456 登录，依次验证：登录、实验室列表、预约提交、AI 助手对话、Agent 预约确认。", { indent: true }),

            // 四、实验分析
            h("四、实验分析"),
            p("1. 分层设计的价值。后端 api 层只接收参数与鉴权，service 层承载业务规则，model 层对应数据库表，schema 层定义接口契约。AI 工具直接复用 service，因此普通接口与 Agent 落库走的是同一套校验逻辑，避免“两套实现”。", { indent: true }),
            p("2. Tool Calling 的职责边界。模型不执行函数，只输出 tool_calls；后端执行后把结果以 role=tool 塞回消息。这样既发挥了模型的理解能力，又保证写数据库等敏感操作始终由受控代码完成。", { indent: true }),
            p("3. 为什么使用混合检索。向量检索擅长语义相近但用词不同的情况，BM25 擅长精确词与专有名词；RRF 只看名次、不依赖分数尺度，融合稳定；rerank 用交叉编码器对“问题+文档”成对精排，进一步提升准确率。", { indent: true }),
            p("4. 为什么限制工具轮数。Agent 可能反复调用工具造成死循环，因此设置 recursion_limit，并让工具内部捕获异常返回结构化 JSON，保证单次工具失败不会中断整个对话。", { indent: true }),
            p("5. 遇到的主要问题与解决。其一，新版 LangGraph 移除了 stream_events(version=\"v2\")，流式接口报“大模型调用失败”，改用 astream_events 后恢复正常；其二，虚拟环境中混入了 Python 3.14 的二进制包（pydantic_core、uuid_utils、numpy 等），与 Python 3.11 不兼容，重建干净的 3.11 虚拟环境后解决；其三，pymilvus 会读取同名环境变量 MILVUS_URI，与本地 Milvus Lite 的文件路径冲突，改名为 MILVUS_LOCAL_URI 后解决。", { indent: true }),
            p("6. 测试结果。登录、用户/实验室/设备/预约列表接口均返回 200；AI 助手普通对话、SSE 流式输出、工具调用查询真实实验室数据均正常；预约流程需用户确认后才落库，符合安全设计要求。", { indent: true }),

            // 五、实验总结
            h("五、实验总结"),
            p("通过本次实验，我完成了从传统业务系统到 AI Agent 应用的完整串联：以 FastAPI 分层业务为底座，用 LangChain 定义工具，用 LangGraph 编排 ReAct 循环，用 RAG 补充领域知识，用 MCP 标准化工具接口，用 Redis 做限流与缓存，最后用 SSE 把 Agent 的执行过程实时呈现给用户。", { indent: true }),
            p("最大的收获是理解了“模型负责决策，代码负责执行”的分工，以及工程化的重要性：可评估、可追踪、可回滚、可控制成本。后续可以继续完善的方向包括：增加 RAG 评估指标与 Langfuse 追踪、为 Agent 增加人工审批节点、支持多 Agent 协作，以及使用 Alembic 做数据库迁移、补充自动化测试。", { indent: true }),
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
    default: {
      document: {
        run: { font: BODY, size: 21 },
      },
    },
  },
  sections: [
    {
      properties: {
        page: {
          margin: { top: 1000, bottom: 1000, left: 1100, right: 1100 },
        },
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
  const out = process.argv[2] || "report.docx";
  fs.writeFileSync(out, buf);
  console.log("written:", out, buf.length, "bytes");
});
