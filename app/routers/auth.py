import logging

from fastapi import APIRouter, Depends, HTTPException

from app import accounts_service
from app.auth import create_access_token, require_account_id
from app.auth_schemas import AccountResponse, LoginRequest, SignupRequest, TokenResponse

logger = logging.getLogger("auth")

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=TokenResponse)
def signup(payload: SignupRequest):
    try:
        account = accounts_service.create_account(payload.email, payload.password)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return TokenResponse(access_token=create_access_token(account["_id"]))


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest):
    account = accounts_service.authenticate(payload.email, payload.password)
    if account is None:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return TokenResponse(access_token=create_access_token(account["_id"]))


@router.get("/me", response_model=AccountResponse)
def me(account_id: str = Depends(require_account_id)):
    account = accounts_service.get_account(account_id)
    if account is None:
        raise HTTPException(status_code=401, detail="Account no longer exists")
    return AccountResponse(id=account["_id"], email=account["email"])
