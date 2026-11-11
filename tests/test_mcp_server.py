from pathlib import Path

import pytest

from app import agent, mcp_server, rag, tools

RUNBOOKS = Path(__file__).resolve().parent.parent / "runbooks"
VOCAB = ["rabbitmq", "queue", "consumer", "crashloopbackoff", "oomkilled", "latency", "slow", "rollback", "deploy", "pipeline"]


def fake_embed(texts, task_type):
    return [[t.lower().count(word) for word in VOCAB] for t in texts]


def fake_status_tool(calls):
    def cloud_run_status(service):
        service = agent.check_service(service, None)
        calls.append(service)
        return {"service": service, "ready": "CONDITION_SUCCEEDED"}

    return agent.Tool("cloud_run_status", "status", {"service": agent.Param("string", "name")}, cloud_run_status)


def test_server_exposes_the_same_tools_as_the_agent():
    index = rag.RunbookIndex(rag.load_runbooks(RUNBOOKS), fake_embed)
    names = {t.name for t in tools.default_tools(index, "proj", "us-central1")}
    handlers = mcp_server.make_handlers(tools.default_tools(index, "proj", "us-central1"))
    assert set(handlers) == names == {"search_runbooks", "recent_error_logs", "cloud_run_status"}


def test_runbook_search_works_through_the_handler():
    index = rag.RunbookIndex(rag.load_runbooks(RUNBOOKS), fake_embed)
    handlers = mcp_server.make_handlers([tools.runbook_tool(index)])
    result = handlers["search_runbooks"](query="rabbitmq queue consumer backlog")
    assert result["runbooks"][0] == "rabbitmq-queue-backlog"


def test_handlers_validate_arguments_before_calling_the_tool():
    calls = []
    handlers = mcp_server.make_handlers([fake_status_tool(calls)])
    with pytest.raises(ValueError):
        handlers["cloud_run_status"](service="orders", force=True)   # unknown argument
    with pytest.raises(ValueError):
        handlers["cloud_run_status"]()                               # missing argument
    with pytest.raises(ValueError):
        handlers["cloud_run_status"](service='orders" OR severity>=DEBUG')  # filter injection
    assert calls == []
    assert handlers["cloud_run_status"](service="Orders")["service"] == "orders"


def test_optional_arguments_left_unset_use_the_tool_default():
    seen = {}

    def logs(service, minutes=30):
        seen["minutes"] = minutes
        return {"ok": True}

    tool = agent.Tool("recent_error_logs", "logs", {
        "service": agent.Param("string", "name"),
        "minutes": agent.Param("integer", "window", required=False),
    }, logs)
    mcp_server.make_handlers([tool])["recent_error_logs"](service="orders", minutes=None)
    assert seen["minutes"] == 30


def test_large_output_is_truncated():
    big = agent.Tool("search_runbooks", "s", {"query": agent.Param("string", "q")}, lambda query: {"text": "x" * 10000})
    result = mcp_server.make_handlers([big])["search_runbooks"](query="x")
    assert result["truncated"] is True


def test_fastmcp_server_registers_the_three_tools():
    pytest.importorskip("mcp")  # installed in CI from requirements-mcp.txt
    import asyncio

    server = mcp_server.build_server()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"search_runbooks", "recent_error_logs", "cloud_run_status"}


def test_every_mcp_tool_is_marked_read_only():
    pytest.importorskip("mcp")
    import asyncio

    def hint(annotations, snake, camel):  # mcp 2.x uses snake_case attributes, 1.x camelCase
        return getattr(annotations, snake, None) if hasattr(annotations, snake) else getattr(annotations, camel)

    for tool in asyncio.run(mcp_server.build_server().list_tools()):
        assert hint(tool.annotations, "read_only_hint", "readOnlyHint") is True
        assert hint(tool.annotations, "destructive_hint", "destructiveHint") is False
