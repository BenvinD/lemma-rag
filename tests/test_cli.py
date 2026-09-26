"""End-to-end: manifest -> `lemma ingest` -> JSONL -> `lemma inspect`."""

from pathlib import Path

import pytest

from lemma_rag.cli import main
from lemma_rag.ingest.corpus import extract_sphinx_main
from lemma_rag.ingest.inspector import render_stats, sample_chunks
from lemma_rag.ingest.models import ManifestEntry, SourceFormat
from lemma_rag.ingest.pipeline import MANIFEST_NAME, read_chunks, write_jsonl

MARKDOWN = "# Paths\n\nPath parameters are declared in the route.\n\n## Order\n\nOrder matters.\n"
HTML = (
    '<html><body><div role="main"><h1>json</h1>'
    "<p>The json module encodes and decodes JSON.</p>"
    "<h2>Basic usage</h2><p>Call <code>json.dumps</code> to encode.</p></div></body></html>"
)


def _entry(doc_id: str, fmt: SourceFormat, path: str) -> ManifestEntry:
    source = doc_id.split(":")[0]
    return ManifestEntry(
        doc_id=doc_id,
        source=source,
        format=fmt,
        url=f"https://example.com/{path}",
        title=doc_id,
        path=Path(path),
        sha256=doc_id.ljust(64, "0"),
    )


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    (raw / "fastapi").mkdir(parents=True)
    (raw / "pydocs").mkdir()
    (raw / "fastapi" / "paths.md").write_text(MARKDOWN)
    (raw / "pydocs" / "json.html").write_text(extract_sphinx_main(HTML)[1])
    write_jsonl(
        raw / MANIFEST_NAME,
        [
            _entry("fastapi:paths", SourceFormat.MARKDOWN, "fastapi/paths.md"),
            _entry("pydocs:json", SourceFormat.HTML, "pydocs/json.html"),
        ],
    )
    (tmp_path / "ingest.toml").write_text(
        f'raw_dir = "{raw}"\n'
        f'parsed_dir = "{tmp_path / "parsed"}"\n'
        f'chunks_path = "{tmp_path / "chunks.jsonl"}"\n'
        "[chunking]\nchunk_size = 200\nchunk_overlap = 20\n"
    )
    return tmp_path


def test_ingest_then_inspect(workspace: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = str(workspace / "ingest.toml")
    assert main(["ingest", "--config", config]) == 0

    chunks = list(read_chunks(workspace / "chunks.jsonl"))
    by_doc = {(c.doc_id, tuple(c.heading_path)): c.text for c in chunks}
    assert by_doc == {
        ("fastapi:paths", ("Paths",)): "Path parameters are declared in the route.",
        ("fastapi:paths", ("Paths", "Order")): "Order matters.",
        ("pydocs:json", ("json",)): "The json module encodes and decodes JSON.",
        # Inline code stays inside its sentence.
        ("pydocs:json", ("json", "Basic usage")): "Call `json.dumps` to encode.",
    }
    assert all(c.pages == [] for c in chunks)
    # Parses are cached for the next run.
    assert len(list((workspace / "parsed").glob("*.json"))) == 2

    capsys.readouterr()
    assert main(["inspect", "--config", config, "-n", "2", "--seed", "7"]) == 0
    out = capsys.readouterr().out
    assert out.count("=" * 80) == 3  # two chunks + footer
    assert "seed 7" in out
    assert "chunks: 4  documents: 2" in out


def test_ingest_source_filter(workspace: Path) -> None:
    assert main(["ingest", "--config", str(workspace / "ingest.toml"), "--source", "pydocs"]) == 0
    assert {c.source for c in read_chunks(workspace / "chunks.jsonl")} == {"pydocs"}


def test_failed_document_is_reported_and_exits_nonzero(
    workspace: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (workspace / "raw" / "pydocs" / "json.html").unlink()
    assert main(["ingest", "--config", str(workspace / "ingest.toml")]) == 1
    assert "pydocs:json" in capsys.readouterr().err
    # The healthy document is still written.
    assert {c.doc_id for c in read_chunks(workspace / "chunks.jsonl")} == {"fastapi:paths"}


def test_sampling_is_deterministic(workspace: Path) -> None:
    main(["ingest", "--config", str(workspace / "ingest.toml")])
    chunks = list(read_chunks(workspace / "chunks.jsonl"))
    assert sample_chunks(chunks, 2, seed=1) == sample_chunks(chunks, 2, seed=1)
    assert len(sample_chunks(chunks, 50, seed=1)) == len(chunks)


def test_stats_flag_tiny_and_oversized_chunks(workspace: Path) -> None:
    main(["ingest", "--config", str(workspace / "ingest.toml")])
    stats = render_stats(list(read_chunks(workspace / "chunks.jsonl")), chunk_size=20)
    assert "tiny (<100 chars): 4" in stats
    assert "over chunk_size (20): 3" in stats
    assert render_stats([]) == "no chunks"
