"""终端测试 LangGraph Human-in-the-loop interrupt。

用法：
    python -m scripts.hil_terminal --db concert_singer --question "我们有多少歌手？"

说明：
- 该脚本使用 InMemorySaver，只用于本地测试 interrupt/resume；
- 不影响 FastAPI 默认链路；
- 图会在 generate_sql 后暂停，等待人工 approve/edit/reject。
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.core.langgraph.graph import build_graph


def _print_review(payload: dict) -> None:
    print("\n===== 人工审核 SQL =====")
    print(f"db_id    : {payload.get('db_id')}")
    print(f"question : {payload.get('question')}")
    print(f"attempt  : {payload.get('attempt')}")
    print("\n生成 SQL:")
    print(payload.get("sql") or "（空）")
    print("\n操作:")
    print("  a / approve  直接通过")
    print("  e / edit     修改 SQL 后继续")
    print("  r / reject   拒绝执行，直接结束")


def _ask_decision() -> dict:
    choice = input("\n请选择操作 [a/e/r]: ").strip().lower()
    if choice in {"", "a", "approve"}:
        return {"action": "approve"}
    if choice in {"e", "edit"}:
        print("请输入修改后的 SQL，单行输入：")
        sql = input("> ").strip()
        return {"action": "edit", "sql": sql}
    if choice in {"r", "reject"}:
        reason = input("拒绝原因（可空）: ").strip() or "人工拒绝执行"
        return {"action": "reject", "reason": reason}
    print("未知输入，默认按 reject 处理。")
    return {"action": "reject", "reason": f"未知审核操作: {choice}"}


def _extract_interrupt(chunk: Any) -> dict | None:
    """从 LangGraph stream chunk 中取出 interrupt payload。

    当某个节点执行了 interrupt({...})，LangGraph 不会继续往后跑，
    而是在 stream 里吐出：

        {"__interrupt__": (Interrupt(value={...}),)}

    这里把 Interrupt.value 取出来，返回给终端展示。
    如果当前 chunk 不是中断事件，返回 None。
    """
    if not isinstance(chunk, dict) or "__interrupt__" not in chunk:
        return None
    interrupts = chunk["__interrupt__"]
    if not interrupts:
        return {}
    first = interrupts[0]
    return first.value if hasattr(first, "value") else first


async def _run_until_interrupt_or_done(graph, payload: Any, config: dict) -> dict | None:
    """运行图，直到遇到 interrupt 或图自然结束。

    payload 有两种：
    1. 第一次调用：传入 init_state，图从 START 开始跑；
    2. 恢复调用：传入 Command(resume=decision)，图从上次 interrupt 的节点恢复。

    返回值：
    - dict：遇到了 interrupt，dict 是节点传给 interrupt({...}) 的 payload；
    - None：没有遇到 interrupt，说明图已经跑完。
    """
    print("\n[Graph] 开始/继续执行，等待节点输出...")
    async for chunk in graph.astream(payload, config=config, stream_mode="updates"):
        review = _extract_interrupt(chunk)
        if review is not None:
            print("[Interrupt] 图在 human_review_sql 节点暂停，等待人工输入。")
            return review
        for node_name, update in chunk.items():
            if node_name == "__interrupt__":
                continue
            if isinstance(update, dict):
                summary = []
                if update.get("sql"):
                    summary.append(f"sql={update['sql']}")
                if update.get("error"):
                    summary.append(f"error={update['error']}")
                if update.get("success") is not None:
                    summary.append(f"success={update['success']}")
                suffix = " | " + " | ".join(summary) if summary else ""
                print(f"[{node_name}]{suffix}")
            else:
                print(f"[{node_name}] {update}")
    return None


async def run(question: str, db_id: str, thread_id: str | None = None) -> None:
    """运行一次终端版 Human-in-the-loop Text-to-SQL。

    整体流程：

    1. 构建一个临时 graph：
       build_graph(checkpointer=InMemorySaver(), enable_hil=True)

       - enable_hil=True 会把链路变成：
         generate_sql -> human_review_sql -> validate_sql

       - InMemorySaver 是 checkpointer。
         interrupt 必须要有 checkpointer，因为图暂停后需要保存现场。

    2. 第一次执行：
       _run_until_interrupt_or_done(graph, init_state, config)

       图从 START 开始跑，直到 human_review_sql 节点里的 interrupt({...})。
       这个 interrupt 的 payload 会作为 review 返回。

    3. 人工选择：
       approve / edit / reject

    4. 恢复执行：
       _run_until_interrupt_or_done(graph, Command(resume=decision), config)

       Command(resume=...) 会把人的选择传回 interrupt(...) 那一行。
       恢复时必须使用同一个 config.thread_id，否则 LangGraph 找不到上次暂停的现场。

    5. 图继续向后跑：
       validate_sql -> execute_sql -> format_answer
    """
    print("\n===== HIL 终端测试启动 =====")

    # 构建一个专门用于终端测试的临时图。
    # 注意：这里不调用 get_graph()，因为 get_graph() 是默认 API 使用的全局图；
    # 这个脚本要强制开启 HIL，所以直接 build_graph(enable_hil=True)。
    graph = build_graph(checkpointer=InMemorySaver(), enable_hil=True)

    # thread_id 是 LangGraph 找回 checkpoint 的关键。
    # 第一次执行和后续 Command(resume=...) 必须使用同一个 thread_id。
    current_thread_id = thread_id or f"hil-terminal-{uuid.uuid4().hex}"
    config = {
        "recursion_limit": 25,
        "configurable": {"thread_id": current_thread_id},
    }

    # init_state 是图的初始输入。
    # 这一次会从 START 开始执行：
    # detect_language -> rewrite -> expand -> retrieve -> schema_linking -> generate_sql -> human_review_sql
    init_state = {"question": question, "db_id": db_id, "attempt": 0, "history": []}

    print(f"thread_id: {current_thread_id}")
    print(f"db_id    : {db_id}")
    print(f"question : {question}")

    # 第一次运行：从 START 开始，直到遇到 interrupt 或图结束。
    # 正常情况下会在 human_review_sql 节点暂停，并返回 review payload。
    review = await _run_until_interrupt_or_done(graph, init_state, config)

    # 只要 review 不为空，就说明图暂停了，需要人工输入。
    # 输入完成后，用 Command(resume=decision) 恢复同一个 thread_id 的图执行。
    while review is not None:
        _print_review(review)
        decision = _ask_decision()
        print(f"\n[Resume] 使用 Command(resume={decision}) 恢复图执行。")
        review = await _run_until_interrupt_or_done(graph, Command(resume=decision), config)

    # 图跑完后，从 checkpointer 里取最终 state。
    snapshot = await graph.aget_state(config)
    state = snapshot.values
    print("\n===== 最终结果 =====")
    print(f"success : {state.get('success')}")
    print(f"sql     : {state.get('sql')}")
    print(f"answer  : {state.get('answer')}")
    if state.get("error"):
        print(f"error   : {state.get('error')}")
    result = state.get("sql_result") or {}
    if result.get("columns"):
        print(f"columns : {result.get('columns')}")
        print(f"rows    : {result.get('rows')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="终端测试 LangGraph interrupt 人机交互")
    parser.add_argument("--question", default="我们有多少歌手？")
    parser.add_argument("--db", dest="db_id", default="concert_singer")
    parser.add_argument("--thread-id", default=None)
    args = parser.parse_args()
    asyncio.run(run(args.question, args.db_id, args.thread_id))


if __name__ == "__main__":
    main()
