# skills/agent-resume-packaging/tests/test_validate_claim_ledger.py
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import validate_claim_ledger as vl  # noqa: E402

TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "claim-ledger-template.json"


def valid_claim(**overrides):
    data = {
        "id": "claim-agent-001",
        "source_fact": "把知识库需要的文档能力抽成工具注册表",
        "candidate_wording": "**分层工具编排：** 统一工具声明与执行边界",
        "sources": ["app/agent/tools.py", "tests/test_agent_tools.py"],
        "responsibility_level": "负责模块",
        "verification_status": "已确认",
        "allowed_uses": ["Agent 开发岗"],
        "interview_details": ["为什么参数校验放在工具层"],
        "boundary": "工具层由本人实现，模型接入只做协议适配",
        "risk_notes": [],
        "last_verified": "2026-10-17",
    }
    data.update(overrides)
    return data


def fields(issues):
    return {item["field"] for item in issues}


def test_template_asset_is_valid():
    data = json.loads(TEMPLATE.read_text(encoding="utf-8"))

    assert vl.validate_ledger(data) == []


def test_valid_ledger_has_no_issues():
    assert vl.validate_ledger({"claims": [valid_claim()]}) == []


def test_missing_field_is_error():
    claim = valid_claim()
    del claim["boundary"]

    issues = vl.validate_ledger({"claims": [claim]})

    assert any(item["field"] == "boundary" and item["severity"] == "error" for item in issues)


def test_blank_required_field_is_error():
    issues = vl.validate_ledger({"claims": [valid_claim(source_fact="   ")]})

    assert "source_fact" in fields(issues)


def test_invalid_enums_are_errors():
    issues = vl.validate_ledger(
        {
            "claims": [
                valid_claim(responsibility_level="负责人", verification_status="也许吧"),
            ]
        }
    )

    assert {"responsibility_level", "verification_status"} <= fields(issues)


def test_confirmed_claim_needs_sources():
    issues = vl.validate_ledger({"claims": [valid_claim(sources=[])]})

    assert any(item["field"] == "sources" and item["severity"] == "error" for item in issues)


def test_strong_level_needs_interview_details():
    issues = vl.validate_ledger(
        {"claims": [valid_claim(responsibility_level="主导方案或交付", interview_details=[])]}
    )

    assert any(item["field"] == "interview_details" for item in issues)


def test_duplicate_id_is_error():
    issues = vl.validate_ledger({"claims": [valid_claim(), valid_claim(source_fact="另一件事")]})

    assert any(item["field"] == "id" and item["severity"] == "error" for item in issues)


def test_bad_date_is_error():
    issues = vl.validate_ledger({"claims": [valid_claim(last_verified="2026/10/17")]})

    assert "last_verified" in fields(issues)


def test_null_date_is_allowed():
    issues = vl.validate_ledger({"claims": [valid_claim(last_verified=None, verification_status="待确认", candidate_wording="【待补：补证据】", sources=[])]})

    assert issues == []


def test_pending_claim_should_keep_placeholder():
    issues = vl.validate_ledger(
        {"claims": [valid_claim(verification_status="待确认", candidate_wording="已实现轨迹落盘", sources=[])]}
    )

    assert any(item["field"] == "candidate_wording" and item["severity"] == "warning" for item in issues)


def test_secret_material_is_error():
    issues = vl.validate_ledger({"claims": [valid_claim(sources=["token: sk-abcdef123456"])]})

    assert any("凭据" in item["message"] or "口令" in item["message"] for item in issues)


def test_duplicate_source_fact_is_warning():
    issues = vl.validate_ledger(
        {"claims": [valid_claim(), valid_claim(id="claim-agent-002", candidate_wording="另一种说法")]}
    )

    assert any(item["field"] == "source_fact" and item["severity"] == "warning" for item in issues)


def test_bare_list_is_warning_and_missing_claims_is_error():
    assert any(item["severity"] == "warning" for item in vl.validate_ledger([valid_claim()]))
    assert any(item["severity"] == "error" for item in vl.validate_ledger({"nope": []}))


def test_non_object_claim_is_error():
    issues = vl.validate_ledger({"claims": ["不是对象"]})

    assert issues and issues[0]["severity"] == "error"


def test_main_exit_codes(tmp_path, capsys):
    good = tmp_path / "ledger.json"
    good.write_text(json.dumps({"claims": [valid_claim()]}, ensure_ascii=False), encoding="utf-8")
    assert vl.main([str(good)]) == 0
    assert "结构与状态检查通过" in capsys.readouterr().out

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"claims": [valid_claim(sources=[])]}, ensure_ascii=False), encoding="utf-8")
    assert vl.main([str(bad), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["error"] >= 1

    broken = tmp_path / "broken.json"
    broken.write_text("{不是 json", encoding="utf-8")
    assert vl.main([str(broken)]) == 2
    assert vl.main([str(tmp_path / "missing.json")]) == 2
