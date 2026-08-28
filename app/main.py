"""FastAPI アプリ本体。

エンドポイント:
  GET  /                     デモUI
  POST /api/clean            CSVアップロードを処理
  GET  /api/clean/sample     同梱サンプルデータを処理
"""

from __future__ import annotations

import time
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from .pipeline import PipelineError, run_pipeline

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR.parent / "data"

SAMPLES = {
    "customers": DATA_DIR / "sample_customers.csv",
    "facilities": DATA_DIR / "sample_facilities.csv",
}

MAX_UPLOAD_BYTES = 512 * 1024

# Claude API の悪用・コスト暴走を防ぐ簡易レート制限（IPごと・プロセス内カウント）。
# サーバーレス環境ではインスタンス再起動でリセットされるが、デモ用途では十分。
RATE_LIMIT_PER_DAY = 30
_request_log: dict[str, list[float]] = defaultdict(list)

app = FastAPI(title="AIデータクレンジング＆名寄せ デモ", docs_url=None, redoc_url=None)


def _check_rate_limit(request: Request) -> None:
    ip = request.client.host if request.client else "unknown"
    now = time.time()
    _request_log[ip] = [t for t in _request_log[ip] if now - t < 86400]
    if len(_request_log[ip]) >= RATE_LIMIT_PER_DAY:
        raise HTTPException(
            status_code=429,
            detail="デモ版の利用上限（1日30回）に達しました。日を改めてお試しください。",
        )
    _request_log[ip].append(now)


def _run(csv_text: str) -> JSONResponse:
    try:
        return JSONResponse(run_pipeline(csv_text))
    except PipelineError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/")
def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.post("/api/clean")
async def clean_upload(request: Request, file: UploadFile) -> JSONResponse:
    _check_rate_limit(request)
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="ファイルサイズの上限は512KBです")
    for encoding in ("utf-8-sig", "cp932"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(status_code=400, detail="文字コードを判定できません（UTF-8 / Shift_JIS に対応）")
    return _run(text)


@app.get("/api/clean/sample")
def clean_sample(request: Request, name: str = "customers") -> JSONResponse:
    _check_rate_limit(request)
    path = SAMPLES.get(name)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="サンプルが見つかりません")
    return _run(path.read_text(encoding="utf-8-sig"))
