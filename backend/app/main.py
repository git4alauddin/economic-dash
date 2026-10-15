"""Application entrypoint; indicator routes are added in later modules."""

from fastapi import FastAPI

app = FastAPI(title="Economic Indicators API", version="0.1.0")


@app.get("/")
def index() -> dict[str, str]:
    """Return a bootstrap response, separate from the future health contract."""
    return {"message": "Economic Indicators API"}
