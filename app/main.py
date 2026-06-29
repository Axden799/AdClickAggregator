from fastapi import FastAPI

from app.routers import health

app = FastAPI(title="Ad Click Aggregator")

app.include_router(health.router)
