"""曖昧ペアのAI判定（Claude API）。

ルールで判断しきれなかったペアだけをまとめて1リクエストで判定する。
確信度が閾値未満のものはマージせず「保留」にして人間の確認に委ねる。

ANTHROPIC_API_KEY が未設定の環境ではモック判定で動作する
（ローカル開発・API費用ゼロでのデモ用）。
"""

from __future__ import annotations

import json
import os

import anthropic
from pydantic import BaseModel

from .matching import MatchPair

# デモ用途のためコスト最優先で Haiku を使用（判定タスクには十分な精度）
MODEL = "claude-haiku-4-5"

MERGE_THRESHOLD = 0.85   # これ以上の確信度で「同一」→ マージ
HOLD_THRESHOLD = 0.5     # これ以上なら「保留」アラート、未満は別人と確定

SYSTEM_PROMPT = """\
あなたは日本の顧客データ・施設データの名寄せ（同一エンティティ判定）の専門家です。
2件のレコードが同一の人物（または施設・法人）を指すかを判定してください。

判定の観点:
- 姓名の表記揺れ（旧字体/新字体、外字、通称）、結婚等による改姓の可能性
- 住所の転居可能性（同一人物でも住所が異なることはある）
- 入力ミスの可能性（電話番号の1桁違い、メールのドメイン違い等）
- 同姓同名の別人の可能性（生年月日や住所が明確に異なる場合）

confidence は「同一である」ことへの確信度 (0.0〜1.0)。
迷う場合は confidence を低めに出すこと。誤マージは誤分割より重大な事故である。
reason は日本語で1文、判定根拠を書くこと。
"""


def _make_client() -> anthropic.Anthropic:
    """IDリンク型APIキーは anthropic-workspace-id ヘッダーが必須のため、
    環境変数 ANTHROPIC_WORKSPACE_ID があれば付与する。"""
    workspace_id = os.environ.get("ANTHROPIC_WORKSPACE_ID", "")
    headers = {"anthropic-workspace-id": workspace_id} if workspace_id else None
    return anthropic.Anthropic(default_headers=headers)


class PairVerdict(BaseModel):
    pair_id: int
    same_entity: bool
    confidence: float
    reason: str


class JudgeResponse(BaseModel):
    verdicts: list[PairVerdict]


def _format_record(row: dict[str, str], field_map: dict[str, str]) -> dict[str, str]:
    """AIに渡すレコード表現。マッピング済みフィールドのみ（余計な列は渡さない）。"""
    return {
        f: row.get(header, "")
        for f, header in field_map.items()
        if row.get(header, "")
    }


def judge_pairs(
    pairs: list[MatchPair],
    rows: list[dict[str, str]],
    field_map: dict[str, str],
) -> tuple[list[MatchPair], bool]:
    """曖昧ペアを判定し verdict / confidence / explanation を書き込む。

    戻り値: (判定済みペア, AIを実際に使ったか)
    """
    if not pairs:
        return pairs, False

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return _mock_judge(pairs, rows, field_map), False

    payload = [
        {
            "pair_id": idx,
            "candidate_reason": pair.reason,
            "record_a": _format_record(rows[pair.index_a], field_map),
            "record_b": _format_record(rows[pair.index_b], field_map),
        }
        for idx, pair in enumerate(pairs)
    ]

    client = _make_client()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": (
                "次の各ペアについて同一エンティティかを判定してください。\n\n"
                + json.dumps(payload, ensure_ascii=False, indent=1)
            ),
        }],
        output_format=JudgeResponse,
    )
    verdicts = {v.pair_id: v for v in response.parsed_output.verdicts}

    for idx, pair in enumerate(pairs):
        verdict = verdicts.get(idx)
        if verdict is None:
            pair.verdict, pair.explanation = "hold", "AI判定が返らなかったため保留"
            continue
        pair.confidence = verdict.confidence
        pair.explanation = verdict.reason
        if verdict.same_entity and verdict.confidence >= MERGE_THRESHOLD:
            pair.verdict = "merge"
        elif verdict.confidence >= HOLD_THRESHOLD:
            pair.verdict = "hold"
        else:
            pair.verdict = "distinct"
    return pairs, True


def _mock_judge(
    pairs: list[MatchPair],
    rows: list[dict[str, str]],
    field_map: dict[str, str],
) -> list[MatchPair]:
    """APIキーなし環境用の決定的モック。候補根拠の強さだけで機械的に振り分ける。"""
    for pair in pairs:
        if "フリガナが一致" in pair.reason:
            pair.verdict, pair.confidence = "merge", 0.9
            pair.explanation = "[モック判定] フリガナ一致を同一とみなす"
        elif "類似度 0.9" in pair.reason or "類似度 1.00" in pair.reason:
            pair.verdict, pair.confidence = "hold", 0.7
            pair.explanation = "[モック判定] 名前が酷似するため要確認"
        else:
            pair.verdict, pair.confidence = "hold", 0.6
            pair.explanation = "[モック判定] 判断材料不足のため保留"
    return pairs
