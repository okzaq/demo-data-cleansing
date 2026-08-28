"""名寄せ（同一人物・同一施設の突合）ロジック。

方針: すべてをAI任せにしない。
  1. ルールで確実に判定できるペア（メール一致・電話一致など）は即マージ
  2. ルールで曖昧なペア（名前が似ている等）だけをAI判定に回す
  3. AIでも確信が持てないペアは「保留」として人間の確認に委ねる
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher


@dataclass
class MatchPair:
    index_a: int
    index_b: int
    reason: str            # 候補になった根拠
    verdict: str = ""      # merge / hold / distinct
    confidence: float = 0.0
    explanation: str = ""


@dataclass
class MatchResult:
    groups: list[list[int]]          # マージされた行インデックスのグループ
    auto_pairs: list[MatchPair]      # ルールで確定したペア
    ai_pairs: list[MatchPair]        # AI判定に回したペア（判定結果込み）
    holds: list[MatchPair] = field(default_factory=list)


class UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _get(row: dict[str, str], field_map: dict[str, str], f: str) -> str:
    header = field_map.get(f)
    return (row.get(header, "") or "") if header else ""


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def find_candidates(
    rows: list[dict[str, str]], field_map: dict[str, str]
) -> tuple[list[MatchPair], list[MatchPair]]:
    """全行を突き合わせ、(ルール確定ペア, AI判定行きペア) を返す。

    行数は最大500件（API側で制限）のため総当たりで十分。
    実案件で数万件規模を扱う場合はブロッキングキーで候補を絞る設計にする。
    """
    auto: list[MatchPair] = []
    ambiguous: list[MatchPair] = []

    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            a, b = rows[i], rows[j]
            email_a, email_b = _get(a, field_map, "email"), _get(b, field_map, "email")
            phone_a, phone_b = _get(a, field_map, "phone"), _get(b, field_map, "phone")
            kana_a, kana_b = _get(a, field_map, "kana"), _get(b, field_map, "kana")
            birth_a, birth_b = _get(a, field_map, "birthdate"), _get(b, field_map, "birthdate")
            name_sim = _similarity(_get(a, field_map, "name"), _get(b, field_map, "name"))
            addr_sim = _similarity(_get(a, field_map, "address"), _get(b, field_map, "address"))

            # --- ルールで確定できる強い一致 ---
            if email_a and email_a == email_b:
                auto.append(MatchPair(i, j, "メールアドレスが完全一致"))
                continue
            if phone_a and phone_a == phone_b and name_sim >= 0.5:
                auto.append(MatchPair(i, j, "電話番号が一致し名前も類似"))
                continue
            if kana_a and kana_a == kana_b and birth_a and birth_a == birth_b:
                auto.append(MatchPair(i, j, "フリガナと生年月日が一致"))
                continue

            # --- 曖昧: AI判定に回す ---
            if name_sim >= 0.75:
                ambiguous.append(MatchPair(i, j, f"名前の類似度 {name_sim:.2f}"))
            elif kana_a and kana_a == kana_b:
                ambiguous.append(MatchPair(i, j, "フリガナが一致（他の項目は不一致）"))
            elif phone_a and phone_a == phone_b:
                ambiguous.append(MatchPair(i, j, "電話番号のみ一致"))
            elif name_sim >= 0.55 and addr_sim >= 0.7:
                ambiguous.append(
                    MatchPair(i, j, f"名前 {name_sim:.2f}・住所 {addr_sim:.2f} が類似")
                )

    return auto, ambiguous


def build_groups(
    total: int, auto: list[MatchPair], merged_ai: list[MatchPair]
) -> list[list[int]]:
    """確定ペアをUnion-Findで束ね、2件以上のグループのみ返す。"""
    uf = UnionFind(total)
    for pair in auto:
        uf.union(pair.index_a, pair.index_b)
    for pair in merged_ai:
        uf.union(pair.index_a, pair.index_b)

    members: dict[int, list[int]] = {}
    for idx in range(total):
        members.setdefault(uf.find(idx), []).append(idx)
    return [sorted(group) for group in members.values() if len(group) > 1]
