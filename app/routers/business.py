"""
Endpoints for the frontend's onboarding/settings pages: stores the signed-in
business owner's profile (contact details, hours, job types). Scoped to the
caller's account via require_account_id — see business_service.py.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException

from app import business_service
from app.auth import require_account_id
from app.business_schemas import BusinessProfile

logger = logging.getLogger("business")

router = APIRouter(prefix="/business", tags=["business"])


@router.get("/profile")
def get_profile(account_id: str = Depends(require_account_id)):
    profile = business_service.get_profile(account_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="No business profile set up yet")
    return profile


@router.put("/profile")
def save_profile(payload: BusinessProfile, account_id: str = Depends(require_account_id)):
    try:
        return business_service.save_profile(account_id, payload)
    except Exception as e:
        logger.exception("save_profile failed")
        raise HTTPException(status_code=400, detail=f"{type(e).__name__}: {e}")
