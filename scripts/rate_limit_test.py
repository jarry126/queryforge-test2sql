"""验证 slowapi 限流 / 在途并发保护效果。

先把 RATE_LIMIT_QUERY 临时调小，例如：
RATE_LIMIT_QUERY=5/minute make run

再运行：
python -m scripts.rate_limit_test --requests 20
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections import Counter

import httpx

from app.core.security import create_access_token

DEFAULT_URL = "http://localhost:8000/api/v1/query"
DEFAULT_PAYLOAD = {"question": "我们有多少歌手？", "db_id": "concert_singer"}


async def _one(
    client: httpx.AsyncClient,
    url: str,
    payload: dict,
    token: str | None = None,
) -> tuple[int, float, str]:
    t0 = time.perf_counter()
    try:
        headers = {"Authorization": f"Bearer {token}"} if token else None
        resp = await client.post(url, json=payload, headers=headers)
        detail = ""
        if resp.status_code != 200:
            try:
                detail = str(resp.json().get("detail", ""))[:120]
            except Exception:  # noqa: BLE001
                detail = resp.text[:120]
        return resp.status_code, time.perf_counter() - t0, detail
    except Exception as exc:  # noqa: BLE001
        return 0, time.perf_counter() - t0, str(exc)[:120]


async def run(
    url: str,
    requests: int,
    concurrency: int,
    token: str | None,
    users: int,
    question: str,
    db_id: str,
) -> None:
    payload = {"question": question, "db_id": db_id}
    limits = httpx.Limits(max_connections=max(concurrency * 2, 10), max_keepalive_connections=max(concurrency, 10))
    sem = asyncio.Semaphore(concurrency)
    tokens = _tokens(token, users)

    async with httpx.AsyncClient(timeout=60.0, limits=limits) as client:
        async def guarded(i: int) -> tuple[int, float, str]:
            async with sem:
                return await _one(client, url, payload, tokens[i % len(tokens)] if tokens else None)

        start = time.perf_counter()
        results = await asyncio.gather(*[asyncio.create_task(guarded(i)) for i in range(requests)])
        wall = time.perf_counter() - start

    counts = Counter(status for status, _lat, _detail in results)
    latencies = [lat for _status, lat, _detail in results]
    examples = [detail for status, _lat, detail in results if status != 200 and detail][:3]

    print("\n===== 限流测试结果 =====")
    print(f"URL         : {url}")
    print(f"请求数      : {requests}")
    print(f"并发数      : {concurrency}")
    print(f"模拟用户数  : {users if users > 0 else 0}")
    print(f"耗时        : {wall:.2f}s")
    print(f"状态码      : {dict(sorted(counts.items()))}")
    print(f"429 数量    : {counts.get(429, 0)}")
    print(f"503 数量    : {counts.get(503, 0)}")
    if latencies:
        print(f"平均时延    : {sum(latencies) / len(latencies) * 1000:.0f} ms")
        print(f"最大时延    : {max(latencies) * 1000:.0f} ms")
    if examples:
        print("非 200 示例 :")
        for item in examples:
            print(f"  - {item}")


def _tokens(token: str | None, users: int) -> list[str]:
    if token:
        return [token]
    if users <= 0:
        return []
    return [create_access_token(i + 1, f"loadtest_user_{i + 1}") for i in range(users)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--token", default=None, help="Bearer token；PUBLIC_QUERY_ENABLED=false 时需要")
    parser.add_argument("--users", type=int, default=0, help="生成 N 个本地 JWT 模拟 N 个登录用户")
    parser.add_argument("--question", default=DEFAULT_PAYLOAD["question"])
    parser.add_argument("--db-id", default=DEFAULT_PAYLOAD["db_id"])
    args = parser.parse_args()
    asyncio.run(run(args.url, args.requests, args.concurrency, args.token, args.users, args.question, args.db_id))
