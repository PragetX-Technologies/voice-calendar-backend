from pydantic import BaseModel, Field


# ---------- Tool webhook schemas (called BY ElevenLabs, mid-conversation) ----------

_PROVIDER_DESC = (
    "'apple' or 'google'; should be set from the {{provider}} dynamic variable "
    "(set at call trigger, same mechanism as phone_number) so the agent doesn't "
    "have to guess which calendar is connected. Falls back to CALENDAR_PROVIDER if omitted."
)


class GetBusinessHoursRequest(BaseModel):
    provider: str | None = Field(None, description=_PROVIDER_DESC)


class ListEventsRequest(BaseModel):
    start_iso: str = Field(..., description="Start of the search window, ISO 8601, e.g. 2026-07-25T00:00:00")
    end_iso: str = Field(..., description="End of the search window, ISO 8601, e.g. 2026-07-26T00:00:00")
    provider: str | None = Field(None, description=_PROVIDER_DESC)


class CreateEventRequest(BaseModel):
    summary: str = Field(..., description="Short title, e.g. 'Plumbing appointment - leaky faucet'")
    start_iso: str = Field(..., description="Appointment start, ISO 8601, e.g. 2026-07-25T14:00:00")
    end_iso: str = Field(..., description="Appointment end, ISO 8601, e.g. 2026-07-25T15:00:00")
    description: str = Field("", description="Extra notes, e.g. issue details")
    location: str = Field("", description="Address or location of the appointment")
    provider: str | None = Field(None, description=_PROVIDER_DESC)
    phone_number: str | None = Field(None, description="Caller's phone number (dynamic variable from call trigger), used as SMS recipient")
    email: str | None = Field(None, description="Unused — email now hardcoded server-side via settings.user_email; agent no longer collects it")
    price_estimate: str | None = Field(None, description="Spoken price range for the issue, e.g. '$150 to $400', to include in SMS/email confirmation")


class UpdateEventRequest(BaseModel):
    uid: str = Field(..., description="The unique id of the event to update (returned from create/list)")
    summary: str | None = None
    start_iso: str | None = None
    end_iso: str | None = None
    description: str | None = None
    location: str | None = None
    provider: str | None = Field(None, description=_PROVIDER_DESC)
    phone_number: str | None = Field(None, description="Caller's phone number (dynamic variable from call trigger), used as SMS recipient")
    email: str | None = Field(None, description="Unused — email now hardcoded server-side via settings.user_email; agent no longer collects it")


class DeleteEventRequest(BaseModel):
    uid: str = Field(..., description="The unique id of the event to delete")
    provider: str | None = Field(None, description=_PROVIDER_DESC)
    phone_number: str | None = Field(None, description="Caller's phone number (dynamic variable from call trigger), used as SMS recipient")
    email: str | None = Field(None, description="Unused — email now hardcoded server-side via settings.user_email; agent no longer collects it")


# ---------- Call trigger schema (called BY your backend, TO ElevenLabs) ----------

class TriggerCallRequest(BaseModel):
    to_number: str = Field(..., description="Phone number to call, E.164 format e.g. +919812345678")
    customer_name: str | None = Field(None, description="Passed to the agent as a dynamic variable")
    reason: str | None = Field(None, description="e.g. 'Follow-up on plumbing quote request', passed as dynamic variable")
    provider: str | None = Field(None, description="'apple' or 'google'; picks which agent places the call. Defaults to CALENDAR_PROVIDER if omitted")
    purpose: str = Field("booking", description="'booking' (Aura) or 'reminder' (Echo) — picks which of the two agents/phone numbers places the call")
