"""SimpleSpecs backend entrypoint."""
from fastapi import FastAPI

app = FastAPI(title="SimpleSpecs", version="0.0.1")


@app.get("/api/health")
def read_health() -> dict[str, bool]:
    """Health check endpoint returning a simple ok response."""
    return {"ok": True}
