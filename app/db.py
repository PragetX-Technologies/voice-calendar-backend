"""
Mongo connection, lazily initialized and cached across requests — same
singleton pattern as the CalDAV client in caldav_service.py.
"""
from pymongo import MongoClient
from pymongo.database import Database

from app.config import settings

_client: MongoClient | None = None


def get_db() -> Database:
    global _client
    if _client is None:
        _client = MongoClient(settings.mongodb_uri)
    return _client[settings.mongodb_db_name]
