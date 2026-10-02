"""Kết nối MongoDB dùng chung cho tiến trình (PyMongo đồng bộ — hợp gevent sau monkey-patch)."""
from __future__ import annotations

from pymongo import MongoClient
from pymongo.database import Database

from app.config.settings import get_settings

_client: MongoClient | None = None


def get_client() -> MongoClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = MongoClient(
            s.MONGO_URI,
            w="majority",
            retryWrites=True,
            appname="platform-core",
            serverSelectionTimeoutMS=15000,
            tz_aware=True,
        )
    return _client


def get_db() -> Database:
    return get_client()[get_settings().MONGO_DB]
