"""RAG Agent implementation."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Lemma RAG",
        version="0.1.0",
        description="Enterprise RAG with hybrid search and bidirectional guardrails",
    )

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "healthy"}

    return app


app = create_app()
