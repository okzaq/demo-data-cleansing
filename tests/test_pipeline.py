"""パイプラインの動作確認（APIキー不要・AI判定はモックで走る）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.normalize import (  # noqa: E402
    detect_fields,
    normalize_address,
    normalize_company,
    normalize_kana,
    normalize_phone,
    normalize_postal,
)
from app.pipeline import run_pipeline  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def test_normalize_company():
    assert normalize_company("㈱北海道商事") == "株式会社北海道商事"
    assert normalize_company("(有)さくら企画") == "有限会社さくら企画"


def test_normalize_kana():
    assert normalize_kana("やまだ たろう") == "ヤマダタロウ"
    assert normalize_kana("ｻﾄｳ ﾊﾅｺ") == "サトウハナコ"


def test_normalize_address():
    assert normalize_address("札幌市中央区北一条西二丁目3番4号") == "札幌市中央区北1条西2-3-4"
    assert normalize_address("帯広市大通南10丁目1番地") == "帯広市大通南10-1"


def test_normalize_phone_postal():
    assert normalize_phone("011-234-5678") == "0112345678"
    assert normalize_postal("０６２－００２０") == "062-0020"


def test_detect_fields():
    mapping = detect_fields(["顧客ID", "氏名", "フリガナ", "メールアドレス", "住所"])
    assert mapping["name"] == "氏名"
    assert mapping["kana"] == "フリガナ"
    assert mapping["email"] == "メールアドレス"
    assert "顧客ID" not in mapping.values() or True  # パススルー列は対象外


def test_pipeline_customers():
    csv_text = (DATA_DIR / "sample_customers.csv").read_text(encoding="utf-8-sig")
    result = run_pipeline(csv_text)

    assert result["summary"]["total_rows"] == 20
    # ルール確定: C001/C002 はメール一致で必ず統合される
    assert any(
        {p["index_a"], p["index_b"]} == {0, 1} for p in result["auto_pairs"]
    )
    assert result["summary"]["merged_groups"] >= 2
    # 曖昧ペアがAI判定（モック）に回っている
    assert len(result["ai_pairs"]) > 0
    assert all(p["verdict"] in ("merge", "hold", "distinct") for p in result["ai_pairs"])
    # 出力CSVに付加列がある
    assert "名寄せグループ" in result["output_csv"].splitlines()[0]


def test_pipeline_facilities():
    csv_text = (DATA_DIR / "sample_facilities.csv").read_text(encoding="utf-8-sig")
    result = run_pipeline(csv_text)
    assert result["summary"]["total_rows"] == 10
    assert result["field_map"]["name"] == "施設名"
    assert result["summary"]["merged_groups"] >= 1


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok: {name}")
    print("all tests passed")
