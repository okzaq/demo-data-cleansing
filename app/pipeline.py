"""クレンジング〜名寄せの一連のパイプライン。"""

from __future__ import annotations

import csv
import io
from typing import Any

from .ai_judge import judge_pairs
from .matching import MatchPair, build_groups, find_candidates
from .normalize import detect_fields, normalize_row

MAX_ROWS = 500  # デモ用の入力上限


class PipelineError(Exception):
    pass


def _pair_dict(pair: MatchPair, rows: list[dict[str, str]], field_map: dict[str, str]) -> dict[str, Any]:
    name_header = field_map.get("name", "")
    return {
        "index_a": pair.index_a,
        "index_b": pair.index_b,
        "name_a": rows[pair.index_a].get(name_header, f"行{pair.index_a + 1}"),
        "name_b": rows[pair.index_b].get(name_header, f"行{pair.index_b + 1}"),
        "reason": pair.reason,
        "verdict": pair.verdict,
        "confidence": pair.confidence,
        "explanation": pair.explanation,
    }


def run_pipeline(csv_text: str) -> dict[str, Any]:
    """CSVテキストを受け取り、クレンジング・名寄せ結果をまとめて返す。"""
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise PipelineError("CSVのヘッダー行が読み取れませんでした")
    headers = [h for h in reader.fieldnames if h is not None]
    # 列数がヘッダーと合わない行があっても落とさない（余剰列は捨て、欠損は空文字）
    original_rows = [
        {h: (row.get(h) or "") for h in headers} for row in reader
    ]
    if not original_rows:
        raise PipelineError("データ行がありません")
    if len(original_rows) > MAX_ROWS:
        raise PipelineError(f"デモ版の上限は {MAX_ROWS} 行です（{len(original_rows)} 行が入力されました）")

    field_map = detect_fields(headers)
    if "name" not in field_map:
        raise PipelineError(
            "名前に相当する列が見つかりませんでした（氏名・名前・施設名 などのヘッダーが必要です）"
        )

    # 1. ルールベース正規化
    cleaned_rows: list[dict[str, str]] = []
    changed_cells: list[list[str]] = []
    for row in original_rows:
        cleaned, changed = normalize_row(row, field_map)
        cleaned_rows.append(cleaned)
        changed_cells.append(changed)

    # 2. 突合候補の抽出（ルール確定 + 曖昧）
    auto_pairs, ambiguous = find_candidates(cleaned_rows, field_map)

    # 3. 曖昧ペアのみAI判定
    ai_pairs, ai_used = judge_pairs(ambiguous, cleaned_rows, field_map)

    # 4. グループ化（ルール確定 + AI確信マージ）
    merged_ai = [p for p in ai_pairs if p.verdict == "merge"]
    holds = [p for p in ai_pairs if p.verdict == "hold"]
    groups = build_groups(len(cleaned_rows), auto_pairs, merged_ai)

    # 5. 出力CSV（グループIDと保留フラグを付与）
    group_of: dict[int, int] = {}
    for gid, group in enumerate(groups, start=1):
        for idx in group:
            group_of[idx] = gid
    hold_indexes = {p.index_a for p in holds} | {p.index_b for p in holds}

    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=headers + ["名寄せグループ", "要確認"], lineterminator="\n")
    writer.writeheader()
    for idx, row in enumerate(cleaned_rows):
        writer.writerow({
            **row,
            "名寄せグループ": f"G{group_of[idx]:03d}" if idx in group_of else "",
            "要確認": "保留" if idx in hold_indexes else "",
        })

    normalized_count = sum(1 for c in changed_cells if c)
    return {
        "headers": headers,
        "field_map": field_map,
        "original_rows": original_rows,
        "cleaned_rows": cleaned_rows,
        "changed_cells": changed_cells,
        "groups": groups,
        "auto_pairs": [_pair_dict(p, cleaned_rows, field_map) for p in auto_pairs],
        "ai_pairs": [_pair_dict(p, cleaned_rows, field_map) for p in ai_pairs],
        "ai_used": ai_used,
        "output_csv": out.getvalue(),
        "summary": {
            "total_rows": len(original_rows),
            "normalized_rows": normalized_count,
            "merged_groups": len(groups),
            "hold_pairs": len(holds),
        },
    }
