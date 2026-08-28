"""Vercel サーバーレス関数のエントリポイント。

Vercel の Python ランタイムは ASGI アプリ変数 `app` を検出して起動する。
実体は app/main.py の FastAPI アプリ。
"""

from app.main import app  # noqa: F401
