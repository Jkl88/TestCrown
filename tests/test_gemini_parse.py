from app.gemini import parse_summary_json


def test_parse_plain_json():
    data = parse_summary_json(
        '{"subject":"окна","customer":"школа","contract_amount":"1 млн руб.",'
        '"deadlines":"60 дней","requirements":["СРО"],"penalties":["0.1% в день"],'
        '"notes":null}'
    )
    assert data["subject"] == "окна"
    assert data["requirements"] == ["СРО"]
    assert data["notes"] is None


def test_parse_fenced_json():
    raw = """```json
    {"subject": "x", "customer": null, "contract_amount": null,
     "deadlines": null, "requirements": [], "penalties": ["штраф"], "notes": ""}
    ```"""
    data = parse_summary_json(raw)
    assert data["subject"] == "x"
    assert data["penalties"] == ["штраф"]
    assert data["notes"] is None
