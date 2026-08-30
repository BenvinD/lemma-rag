"""RAG Agent implementation."""

from fastapi import FastAPI

app = FastAPI(title="Lemma RAG", version="0.1.0")


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}
