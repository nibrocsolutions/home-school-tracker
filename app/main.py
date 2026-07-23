import time

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError

from app.database import Base, SessionLocal, engine
from app.media_library import ensure_default_media_folders
from app.routers import pages
from app.seed import seed_database

app = FastAPI(title="Home School Tracker", version="1.0.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(pages.router)


def init_db(retries: int = 30, delay: float = 2.0) -> None:
    for attempt in range(retries):
        try:
            Base.metadata.create_all(bind=engine)
            db = SessionLocal()
            try:
                seed_database(db)
            finally:
                db.close()
            ensure_default_media_folders()
            return
        except OperationalError:
            if attempt == retries - 1:
                raise
            time.sleep(delay)


@app.on_event("startup")
def on_startup():
    init_db()
