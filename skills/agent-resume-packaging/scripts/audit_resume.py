#!/usr/bin/env python3
# skills/agent-resume-packaging/scripts/audit_resume.py
"""简历反假审计：把「这份简历我看着就不行」拆成可执行规则，逐行给出问题、依据和改法。

零依赖，只用标准库，方便在任何机器上跑：
    python3 scripts/audit_resume.py resume.md --ledger ledger.json
    python3 scripts/audit_resume.py resume.md --mode final --json

设计原则：
1. 只做确定性判断（有没有证据标记、状态是不是待确认、有没有内部私名），不做「写得好不好」的主观评分；
2. 发现问题的同时给出改写方向，让模型/人都知道下一步动作；
3. 有 error 时退出码为 1，可以直接当投递前的门禁。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"

# 证据标记：每个强主张/指标后面挂一个账本条目 id
EVIDENCE_MARKER = re.compile(r"【证据：\s*([A-Za-z0-9_.\-]+)\s*】")

METRIC_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\d+(?:\.\d+)?\s*%"), "百分比"),
    (re.compile(r"\d+(?:\.\d+)?\s*(?:倍|万|亿|千)"), "数量级"),
    (re.compile(r"(?:P95|P99|QPS|TPS|RT)\s*[:：]?\s*\d+", re.IGNORECASE), "性能指标"),
    (re.compile(r"(?:准确率|召回率|覆盖率|成功率|通过率|命中率|转化率)\s*[:：]?\s*\d+"), "质量指标"),
    (re.compile(r"\d+\s*(?:ms|毫秒|秒|分钟|小时)"), "耗时"),
    (re.compile(r"(?:用户|客户|日活|月活|工单)\s*(?:数)?\s*\d+"), "规模"),
]

PERCENT_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*%")

VAGUE_RESULT_WORDS = [
    "提升性能",
    "提高性能",
    "提升稳定性",
    "提高稳定性",
    "优化体验",
    "提升体验",
    "大幅提升",
    "显著提升",
    "有效提升",
    "性能优化",
    "降本增效",
]

STRONG_VERBS = ["主导", "负责人", "Owner", "owner", "从0到1", "从 0 到 1", "核心作者", "独立完成", "全权负责"]

# 指标口径线索：出现指标时，同一行至少要有一种，否则无法判断数字怎么来的
SCOPE_WORDS = ["口径", "实测", "压测", "基线", "测量", "统计", "同比", "环比", "待测", "验证计划", "目标值"]

PENDING_MARKERS = ["【待补", "待确认", "TODO"]

STRONG_LEVELS = {"主导方案或交付", "项目负责人"}

# 启发式内部私名：命中即提醒抽象成通用表达
HEURISTIC_INTERNAL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b[a-zA-Z0-9_\-]+/[a-zA-Z0-9_\-]+\.(?:py|ts|js|java|go|yaml|json)\b"), "代码路径"),
    (re.compile(r"\b[a-z][a-z0-9]*_[a-z0-9_]+\b"), "下划线字段/函数名"),
    (re.compile(r"\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b"), "驼峰类名"),
]

PILLAR_PREFIX = re.compile(r"^\s*[-*+]\s*\*\*[^*：:]{2,20}[：:]\*\*")

# 公开技术名词容易被驼峰规则误伤，命中这些名字不算内部私名
TECH_ALLOWLIST = {
    "fastapi",
    "sqlalchemy",
    "postgresql",
    "mysql",
    "mongodb",
    "javascript",
    "typescript",
    "github",
    "gitlab",
    "openai",
    "langchain",
    "langgraph",
    "llamaindex",
    "pytorch",
    "tensorflow",
    "websocket",
    "kubernetes",
    "elasticsearch",
    "clickhouse",
    "qdrant",
    "milvus",
}


@dataclass
class Finding:
    rule: str
    severity: str
    line: int
    snippet: str
    message: str
    suggestion: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class Ledger:
    claims: dict[str, dict] = field(default_factory=dict)
    internal_names: list[str] = field(default_factory=list)

    def get(self, claim_id: str) -> dict | None:
        return self.claims.get(claim_id)


def load_ledger(path: Path) -> Ledger:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        raw_claims = data.get("claims", [])
        internal_names = list(data.get("internal_names", []) or [])
    else:
        raw_claims = data
        internal_names = []
    claims: dict[str, dict] = {}
    for item in raw_claims:
        if isinstance(item, dict) and item.get("id"):
            claims[str(item["id"])] = item
    return Ledger(claims=claims, internal_names=internal_names)


def load_internal_names(path: Path) -> list[str]:
    names = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text and not text.startswith("#"):
            names.append(text)
    return names

def _metrics_in(line: str) -> list[str]:
    return [label for pattern, label in METRIC_PATTERNS if pattern.search(line)]


def _suspicious_percentages(line: str) -> list[str]:
    return [raw for raw in PERCENT_PATTERN.findall(line) if float(raw) > 100]


def audit_line(line: str, number: int, *, ledger: Ledger | None, mode: str) -> list[Finding]:
    findings: list[Finding] = []
    stripped = line.strip()
    snippet = stripped[:80]
    markers = EVIDENCE_MARKER.findall(stripped)

    def add(rule: str, severity: str, message: str, suggestion: str) -> None:
        findings.append(
            Finding(
                rule=rule,
                severity=severity,
                line=number,
                snippet=snippet,
                message=message,
                suggestion=suggestion,
            )
        )

    # 1) 指标必须挂证据
    metric_labels = _metrics_in(stripped)
    if metric_labels:
        labels = "、".join(metric_labels)
        if not markers:
            add(
                "metric_without_evidence",
                SEVERITY_ERROR,
                f"出现{labels}，但这一条没有【证据：claim-id】标记，无法回指账本。",
                "补上【证据：claim-xxx】并确认该数字来自实测；没有实测数据就改成可核验的定性结果或写「待测」。",
            )
        if not any(word in stripped for word in SCOPE_WORDS):
            add(
                "metric_without_scope",
                SEVERITY_WARNING,
                f"出现{labels}，但没有说明统计口径或测量方式。",
                "补一句口径，例如「（口径：本地压测，200 并发，P95）」；不确定就标「待测」。",
            )
        for raw in _suspicious_percentages(stripped):
            add(
                "suspicious_metric",
                SEVERITY_WARNING,
                f"百分比 {raw}% 大于 100%，很容易被面试官当成编的数字。",
                "确认基线与口径，或改成绝对量（例如「从 3 步降到 1 步」）。",
            )

    # 2) 证据 id 必须存在，且最终稿不能引用未确认条目
    for claim_id in markers:
        if ledger is None:
            continue
        claim = ledger.get(claim_id)
        if claim is None:
            add(
                "evidence_id_unknown",
                SEVERITY_ERROR,
                f"引用的证据 id {claim_id} 不在账本里。",
                "在账本补建这条主张，或删除这个引用。",
            )
            continue
        status = str(claim.get("verification_status", ""))
        if mode == "final" and status != "已确认":
            add(
                "pending_claim_in_final",
                SEVERITY_ERROR,
                f"最终稿引用了状态为「{status}」的主张 {claim_id}。",
                "投递版本只保留「已确认」的主张；未确认的先回到账本补证据。",
            )

    # 3) 不可验证的结果词
    hit_vague = [word for word in VAGUE_RESULT_WORDS if word in stripped]
    if hit_vague:
        add(
            "vague_result",
            SEVERITY_ERROR,
            f"出现不可验证的结果表达：{hit_vague[0]}。",
            "改成机制带来的可验证变化（接口收敛、失败隔离、重试边界）或写「收益待测」。",
        )

    # 4) 强动词必须有账本支撑，且职责等级匹配
    hit_strong = [word for word in STRONG_VERBS if word in stripped]
    if hit_strong:
        verb = hit_strong[0]
        if ledger is None:
            add(
                "strong_verb_without_ledger",
                SEVERITY_WARNING,
                f"使用了强动词「{verb}」，但没有提供账本，无法核对职责边界。",
                "为该经历建账本条目并写清 boundary 与 interview_details。",
            )
        else:
            levels = {
                str((ledger.get(cid) or {}).get("responsibility_level", "")) for cid in markers
            }
            if not markers or not (levels & STRONG_LEVELS):
                add(
                    "strong_verb_boundary_violation",
                    SEVERITY_ERROR,
                    f"强动词「{verb}」缺少匹配的职责等级（需要 {sorted(STRONG_LEVELS)}）。",
                    "降级为「负责模块/参与」，或在账本里确认你确实主导并补齐 interview_details。",
                )

    # 5) 待确认标记不能进最终稿
    hit_pending = [word for word in PENDING_MARKERS if word in stripped]
    if hit_pending:
        add(
            "pending_marker_in_final" if mode == "final" else "draft_pending_marker",
            SEVERITY_ERROR if mode == "final" else SEVERITY_WARNING,
            f"出现待确认标记「{hit_pending[0]}」。",
            "最终稿必须删掉或补齐；草稿阶段可以保留，但要列进待补清单。",
        )

    # 6) 内部私名泄漏
    if ledger is not None:
        for name in ledger.internal_names:
            if name and name in stripped:
                add(
                    "internal_name_leak",
                    SEVERITY_ERROR,
                    f"出现内部私名「{name}」。",
                    "改写为面试官能懂的通用能力表达，具体符号下沉到源码证据索引。",
                )
    for pattern, label in HEURISTIC_INTERNAL_PATTERNS:
        found = pattern.search(stripped)
        if not found or found.group(0).lower() in TECH_ALLOWLIST:
            continue
        if any(f.rule == "internal_name_leak" for f in findings):
            break
        add(
            "internal_name_leak",
            SEVERITY_WARNING,
            f"疑似内部{label}「{found.group(0)}」。",
            "确认是否面试官能理解；不能理解就抽象成通用表达。",
        )
        break

    # 7) bullet 结构：一级 bullet 建议用「通用支柱名：」开头
    if stripped.startswith(("-", "*", "+")) and len(stripped) >= 20 and not PILLAR_PREFIX.match(line):
        add(
            "bullet_missing_pillar",
            SEVERITY_WARNING,
            "这条 bullet 没有以「**通用支柱名：**」开头，面试官看不到能力标签。",
            "改成「**分层容错：** 针对……问题，采用……机制，……」。",
        )

    return findings


def audit_resume(text: str, *, ledger: Ledger | None = None, mode: str = "draft") -> list[Finding]:
    findings: list[Finding] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("|"):
            continue
        findings.extend(audit_line(raw, number, ledger=ledger, mode=mode))
    return findings




def summarize(findings: list[Finding]) -> dict[str, int]:
    return {
        "error": sum(1 for item in findings if item.severity == SEVERITY_ERROR),
        "warning": sum(1 for item in findings if item.severity == SEVERITY_WARNING),
        "total": len(findings),
    }


def render_text(path: Path, findings: list[Finding], summary: dict[str, int], mode: str) -> str:
    lines = [
        f"审计对象：{path}（模式：{mode}）",
        f"结果：error {summary['error']} 条，warning {summary['warning']} 条",
        "",
    ]
    if not findings:
        lines.append("没有发现规则内的问题。注意：审计只保证「可核验」，不保证经历真实，最终事实仍需本人确认。")
        return "\n".join(lines)
    for item in findings:
        lines.append(f"[{item.severity}] 第 {item.line} 行 {item.rule}")
        lines.append(f"  原文：{item.snippet}")
        lines.append(f"  问题：{item.message}")
        lines.append(f"  改法：{item.suggestion}")
        lines.append("")
    if summary["error"]:
        lines.append("存在 error：这份简历还不满足「可被追问」的最低要求，先按上面的改法逐条处理。")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="简历反假审计（零依赖）")
    parser.add_argument("resume", type=Path, help="简历 Markdown 文件")
    parser.add_argument("--ledger", type=Path, default=None, help="主张—证据账本 JSON")
    parser.add_argument("--internal-names", type=Path, default=None, help="内部私名清单（每行一个）")
    parser.add_argument("--mode", choices=("draft", "final"), default="draft", help="final 时待确认内容直接判错")
    parser.add_argument("--json", action="store_true", help="输出 JSON，方便接进流水线")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.resume.exists():
        print(f"简历文件不存在：{args.resume}", file=sys.stderr)
        return 2

    ledger: Ledger | None = None
    if args.ledger:
        if not args.ledger.exists():
            print(f"账本文件不存在：{args.ledger}", file=sys.stderr)
            return 2
        ledger = load_ledger(args.ledger)
    if args.internal_names:
        names = load_internal_names(args.internal_names)
        ledger = ledger or Ledger()
        ledger.internal_names.extend(names)

    findings = audit_resume(args.resume.read_text(encoding="utf-8"), ledger=ledger, mode=args.mode)
    summary = summarize(findings)

    if args.json:
        payload = {
            "resume": str(args.resume),
            "mode": args.mode,
            "summary": summary,
            "findings": [item.as_dict() for item in findings],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(render_text(args.resume, findings, summary, args.mode))

    return 1 if summary["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
