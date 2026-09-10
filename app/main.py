import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.reminder_job import run_reminder_sweep
from app.routers import auth, business, calendar_view, calls, oauth, sms, tools

logging.basicConfig(level=logging.INFO)

scheduler = BackgroundScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(run_reminder_sweep, "interval", minutes=15, id="reminder_sweep")
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(
    title="Voice Agent x Apple Calendar Backend",
    description="Backend connecting an ElevenLabs voice agent to a user's Apple (iCloud) Calendar via CalDAV.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "https://voice-calendar.netlify.app"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(calls.router)
app.include_router(tools.router)
app.include_router(calendar_view.router)
app.include_router(sms.router)
app.include_router(business.router)
app.include_router(oauth.router)
app.include_router(auth.router)


@app.get("/health")
def health():
    return {"status": "ok"}
