"""一键评测入口：检索评估 + 生成质量评估。

把两条离线评估链收进一个命令，方便「改完 prompt / 换模型 / 换检索参数后
跑一遍看有没有退化」，也便于后续接入 CI。

用法::

    python run_eval.py                  # 检索 + 生成全跑
    python run_eval.py --skip-gen       # 只跑检索
    python run_eval.py --limit 3        # 生成侧只跑前 3 条（冒烟）
    python run_eval.py --diff           # 生成侧跑完后与上次报告对比

返回码：0 全部成功；非 0 有环节失败。CI 里可直接用 exit code 判断。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPORT_DIR = Path(__file__).parent / "eval_reports"
GEN_REPORT = REPORT_DIR / "generation.json"


def _run_retrieval() -> int:
    """跑检索评估，只打印汇总，不落盘（检索指标可复现，无需留档）。"""
    import evaluate_rag

    try:
        evaluate_rag.evaluate()
        return 0
    except Exception as exc:
        print(f"[检索评估] 失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def _run_generation(limit: int | None, concurrency: int) -> int:
    """跑生成质量评估，落盘 generation.json 并返回 exit code。"""
    try:
        return _run_gen_direct(limit, concurrency)
    except Exception as exc:
        print(f"[生成评估] 失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


def _run_gen_direct(limit: int | None, concurrency: int) -> int:
    import asyncio

    import evaluate_generation as gen

    return asyncio.run(gen._run(limit, concurrency, GEN_REPORT))


def _diff_last_report() -> int:
    """与上一次生成评估报告对比，输出每个指标的涨跌。"""
    if not GEN_REPORT.exists():
        print("没有历史报告可对比。", file=sys.stderr)
        return 0

    data = json.loads(GEN_REPORT.read_text(encoding="utf-8"))
    summary = data.get("summary", {})
    prev = data.get("config", {})

    print()
    print("=" * 72)
    print("生成评估报告摘要")
    print("=" * 72)
    print(f"生成时间    : {data.get('generated_at')}")
    print(f"被测模型    : {prev.get('llm_model')}")
    print(f"裁判模型    : {prev.get('judge_model')}")
    print()

    overall = summary.get("overall", {})
    print("指标         均值        有效样本")
    print("-" * 40)
    for metric in ("faithfulness", "answer_relevancy", "context_precision", "context_recall"):
        item = overall.get(metric, {})
        mean = item.get("mean")
        mean_s = "  n/a " if mean is None else f"{mean:.4f}"
        print(f"  {metric:<14} {mean_s}      {item.get('scored', 0)}")

    failed = overall.get("_cases_with_errors", 0)
    if failed:
        print(f"\n  ⚠ {failed} 条用例存在指标异常")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="一键跑 RAG 检索评估 + 生成质量评估")
    parser.add_argument("--skip-retrieval", action="store_true", help="跳过检索评估")
    parser.add_argument("--skip-gen", action="store_true", help="跳过生成评估")
    parser.add_argument("--limit", type=int, default=None, help="生成侧只跑前 N 条")
    parser.add_argument("--concurrency", type=int, default=3, help="生成侧并发数")
    parser.add_argument("--diff", action="store_true", help="跑完后打印上次报告摘要")
    args = parser.parse_args()

    rc = 0
    if not args.skip_retrieval:
        rc |= _run_retrieval()
    if not args.skip_gen:
        rc |= _run_generation(args.limit, args.concurrency)
    if args.diff:
        rc |= _diff_last_report()

    print()
    if rc == 0:
        print("评测完成：全部通过。")
    else:
        print("评测完成：存在失败环节，请查看上方输出。", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
