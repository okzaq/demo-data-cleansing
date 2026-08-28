"""ルールベースのデータクレンジング処理。

AIに渡す前の第一段階。決定的なルールで直せるものはここで直し切り、
AIには「ルールで判断しきれない曖昧な突合」だけを回す方針。
"""

from __future__ import annotations

import re
import unicodedata

# 漢数字→算用数字（住所の丁目・番地で使う範囲のみ）
_KANJI_DIGITS = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
                 "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

_LEGAL_FORMS = [
    (re.compile(r"\(株\)|㈱"), "株式会社"),
    (re.compile(r"\(有\)|㈲"), "有限会社"),
    (re.compile(r"\(合\)"), "合同会社"),
]

# ヘッダーの表記揺れ → 正規フィールド名
HEADER_ALIASES = {
    "name": ["氏名", "名前", "顧客名", "施設名", "名称", "name"],
    "kana": ["カナ", "かな", "フリガナ", "ふりがな", "氏名カナ", "kana"],
    "company": ["会社名", "勤務先", "法人名", "所属", "company"],
    "email": ["メール", "メールアドレス", "email", "mail", "e-mail"],
    "phone": ["電話", "電話番号", "tel", "phone", "連絡先"],
    "postal": ["郵便番号", "〒", "zip", "postal", "postcode"],
    "address": ["住所", "所在地", "address", "addr"],
    "birthdate": ["生年月日", "誕生日", "birthdate", "birthday", "dob"],
}


def detect_fields(headers: list[str]) -> dict[str, str]:
    """CSVヘッダーから正規フィールド名 → 実ヘッダー名の対応を推定する。"""
    mapping: dict[str, str] = {}
    for header in headers:
        key = unicodedata.normalize("NFKC", header).strip().lower()
        for field, aliases in HEADER_ALIASES.items():
            if field not in mapping and key in [a.lower() for a in aliases]:
                mapping[field] = header
                break
    return mapping


def _kanji_to_number(text: str) -> str:
    """住所中の漢数字（十進まで）を算用数字に変換する。例: 三十二丁目 → 32丁目

    「五稜郭」「九段」のような地名の漢数字を壊さないよう、
    丁目・番地・号・条 が後続する場合に限って変換する。
    """

    def convert(match: re.Match) -> str:
        s = match.group(0)
        if "十" in s:
            tens, _, ones = s.partition("十")
            value = (_KANJI_DIGITS.get(tens, 1) if tens else 1) * 10
            value += _KANJI_DIGITS.get(ones, 0) if ones else 0
        else:
            value = 0
            for ch in s:
                value = value * 10 + _KANJI_DIGITS[ch]
        return str(value)

    return re.sub(r"[〇一二三四五六七八九十]+(?=丁目|番地|番|号|条)", convert, text)


def normalize_text(value: str) -> str:
    """全フィールド共通の基本整形。NFKC・空白の統一。"""
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"[\s　]+", " ", value).strip()
    return value


def normalize_name(value: str) -> str:
    """人名・施設名。基本整形＋姓名間の空白を1つに。"""
    return normalize_text(value)


def normalize_kana(value: str) -> str:
    """フリガナ。ひらがな→カタカナに統一し空白を除去。"""
    value = normalize_text(value)
    value = "".join(
        chr(ord(ch) + 0x60) if "ぁ" <= ch <= "ゖ" else ch for ch in value
    )
    return value.replace(" ", "")


def normalize_company(value: str) -> str:
    """法人名。㈱/(株)等を正式表記に展開し、前後の空白を整える。"""
    value = normalize_text(value)
    for pattern, replacement in _LEGAL_FORMS:
        value = pattern.sub(replacement, value)
    return value.replace("株式会社 ", "株式会社").replace(" 株式会社", "株式会社")


def normalize_email(value: str) -> str:
    return normalize_text(value).lower().replace(" ", "")


def normalize_phone(value: str) -> str:
    """電話番号。数字のみに正規化（比較キー兼表示用）。"""
    digits = re.sub(r"\D", "", normalize_text(value))
    return digits


def normalize_postal(value: str) -> str:
    """郵便番号。7桁なら XXX-XXXX 形式に統一。"""
    digits = re.sub(r"\D", "", normalize_text(value))
    if len(digits) == 7:
        return f"{digits[:3]}-{digits[4 - 1:]}"
    return digits


def normalize_address(value: str) -> str:
    """住所。漢数字→算用数字、丁目・番地・号→ハイフン区切りに統一。"""
    value = normalize_text(value).replace(" ", "")
    value = _kanji_to_number(value)
    value = re.sub(r"(\d+)丁目(\d+)番地?(\d+)号?", r"\1-\2-\3", value)
    value = re.sub(r"(\d+)丁目(\d+)番地?", r"\1-\2", value)
    value = re.sub(r"(\d+)丁目", r"\1-", value)
    value = re.sub(r"(\d+)番地?(\d+)号?", r"\1-\2", value)
    value = re.sub(r"(\d+)番地", r"\1", value)
    value = re.sub(r"-+", "-", value).rstrip("-")
    return value


def normalize_birthdate(value: str) -> str:
    """生年月日。YYYY-MM-DD に統一（和暦は対象外）。"""
    value = normalize_text(value)
    match = re.search(r"(\d{4})[年/\-.](\d{1,2})[月/\-.](\d{1,2})", value)
    if match:
        y, m, d = match.groups()
        return f"{y}-{int(m):02d}-{int(d):02d}"
    return value


NORMALIZERS = {
    "name": normalize_name,
    "kana": normalize_kana,
    "company": normalize_company,
    "email": normalize_email,
    "phone": normalize_phone,
    "postal": normalize_postal,
    "address": normalize_address,
    "birthdate": normalize_birthdate,
}


def normalize_row(row: dict[str, str], field_map: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """1行を正規化し、(正規化後の行, 変更があったフィールド名リスト) を返す。"""
    cleaned = dict(row)
    changed: list[str] = []
    for field, header in field_map.items():
        original = row.get(header, "") or ""
        normalized = NORMALIZERS[field](original)
        if normalized != original:
            changed.append(header)
        cleaned[header] = normalized
    return cleaned, changed
