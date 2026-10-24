from fastapi import FastAPI

from app.modules import load_all


def create_app() -> FastAPI:
    load_all()
    app = FastAPI(title="saylist")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
