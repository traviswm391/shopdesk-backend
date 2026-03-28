from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import shops, calls, webhooks, admin
import logging

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="ShopDesk AI API",
    description="AI Receptionist backend for mechanic shops",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://shopdesk-dashboard.vercel.app",
        "http://localhost:3000"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(shops.router)
app.include_router(calls.router)
app.include_router(webhooks.router)
app.include_router(admin.router)


@app.get("/")
async def root():
    return {"status": "ShopDesk AI backend is running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
