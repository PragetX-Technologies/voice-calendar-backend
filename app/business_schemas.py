from pydantic import BaseModel, Field


class CalendarConnection(BaseModel):
    account: str


class DayHours(BaseModel):
    enabled: bool
    start: str  # "HH:MM"
    end: str  # "HH:MM"


class BusinessProfile(BaseModel):
    business_name: str = Field(..., alias="businessName")
    mobile: str = Field(..., description="E.164, the number customers call")
    email: str
    connections: dict[str, CalendarConnection] = Field(default_factory=dict)  # "google" / "apple" -> account
    hours: dict[str, DayHours] = Field(default_factory=dict)  # "Mon".."Sun" -> hours
    job_types: list[str] = Field(default_factory=list, alias="jobTypes")

    model_config = {"populate_by_name": True}
