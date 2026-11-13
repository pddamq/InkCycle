"""全局配置接口 + 应用主入口。"""
import asyncio

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from .. import db
from ..llm import chat, fetch_models, LLMError

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config")
def get_config():
    cfg = db.get_config()
    key = cfg.get("api_key", "")
    cfg["api_key_masked"] = ("*" * 8 + key[-4:]) if len(key) > 8 else ("*" * len(key))
    cfg["has_key"] = bool(key)
    return cfg


@router.put("/config")
def put_config(body: dict):
    updates = {k: body[k] for k in body if k in db.DEFAULT_CONFIG}
    # 空字符串的 api_key 表示不修改
    if "api_key" in updates and updates["api_key"] in ("", None):
        updates.pop("api_key")
    db.set_config_values(updates)
    return {"ok": True}


@router.post("/config/models")
async def list_models(body: dict = None):
    """拉取当前（或传入临时）配置对应的模型列表。"""
    saved = db.get_config()
    cfg = dict(saved)
    if body:
        if body.get("base_url"):
            cfg["base_url"] = body["base_url"]
        if body.get("api_key"):
            cfg["api_key"] = body["api_key"]
    if not cfg.get("api_key"):
        return {"ok": False, "message": "请先配置 API Key", "models": []}
    try:
        models = await fetch_models(cfg)
        return {"ok": True, "models": models}
    except LLMError as e:
        return {"ok": False, "message": str(e), "models": []}


@router.post("/config/test")
async def test_config(body: dict = None):
    """用当前（或传入临时）配置发一次极小请求。"""
    saved = db.get_config()
    if body:
        tmp = dict(saved)
        for k in ("base_url", "model", "api_key"):
            if body.get(k):
                tmp[k] = body[k]
        db.set_config_values({k: tmp[k] for k in tmp if k in db.DEFAULT_CONFIG})
    cfg = db.get_config()
    if not cfg.get("api_key"):
        return {"ok": False, "message": "请先配置 API Key"}
    try:
        reply = await chat([{"role": "user", "content": "回复“连接成功”两个字"}])
        return {"ok": True, "message": f"连接成功：{reply[:50]}"}
    except LLMError as e:
        return {"ok": False, "message": str(e)}
    finally:
        if body:
            # 还原为保存前的配置
            db.set_config_values({k: saved[k] for k in saved})
