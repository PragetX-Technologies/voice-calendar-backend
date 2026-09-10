"""
JWT bearer-token auth for business owner accounts. Every business/oauth
endpoint depends on require_account_id to scope data to the caller's account.
"""
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings

_JWT_ALGORITHM = "HS256"

_bearer = HTTPBearer(auto_error=False)


def create_access_token(account_id: str) -> str:
    payload = {
        "sub": account_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


def decode_account_id(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail="Invalid or expired token") from e
    return payload["sub"]


def require_account_id(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return decode_account_id(credentials.credentials)
