#!/usr/bin/env python3
# skills/agent-resume-packaging/scripts/validate_claim_ledger.py
"""主张—证据账本结构校验：只检查确定性的结构和状态矛盾，不判断经历真假。

    python3 scripts/validate_claim_ledger.py ledger.json
    python3 scripts/validate_claim_ledger.py ledger.json --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_FIELDS = [
    "id",
    "source_fact",
    "candidate_wording",
    "sources",
    "responsibility_level",
    "verification_status",
    "allowed_uses",
    "interview_details",
    "boundary",
    "risk_notes",
    "last_verified",
]

NON_BLANK_FIELDS = [
    "id",
    "source_fact",
    "candidate_wording",
    "responsibility_level",
    "verification_status",
    "boundary",
]

RESPONSIBILITY_LEVELS = {"参与", "负责模块", "主导方案或交付", "项目负责人"}
VERIFICATION_STATUS = {"已确认", "待确认", "已过期", "不采用"}
STRONG_LEVELS = {"主导方案或交付", "项目负责人"}
ID_PATTERN = re.compile(r"^claim-[a-z0-9\-]+-\d{3}$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9]{8,}"), "疑似 API Key"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"), "疑似 GitHub Token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "疑似 AWS Key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "疑似私钥"),
    (re.compile(r"(?i)(password|passwd|secret)\s*[:=]\s*\S+"), "疑似口令"),
]

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


def _issue(severity: str, claim_id: str, field: str, message: str) -> dict[str, str]:
    return {"severity": severity, "claim": claim_id, "field": field, "message": message}


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple)):
        return len(value) == 0
    return False


def _validate_claim(claim: dict, index: int, seen_ids: dict[str, int], seen_facts: dict[str, str]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    claim_id = str(claim.get("id") or f"#{index}")

    for field in REQUIRED_FIELDS:
        if field not in claim:
            issues.append(_issue(SEVERITY_ERROR, claim_id, field, "缺少必填字段。"))

    for field in NON_BLANK_FIELDS:
        if field in claim and _is_blank(claim[field]):
            issues.append(_issue(SEVERITY_ERROR, claim_id, field, "字段不能为空。"))

    if claim_id in seen_ids:
        issues.append(_issue(SEVERITY_ERROR, claim_id, "id", f"与第 {seen_ids[claim_id]} 条主张 id 重复。"))
    seen_ids[claim_id] = index

    if "id" in claim and not ID_PATTERN.match(str(claim["id"])):
        issues.append(
            _issue(SEVERITY_WARNING, claim_id, "id", "建议使用 claim-<模块>-<三位序号> 形式，便于跨文档引用。")
        )

    level = claim.get("responsibility_level")
    if level is not None and level not in RESPONSIBILITY_LEVELS:
        issues.append(
            _issue(SEVERITY_ERROR, claim_id, "responsibility_level", f"取值必须是 {sorted(RESPONSIBILITY_LEVELS)}。")
        )

    status = claim.get("verification_status")
    if status is not None and status not in VERIFICATION_STATUS:
        issues.append(
            _issue(SEVERITY_ERROR, claim_id, "verification_status", f"取值必须是 {sorted(VERIFICATION_STATUS)}。")
        )

    if status == "已确认" and _is_blank(claim.get("sources")):
        issues.append(
            _issue(SEVERITY_ERROR, claim_id, "sources", "已确认的主张必须给出证据来源（文件、链接、可复现命令）。")
        )

    if status == "已确认" and _is_blank(claim.get("allowed_uses")):
        issues.append(
            _issue(SEVERITY_WARNING, claim_id, "allowed_uses", "已确认的主张建议写明可用于哪些岗位版本。")
        )

    if level in STRONG_LEVELS and _is_blank(claim.get("interview_details")):
        issues.append(
            _issue(SEVERITY_ERROR, claim_id, "interview_details", "强主张必须能回答追问，补齐决策、难点和验证方式。")
        )

    if status == "待确认" and "【待补" not in str(claim.get("candidate_wording", "")):
        issues.append(
            _issue(
                SEVERITY_WARNING,
                claim_id,
                "candidate_wording",
                "待确认的主张建议在措辞里保留【待补】占位，避免误进正式稿。",
            )
        )

    last_verified = claim.get("last_verified")
    if last_verified is not None and not DATE_PATTERN.match(str(last_verified)):
        issues.append(_issue(SEVERITY_ERROR, claim_id, "last_verified", "日期格式必须是 YYYY-MM-DD，未知时写 null。"))

    fact = str(claim.get("source_fact", "")).strip()
    if fact:
        previous = seen_facts.get(fact)
        if previous is not None:
            issues.append(
                _issue(SEVERITY_WARNING, claim_id, "source_fact", f"与 {previous} 的 source_fact 重复，建议合并为一条并写明冲突。")
            )
        seen_facts[fact] = claim_id

    blob = json.dumps(claim, ensure_ascii=False)
    for pattern, label in SECRET_PATTERNS:
        if pattern.search(blob):
            issues.append(_issue(SEVERITY_ERROR, claim_id, "sources", f"{label}：账本不得存放凭据或口令。"))

    return issues



def validate_ledger(data: object) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if isinstance(data, list):
        claims: object = data
        issues.append(
            _issue(
                SEVERITY_WARNING,
                "-",
                "$",
                "账本顶层是数组，建议改成 {\"claims\": [...]}，以便承载 internal_names 等元信息。",
            )
        )
    elif isinstance(data, dict):
        claims = data.get("claims")
        if not isinstance(claims, list):
            return [_issue(SEVERITY_ERROR, "-", "claims", "账本缺少 claims 数组。")]
    else:
        return [_issue(SEVERITY_ERROR, "-", "$", "账本必须是 JSON 对象或数组。")]

    seen_ids: dict[str, int] = {}
    seen_facts: dict[str, str] = {}
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            issues.append(_issue(SEVERITY_ERROR, f"#{index}", "$", "这条主张不是对象。"))
            continue
        issues.extend(_validate_claim(claim, index, seen_ids, seen_facts))
    return issues


def summarize(issues: list[dict[str, str]]) -> dict[str, int]:
    return {
        "error": sum(1 for item in issues if item["severity"] == SEVERITY_ERROR),
        "warning": sum(1 for item in issues if item["severity"] == SEVERITY_WARNING),
        "total": len(issues),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="主张—证据账本结构校验（零依赖）")
    parser.add_argument("ledger", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if not args.ledger.exists():
        print(f"账本文件不存在：{args.ledger}", file=sys.stderr)
        return 2
    try:
        data = json.loads(args.ledger.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"账本不是合法 JSON：{exc}", file=sys.stderr)
        return 2

    issues = validate_ledger(data)
    summary = summarize(issues)

    if args.json:
        payload = {"ledger": str(args.ledger), "summary": summary, "issues": issues}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"账本：{args.ledger}")
        print(f"结果：error {summary['error']} 条，warning {summary['warning']} 条")
        for item in issues:
            print(f"[{item['severity']}] {item['claim']} · {item['field']}：{item['message']}")
        if not issues:
            print("结构与状态检查通过。注意：校验器不判断经历是否真实，也不联网核对 PR 状态。")
    return 1 if summary["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
