"""RAG 生成质量离线评估（RAGAS）。

姊妹脚本 ``evaluate_rag.py`` 只测检索侧（Hit@K / MRR / nDCG），本脚本补上答案侧：

- **faithfulness**：答案里的每句话是否都能在召回的上下文里找到依据（抗幻觉）。
- **answer_relevancy**：答案是否正面回答了问题，而不是答非所问。
- **context_precision**：有用的召回内容有没有排到前面。注意它算的是 average
  precision，看**排序**不看比例——唯一相关的那条只要排第 1 就是满分，
  后面跟多少条无关块都不扣分（需要 reference）。
- **context_recall**：标准答案里的信息有多少被召回覆盖（需要 reference）。

链路：``kb_service.retrieve`` 召回块 → 按父上下文窗口展开成 ``contexts``
→ 用项目同一个大模型生成答案 → 交给 RAGAS 打分。

与线上 Agent 的差异（重要，别误读分数）
------------------------------------
线上走的是 LangGraph Agent + 工具调用，这里刻意只跑「检索 → 有据作答」这一段。
原因是 RAGAS 的 faithfulness / context_precision 都要求上下文固定可复现，
而 Agent 的工具调用路径每轮都可能不同，分数抖动会掩盖真实问题。
所以本脚本衡量的是 **RAG 问答链路本身**，不含工具编排、多轮记忆与人工审批。

哪些指标算哪些用例
------------------
见 ``METRIC_CATEGORIES``：不同指标的前提条件不一样，硬套会把汇总分数带偏。

用法::

    python evaluate_generation.py                # 全量
    python evaluate_generation.py --limit 3      # 只跑前 3 条，冒烟用
    python evaluate_generation.py --out my.json  # 指定结果落盘路径
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from openai import AsyncOpenAI

from app.config import settings
from app.services import kb_service
from eval_dataset import CASES

# 与 agent_service.SYSTEM_PROMPT 的「引用要求」保持一致：
# 只依据资料作答、资料不足要直说、回答注明来源文件名。
# 这里不抄整段 prompt，是因为线上那段还要讲工具调用规则，跟本脚本无关。
RAG_SYSTEM_PROMPT = """你是智能实验室预约系统的助手，回答要简洁。
只依据下面提供的实验室资料回答，不要编造资料里没有的信息。
如果资料里没有相关内容，直接说明「资料里没有相关内容」，不要给出猜测。
回答时注明依据的文件名，例如「根据《开放时间.md》」。
"""

# RAGAS 结构性输出默认只给 1024 token，deepseek-v4-flash 的思考过程会先把预算吃掉，
# 导致 JSON 被截断并抛 IncompleteOutputException，所以显式调高。
RAGAS_MAX_TOKENS = 8192

# 逐条打印进度用。
_done = 0
_total = 0


# 每个指标适用的用例类别。不同指标的前提条件不一样，硬套会把汇总分数带偏：
#
# - context_precision / context_recall 需要 reference，只对 factual 有意义。
#   拒答用例的标准答案本身就是「资料里没有」，拿它去算召回覆盖毫无意义。
# - answer_relevancy 的算法是「由答案反推问题，再和原问题比嵌入相似度」。
#   拒答答案反推出来的问题是「资料里有什么」，和「Wi-Fi 密码是多少」
#   相似度必然接近 0——实测拒答类恒为 0.000，是机制导致的假低分，
#   不是模型答错了。所以拒答类不算这个指标。
# - faithfulness 只依赖「答案 vs 上下文」，任何类别都适用，
#   也是拒答用例唯一有意义的指标（考的就是有没有编造）。
METRIC_CATEGORIES = {
    "faithfulness": {"factual", "refusal"},
    "answer_relevancy": {"factual"},
    "context_precision": {"factual"},
    "context_recall": {"factual"},
}


def _retrieve_contexts(question: str) -> list[str]:
    """召回并展开父上下文，返回与送入模型完全一致的上下文块列表。"""
    top_k = settings.FINAL_CONTEXT_K
    hits = kb_service.retrieve(question, top_k=top_k)
    contexts: list[str] = []
    for hit in hits:
        meta = hit.get("meta") or {}
        source = meta.get("source") or "未知来源"
        chunk_index = meta.get("chunk_index")
        body = kb_service._expand_context(hit)
        contexts.append(f"[{source}#{chunk_index}]\n{body}")
    return contexts


async def _generate_answer(
    client: AsyncOpenAI, question: str, contexts: list[str]
) -> str:
    """走「有据作答」这条路：把召回内容拼进 prompt，让模型按资料回答。"""
    if contexts:
        material = "\n\n".join(contexts)
    else:
        material = "（本次没有检索到任何资料）"
    user_prompt = f"以下是检索到的实验室资料：\n{material}\n\n问题：{question}"

    response = await client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[
            {"role": "system", "content": RAG_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        max_tokens=1024,
    )
    return (response.choices[0].message.content or "").strip()


def _metric_call(name: str, metric, case: dict, answer: str, contexts: list[str]):
    """按指标名字组装这一次打分调用（各指标的入参并不一样）。"""
    question = case["question"]
    if name == "faithfulness":
        return metric.ascore(
            user_input=question, response=answer, retrieved_contexts=contexts
        )
    if name == "answer_relevancy":
        return metric.ascore(user_input=question, response=answer)
    if name == "context_precision":
        return metric.ascore(
            user_input=question,
            reference=case["ground_truth"],
            retrieved_contexts=contexts,
        )
    if name == "context_recall":
        return metric.ascore(
            user_input=question,
            retrieved_contexts=contexts,
            reference=case["ground_truth"],
        )
    raise KeyError(f"未实现的指标：{name}")


async def _score_case(metrics: dict, case: dict, answer: str, contexts: list[str]) -> dict:
    """对一个用例跑全部适用指标；单个指标失败不影响其它指标。"""
    applicable = [
        name
        for name in METRIC_ORDER
        if case["category"] in METRIC_CATEGORIES[name]
    ]
    calls = {
        name: _metric_call(name, metrics[name], case, answer, contexts)
        for name in applicable
    }

    results = await asyncio.gather(*calls.values(), return_exceptions=True)

    scores: dict[str, float] = {}
    errors: dict[str, str] = {}
    for name, result in zip(calls.keys(), results):
        if isinstance(result, BaseException):
            errors[name] = f"{type(result).__name__}: {result}"
        else:
            scores[name] = round(float(result.value), 4)
    return {"scores": scores, "errors": errors}


async def _run_case(
    client: AsyncOpenAI, metrics: dict, case: dict, sem: asyncio.Semaphore
) -> dict:
    async with sem:
        contexts = _retrieve_contexts(case["question"])
        if not contexts:
            _report_progress(case, {})
            return {
                "question": case["question"],
                "category": case["category"],
                "ground_truth": case["ground_truth"],
                "contexts": [],
                "answer": "",
                "scores": {},
                "errors": {"retrieval": "没有召回到任何块，跳过打分"},
            }

        answer = await _generate_answer(client, case["question"], contexts)
        scored = await _score_case(metrics, case, answer, contexts)
        _report_progress(case, scored["scores"])

        return {
            "question": case["question"],
            "category": case["category"],
            "ground_truth": case["ground_truth"],
            "contexts": contexts,
            "answer": answer,
            **scored,
        }


def _report_progress(case: dict, scores: dict) -> None:
    global _done
    _done += 1
    flag = "拒答" if case["category"] == "refusal" else "事实"
    if scores:
        detail = "  ".join(f"{name}={value:.3f}" for name, value in scores.items())
    else:
        detail = "（无分数）"
    print(f"  [{_done:>2}/{_total}] ({flag}) {case['question']}")
    print(f"        {detail}")


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


METRIC_ORDER = [
    "faithfulness",
    "answer_relevancy",
    "context_precision",
    "context_recall",
]


def _summarize(cases: list[dict], only_category: str | None = None) -> dict:
    selected = [
        c for c in cases if only_category is None or c["category"] == only_category
    ]
    summary: dict[str, dict] = {}
    for metric in METRIC_ORDER:
        values = [c["scores"][metric] for c in selected if metric in c.get("scores", {})]
        summary[metric] = {"mean": _mean(values), "scored": len(values)}
    summary["_cases"] = len(selected)
    failed = sum(1 for c in cases if c.get("errors"))
    summary["_cases_with_errors"] = failed
    return summary


def _print_summary(summary: dict, title: str) -> None:
    print()
    print("-" * 72)
    print(f"{title}（共 {summary['_cases']} 条）")
    print("-" * 72)
    for metric in METRIC_ORDER:
        item = summary[metric]
        mean = "  n/a " if item["mean"] is None else f"{item['mean']:.4f}"
        print(f"  {metric:<20} {mean}   （有效样本 {item['scored']}）")
    if summary["_cases_with_errors"]:
        print(f"  ⚠ {summary['_cases_with_errors']} 条用例存在指标异常，见结果文件")


async def _run(limit: int | None, concurrency: int, out_path: Path) -> int:
    global _total

    if not settings.LLM_API_KEY:
        print("未配置 LLM_API_KEY，无法评估生成质量。请先填 backend/.env。", file=sys.stderr)
        return 2

    cases = CASES[:limit] if limit else CASES
    _total = len(cases)

    print("=" * 72)
    print("RAG 生成质量评估（RAGAS）")
    print("=" * 72)
    print(f"模型        : {settings.LLM_MODEL} @ {settings.LLM_BASE_URL}")
    print(f"嵌入模型    : {settings.EMBEDDING_MODEL}")
    print(
        f"检索配置    : top_k={settings.FINAL_CONTEXT_K}  "
        f"hybrid={settings.HYBRID_SEARCH_ENABLED}  rerank={settings.RERANK_ENABLED}"
    )
    print(f"用例数      : {_total}   并发: {concurrency}")
    print()

    # 这里的 import 故意放在函数内：ragas 及其依赖（datasets / pyarrow 等）
    # 只想在真正跑评估时加载，不影响其它脚本的启动速度。
    from ragas.embeddings import HuggingFaceEmbeddings
    from ragas.llms import llm_factory
    from ragas.metrics.collections import (
        AnswerRelevancy,
        ContextPrecisionWithReference,
        ContextRecall,
        Faithfulness,
    )

    client = AsyncOpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
    llm = llm_factory(
        settings.LLM_MODEL,
        client=client,
        max_tokens=RAGAS_MAX_TOKENS,
        temperature=0,
    )
    embeddings = HuggingFaceEmbeddings(model=settings.EMBEDDING_MODEL)

    metrics = {
        "faithfulness": Faithfulness(llm=llm),
        "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=embeddings),
        "context_precision": ContextPrecisionWithReference(llm=llm),
        "context_recall": ContextRecall(llm=llm),
    }

    sem = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(
        *(_run_case(client, metrics, case, sem) for case in cases)
    )

    overall = _summarize(results)
    factual = _summarize(results, "factual")
    refusal = _summarize(results, "refusal")

    _print_summary(overall, "汇总：全部用例")
    _print_summary(factual, "汇总：事实类用例")
    if any(c["category"] == "refusal" for c in results):
        applies = "/".join(
            name for name in METRIC_ORDER if "refusal" in METRIC_CATEGORIES[name]
        )
        _print_summary(refusal, f"汇总：拒答类用例（只算 {applies}）")

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "config": {
            "llm_model": settings.LLM_MODEL,
            "llm_base_url": settings.LLM_BASE_URL,
            "embedding_model": settings.EMBEDDING_MODEL,
            "retrieval_top_k": settings.FINAL_CONTEXT_K,
            "hybrid_search": settings.HYBRID_SEARCH_ENABLED,
            "rerank": settings.RERANK_ENABLED,
            "ragas_max_tokens": RAGAS_MAX_TOKENS,
        },
        "summary": {
            "overall": overall,
            "factual": factual,
            "refusal": refusal,
        },
        "cases": results,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print()
    print(f"明细已写入：{out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG 生成质量离线评估（RAGAS）")
    parser.add_argument(
        "--limit", type=int, default=None, help="只跑前 N 条用例，用于冒烟"
    )
    parser.add_argument(
        "--concurrency", type=int, default=3, help="并发用例数，默认 3"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent / "eval_reports" / "generation.json",
        help="评估结果 JSON 落盘路径",
    )
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args.limit, args.concurrency, args.out))
    except KeyboardInterrupt:
        print("\n已中断。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
