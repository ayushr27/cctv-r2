import time
from fastapi import FastAPI

_start_time = time.time()

app = FastAPI(title="Store Intelligence API", version="0.1.0")


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": "0.1.0",
        "uptime_seconds": int(time.time() - _start_time),
    }
