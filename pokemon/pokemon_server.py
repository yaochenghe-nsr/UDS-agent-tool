#!/usr/bin/env python3
"""Pokemon game server — FastAPI with WebSocket real-time sync on port 8888."""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, UploadFile, File, HTTPException
from fastapi.responses import FileResponse
import json, base64, os
from pathlib import Path
from google import genai
from google.genai import types

app = FastAPI()

# ── Data storage ──────────────────────────────────────────────────────────────
DATA_DIR = Path("pokemon_user_data")
DATA_DIR.mkdir(exist_ok=True)

# ── WebSocket broadcast manager ───────────────────────────────────────────────
class SyncManager:
    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, msg: dict):
        payload = json.dumps(msg, ensure_ascii=False)
        dead = []
        for ws in self.connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

mgr = SyncManager()

# ── Static / game page ────────────────────────────────────────────────────────
@app.get("/")
def root():
    return FileResponse("pokemon_english.html")

# ── WebSocket sync endpoint ───────────────────────────────────────────────────
@app.websocket("/ws/sync")
async def ws_sync(websocket: WebSocket):
    await mgr.connect(websocket)
    try:
        while True:
            await websocket.receive_text()   # keep-alive ping from client
    except WebSocketDisconnect:
        mgr.disconnect(websocket)

# ── Photo upload → AI extract learning content ────────────────────────────────
@app.post("/api/upload-photo")
async def upload_photo(file: UploadFile = File(...)):
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=500, detail="未配置 GEMINI_API_KEY")

    image_bytes = await file.read()
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片过大，请上传 10MB 以内的图片")

    media_type = file.content_type or "image/jpeg"
    client = genai.Client(api_key=api_key)

    prompt = """请仔细分析这张图片中的英语学习内容（可能是教材页面、单词卡、课文等）。

提取图片中出现的英语单词和句子，生成适合小学生的英语学习内容，并以如下 JSON 格式返回：

{
  "unit": "图片主题（中文）",
  "title": "游戏标题（中文）",
  "subtitle": "英文副标题",
  "level1_words": {
    "english word or phrase": "中文翻译"
  },
  "level2_words": {
    "english word or phrase": "中文翻译"
  },
  "level3_sentences": [
    "Complete English sentence."
  ],
  "fill_blank_items": [
    {
      "sentence_with_blank": "Children need to ___ every day.",
      "answer": "exercise",
      "options": ["exercise", "jump", "stretch", "run"],
      "full_sentence": "Children need to exercise every day."
    }
  ],
  "final_prize": "谜拟丘 (Mimikyu)",
  "final_prize_id": 778
}

要求：
- level1_words 提取 4~6 个基础词汇/短语
- level2_words 提取 4~6 个进阶词汇/短语
- level3_sentences 提取或改写 3~5 个完整英文句子
- fill_blank_items 从 level3_sentences 中选 2~3 个句子，空出一个关键词（用___替换），提供4个选项（含正确答案）
- 所有内容必须来自图片，或与图片主题紧密相关
- 只返回纯 JSON，不要有任何解释文字"""

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=media_type),
                prompt,
            ],
        )
        raw = response.text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        lesson = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"AI 返回格式错误: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 服务错误: {e}")

    return lesson

# ── REST API ──────────────────────────────────────────────────────────────────
@app.delete("/api/users/{username}")
async def api_delete_user(username: str):
    f = DATA_DIR / f"{username}.json"
    if f.exists():
        f.unlink()
    await mgr.broadcast({"type": "user_deleted", "username": username})
    return {"ok": True}

@app.get("/api/users")
def api_users():
    result = {}
    for f in DATA_DIR.glob("*.json"):
        try:
            result[f.stem] = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            result[f.stem] = []
    return result

@app.get("/api/gallery/{username}")
def api_get_gallery(username: str):
    f = DATA_DIR / f"{username}.json"
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []

@app.post("/api/gallery/{username}")
async def api_save_gallery(username: str, request: Request):
    body = await request.json()
    (DATA_DIR / f"{username}.json").write_text(
        json.dumps(body, ensure_ascii=False), encoding="utf-8"
    )
    await mgr.broadcast({"type": "gallery_update", "username": username, "gallery": body})
    return {"ok": True}
