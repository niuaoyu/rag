# skills/agent-resume-packaging/tests/test_audit_resume.py
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import audit_resume as ar  # noqa: E402

LEDGER = {
    "internal_names": ["RunManager"],
    "claims": [
        {
            "id": "claim-agent-001",
            "responsibility_level": "负责模块",
            "verification_status": "已确认",
        },
        {
            "id": "claim-agent-002",
            "responsibility_level": "主导方案或交付",
            "verification_status": "已确认",
        },
        {
            "id": "claim-agent-003",
            "responsibility_level": "参与",
            "verification_status": "待确认",
        },
    ],
}


def rules(findings):
    return sorted({item.rule for item in findings})


def test_clean_bullet_has_no_findings():
    line = "- **请求可靠性治理：** 针对下游抖动，引入超时与有限重试，仅对幂等请求重试【证据：claim-agent-001】，延迟收益待测。"

    findings = ar.audit_resume(line, ledger=ar.Ledger(claims={c["id"]: c for c in LEDGER["claims"]}))

    assert findings == []


def test_metric_without_evidence_is_error():
    findings = ar.audit_resume("- 把问答成功率提升到 95%，P95 从 3 秒降到 800ms。")

    assert "metric_without_evidence" in rules(findings)
    assert all(item.severity == ar.SEVERITY_ERROR for item in findings if item.rule == "metric_without_evidence")


def test_metric_with_evidence_but_no_scope_is_warning():
    findings = ar.audit_resume("- 命中率 92%【证据：claim-agent-001】。")

    assert "metric_without_scope" in rules(findings)
    assert "metric_without_evidence" not in rules(findings)


def test_percentage_over_100_is_flagged():
    findings = ar.audit_resume("- 吞吐提升 300%【证据：claim-agent-001】（口径：本地压测）。")

    assert "suspicious_metric" in rules(findings)


def test_vague_result_word_is_error():
    findings = ar.audit_resume("- 增加缓存和重试，提升稳定性。")

    assert "vague_result" in rules(findings)


def test_strong_verb_without_ledger_is_warning():
    findings = ar.audit_resume("- 主导了问答链路改造。")

    assert "strong_verb_without_ledger" in rules(findings)


def test_strong_verb_with_wrong_level_is_error():
    ledger = ar.Ledger(claims={c["id"]: c for c in LEDGER["claims"]})

    findings = ar.audit_resume("- 主导了工具注册表设计【证据：claim-agent-001】。", ledger=ledger)

    assert "strong_verb_boundary_violation" in rules(findings)


def test_strong_verb_with_matching_level_passes():
    ledger = ar.Ledger(claims={c["id"]: c for c in LEDGER["claims"]})

    findings = ar.audit_resume("- 主导了编排预算设计【证据：claim-agent-002】。", ledger=ledger)

    assert "strong_verb_boundary_violation" not in rules(findings)


def test_unknown_evidence_id_is_error():
    ledger = ar.Ledger(claims={c["id"]: c for c in LEDGER["claims"]})

    findings = ar.audit_resume("- 完成工具层【证据：claim-unknown-999】。", ledger=ledger)

    assert "evidence_id_unknown" in rules(findings)


def test_pending_claim_blocks_final_mode():
    ledger = ar.Ledger(claims={c["id"]: c for c in LEDGER["claims"]})

    draft = ar.audit_resume("- 轨迹用于排障【证据：claim-agent-003】。", ledger=ledger, mode="draft")
    final = ar.audit_resume("- 轨迹用于排障【证据：claim-agent-003】。", ledger=ledger, mode="final")

    assert "pending_claim_in_final" not in rules(draft)
    assert "pending_claim_in_final" in rules(final)


def test_pending_marker_severity_depends_on_mode():
    draft = ar.audit_resume("- 实现了轨迹落盘【待补：补真实样例】。")
    final = ar.audit_resume("- 实现了轨迹落盘【待补：补真实样例】。", mode="final")

    assert "draft_pending_marker" in rules(draft)
    assert "pending_marker_in_final" in rules(final)


def test_internal_names_from_ledger_are_errors():
    ledger = ar.Ledger(claims={}, internal_names=["RunManager"])

    findings = ar.audit_resume("- 用 RunManager 管理运行状态。", ledger=ledger)

    assert "internal_name_leak" in rules(findings)
    assert any(item.severity == ar.SEVERITY_ERROR for item in findings if item.rule == "internal_name_leak")


def test_heuristic_internal_names_are_warnings():
    findings = ar.audit_resume("- 在 app/agent/loop.py 里实现了有限步循环。")

    assert "internal_name_leak" in rules(findings)
    assert any(item.severity == ar.SEVERITY_WARNING for item in findings if item.rule == "internal_name_leak")


def test_public_tech_names_are_not_flagged():
    findings = ar.audit_resume("- 技术栈：Python / FastAPI / SQLAlchemy / pytest。")

    assert "internal_name_leak" not in rules(findings)


def test_bullet_without_pillar_is_warning():
    findings = ar.audit_resume("- 接入列表分页和筛选功能，处理接口异常情况。")

    assert "bullet_missing_pillar" in rules(findings)


def test_headings_and_tables_are_skipped():
    text = "# 项目经历\n| 指标 | 数值 |\n| 成功率 | 99% |\n"

    assert ar.audit_resume(text) == []


def test_main_returns_exit_codes_and_json(tmp_path, capsys):
    resume = tmp_path / "resume.md"
    resume.write_text("- 主导问答链路改造，性能提升 300%。\n", encoding="utf-8")

    exit_code = ar.main([str(resume), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["summary"]["error"] >= 1
    assert payload["resume"].endswith("resume.md")

    clean = tmp_path / "clean.md"
    clean.write_text("- **分层容错：** 收敛异常处理路径。\n", encoding="utf-8")
    assert ar.main([str(clean)]) == 0


def test_main_reports_missing_files(tmp_path):
    assert ar.main([str(tmp_path / "nope.md")]) == 2
