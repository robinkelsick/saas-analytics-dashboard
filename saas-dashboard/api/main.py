import os
from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="SaaS Analytics API")

@app.get("/health")
def health():
    return {"status": "ok"}
