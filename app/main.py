"""FastAPI application with Gradio mounted at /ui."""

from __future__ import annotations

from contextlib import asynccontextmanager

import gradio as gr
from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from app.api.routes import router
from app.config import get_settings
from app.database import get_session_factory, init_db
from app.models.entities import Product
from app.seed.demo_data import seed_database
from app.ui.gradio_app import build_ui
from app.utils.logging import configure_logging


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    init_db()
    session = get_session_factory()()
    try:
        if session.query(Product).count() == 0:
            seed_database(session)
    finally:
        session.close()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="AI Purchasing Agent",
        description="Purchasing copilot with an optional LangChain decision agent and deterministic safety gates.",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )
    app.include_router(router, prefix="/api")

    @app.get("/")
    def root() -> RedirectResponse:
        return RedirectResponse(url="/ui")

    demo = build_ui()
    gr.mount_gradio_app(app, demo, path="/ui")
    app.state.settings = settings
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)
