import asyncio
import json

from app.api.v1 import sessions
from app.schemas.query import HistoryTurn, QueryRequest
from app.services.stream_events import QueryStreamEvent, encode_sse, events_after_node, plan_event
from app.services.text2sql import run_query_stream


def _data(frame: str) -> dict:
    data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
    return json.loads(data_line.removeprefix("data: "))


def test_plan_contains_stable_user_facing_steps():
    event = plan_event()

    assert event.name == "plan"
    assert [step["stage"] for step in event.data["steps"]] == [
        "understand",
        "retrieve",
        "generate_sql",
        "execute_sql",
        "format_answer",
    ]


def test_retrieve_event_only_exposes_counts():
    events = events_after_node(
        "retrieve",
        {
            "schema_docs": [{"content": "secret schema"}, {"content": "another secret"}],
            "fewshots": [{"sql": "SELECT secret"}],
        },
        max_retries=2,
    )

    assert events[0].name == "progress"
    assert events[0].data["details"] == {"schema_documents": 2, "examples": 1}
    assert "secret" not in str(events[0].data)


def test_validation_failure_is_reported_as_retry_without_raw_error():
    events = events_after_node(
        "validate_sql",
        {"error": "database password leaked in raw exception"},
        max_retries=2,
    )

    assert events[0].data["status"] == "retrying"
    assert "password" not in str(events[0].data)


def test_sse_frame_is_single_json_line_and_has_sequence():
    frame = encode_sse(QueryStreamEvent("progress", {"message": "第一行\n第二行"}), 7)

    assert frame.startswith("id: 7\nevent: progress\n")
    assert frame.endswith("\n\n")
    assert len([line for line in frame.splitlines() if line.startswith("data: ")]) == 1
    assert _data(frame)["sequence"] == 7


async def test_run_query_stream_emits_real_node_progress_and_final_result(monkeypatch):
    class FakeGraph:
        async def astream(self, *_args, **_kwargs):
            yield "values", {"question": "测试", "db_id": "demo", "attempt": 0}
            yield (
                "updates",
                {
                    "retrieve": {
                        "schema_docs": [{"content": "private schema"}],
                        "fewshots": [{"sql": "SELECT private"}],
                    }
                },
            )
            yield (
                "updates",
                {
                    "execute_sql": {
                        "sql_result": {
                            "ok": True,
                            "columns": ["count"],
                            "rows": [[3]],
                            "row_count": 1,
                        }
                    }
                },
            )
            yield "updates", {"format_answer": {"answer": "共有 3 条记录"}}
            yield (
                "values",
                {
                    "question": "测试",
                    "db_id": "demo",
                    "sql": "SELECT COUNT(*) AS count FROM demo",
                    "success": True,
                    "answer": "共有 3 条记录",
                    "language": "zh",
                    "attempt": 0,
                    "sql_result": {
                        "ok": True,
                        "columns": ["count"],
                        "rows": [[3]],
                        "row_count": 1,
                    },
                },
            )

    async def fake_get_graph():
        return FakeGraph()

    monkeypatch.setattr("app.services.text2sql.get_graph", fake_get_graph)
    monkeypatch.setattr("app.services.text2sql.get_langfuse_handler", lambda: None)
    request = QueryRequest(
        question="测试",
        db_id="demo",
        thread_id="test-thread",
        history=[HistoryTurn(role="user", content="上一轮")],
    )

    events = [event async for event in run_query_stream(request)]

    assert [event.name for event in events[:3]] == ["meta", "plan", "progress"]
    assert any(
        event.name == "progress" and event.data["stage"] == "execute_sql" and event.data["status"] == "completed"
        for event in events
    )
    assert events[-1].name == "result"
    assert events[-1].data["answer"] == "共有 3 条记录"
    assert "private schema" not in str(events)


async def test_stream_heartbeat_does_not_cancel_pending_graph_event(monkeypatch):
    monkeypatch.setattr(sessions, "_STREAM_HEARTBEAT_SECONDS", 0.001)

    async def delayed_events():
        await asyncio.sleep(0.01)
        yield QueryStreamEvent("progress", {"message": "真实节点已完成"})

    events = [event async for event in sessions._stream_with_heartbeat(delayed_events())]

    assert any(event.name == "heartbeat" for event in events)
    assert events[-1].name == "progress"
