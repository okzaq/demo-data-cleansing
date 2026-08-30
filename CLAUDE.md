# demo-data-cleansing

クラウドワークス応募用ポートフォリオの自主制作デモ。
**架空の要件・架空のデータで作成しており、実案件の納品物ではない**（READMEにも明記済み。外さないこと）。

## 何のデモか

表記揺れだらけの顧客/施設CSVを 3段階で処理する:

1. **ルールベース整形**（`app/normalize.py`）— NFKC・空白・㈱表記・住所の丁目番地・電話/郵便番号の統一。決定的に直せるものはAIに投げない
2. **ルール確定の統合**（`app/matching.py`）— メール完全一致などはAIを介さず統合
3. **曖昧ペアのみAI判定**（`app/ai_judge.py`）— Claude API（Haiku）で判定。確信度 0.85 以上で統合、0.5〜0.85 は「保留」として人間の確認に回す

「AI任せにせず、ルール＋AI判定＋人間の最終確認」という設計自体が営業上の主張。この構造を崩す変更はしない。

## 制約

- **デモの入力上限 500 行・アップロード 512KB・IPごと 30回/日**（コスト暴走防止。緩めない）
- モデルは **claude-haiku-4-5 固定**（デモのコスト最優先。判定精度向上のためのモデル変更は要相談）
- `ANTHROPIC_API_KEY` 未設定なら**モック判定**で動く（`_mock_judge`）。ローカル開発はキーなしで行い、実APIの確認は明示的に指示されたときだけ
- サンプルデータ（`data/*.csv`）はすべて架空。実在の人名・法人・住所を入れない

## 開発

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload   # http://localhost:8000
python -m pytest tests/ -q      # パイプラインのテスト（APIキー不要・モックで走る）
```

## デプロイ

Vercel（FastAPIフレームワーク自動検出）。ルート直下の `main.py` がエントリポイント。
環境変数 `ANTHROPIC_API_KEY`（IDリンク型キーなら `ANTHROPIC_WORKSPACE_ID` も）は Vercel の Project Settings に設定する。
