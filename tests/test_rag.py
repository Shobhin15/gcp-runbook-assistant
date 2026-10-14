from pathlib import Path

import pytest

from app import rag

RUNBOOKS = Path(__file__).resolve().parent.parent / "runbooks"
VOCAB = ["rabbitmq", "queue", "consumer", "crashloopbackoff", "oomkilled", "latency", "slow", "rollback", "deploy", "pipeline"]


def fake_embed(texts, task_type):
    """Bag-of-words vectors over a tiny vocabulary: enough to test ranking without a cloud call."""
    return [[t.lower().count(word) for word in VOCAB] for t in texts]


def test_chunk_markdown_splits_on_headings():
    chunks = rag.chunk_markdown("doc", "# Title\nintro\n## A\none\n## B\ntwo")
    assert [c.text.splitlines()[0] for c in chunks] == ["# Title", "## A", "## B"]
    assert all(c.source == "doc" for c in chunks)


def test_chunk_markdown_caps_long_sections():
    chunks = rag.chunk_markdown("doc", "## Long\n" + "\n".join(["x" * 100] * 30), max_chars=500)
    assert len(chunks) > 1
    assert all(len(c.text) <= 500 for c in chunks)


def test_load_runbooks_reads_every_file():
    chunks = rag.load_runbooks(RUNBOOKS)
    assert {c.source for c in chunks} == {p.stem for p in RUNBOOKS.glob("*.md")}


def test_cosine():
    assert rag.cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert rag.cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert rag.cosine([0, 0], [1, 1]) == 0.0


def test_search_ranks_the_relevant_runbook_first():
    index = rag.RunbookIndex(rag.load_runbooks(RUNBOOKS), fake_embed)
    hits = index.search("rabbitmq queue backing up, consumer slow")
    assert hits[0][0].source == "rabbitmq-queue-backlog"
    hits = index.search("pod in crashloopbackoff, oomkilled")
    assert hits[0][0].source == "pod-crashloopbackoff"


def test_answer_cites_sources_and_grounds_the_prompt():
    index = rag.RunbookIndex(rag.load_runbooks(RUNBOOKS), fake_embed)
    seen = {}

    def fake_generate(system_prompt, user_prompt):
        seen["system"], seen["user"] = system_prompt, user_prompt
        return "Check consumer pods [rabbitmq-queue-backlog]"

    result = rag.answer("rabbitmq queue is growing", index, fake_generate)
    assert result["answer"].startswith("Check consumer pods")
    assert result["sources"][0]["runbook"] == "rabbitmq-queue-backlog"
    assert "ONLY from the runbook" in seen["system"]
    assert "[rabbitmq-queue-backlog]" in seen["user"]


def test_answer_without_matches_escalates_and_skips_the_model():
    index = rag.RunbookIndex(rag.load_runbooks(RUNBOOKS), fake_embed)

    def must_not_be_called(*_):
        raise AssertionError("model should not be called without context")

    result = rag.answer("what is the weather today", index, must_not_be_called)
    assert result["sources"] == []
    assert "escalate" in result["answer"].lower()


def test_answer_rejects_bad_input():
    index = rag.RunbookIndex([], fake_embed)
    with pytest.raises(ValueError):
        rag.answer("   ", index, lambda *_: "")
    with pytest.raises(ValueError):
        rag.answer("x" * 1001, index, lambda *_: "")
