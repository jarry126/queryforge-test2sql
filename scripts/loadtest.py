"""开环压测：以固定 QPS 打 /query，统计时延分位与吞吐.

开环（open-loop）模型：按目标 RPS 定时发起请求，不等上一个返回，
真实反映服务在 100 QPS 下的排队与时延表现。

运行：
    python -m scripts.loadtest --rps 100 --duration 30
    python -m scripts.loadtest --rps 100 --duration 30 --url http://localhost:8000/api/v1/query

问题样本优先取 CSpider dev（命中缓存更真实）；取不到则用内置样本。
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import time
from collections import Counter

import httpx

DEFAULT_URL = "http://localhost:8000/api/v1/query"
FALLBACK_SAMPLES = [
    {"question": "我们有多少歌手？", "db_id": "concert_singer"},
    {"question": "列出所有歌手的名字和国籍", "db_id": "concert_singer"},
    {"question": "按容量降序列出所有体育场", "db_id": "concert_singer"},
]


def _load_samples(limit: int) -> list[dict]:
    try:
        from eval.cspider_loader import load_examples

        ex = load_examples("dev")
        random.shuffle(ex)
        return [{"question": e["question"], "db_id": e["db_id"]} for e in ex[:limit]]
    except Exception:
        return FALLBACK_SAMPLES


async def _one(client: httpx.AsyncClient, url: str, payload: dict, results: list):
    t0 = time.perf_counter()
    try:
        r = await client.post(url, json=payload)
        ok = r.status_code == 200
        results.append((time.perf_counter() - t0, ok, r.status_code))
    except Exception:  # noqa: BLE001
        results.append((time.perf_counter() - t0, False, 0))


async def run(url: str, rps: int, duration: int, token: str | None = None) -> None:
    samples = _load_samples(max(rps * duration, 100))
    total = rps * duration
    results: list[tuple[float, bool, int]] = []
    limits = httpx.Limits(max_connections=rps * 4, max_keepalive_connections=rps * 2)

    print(f"开始压测：{url}  目标 {rps} RPS × {duration}s = {total} 请求")
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with httpx.AsyncClient(timeout=30.0, limits=limits, headers=headers) as client:
        start = time.perf_counter()
        tasks = []
        for i in range(total):
            # 按目标速率定时发起（开环）
            target_t = start + i / rps
            now = time.perf_counter()
            if target_t > now:
                await asyncio.sleep(target_t - now)
            payload = samples[i % len(samples)]
            tasks.append(asyncio.create_task(_one(client, url, payload, results)))
        await asyncio.gather(*tasks)
        wall = time.perf_counter() - start

    _report(results, wall, rps)


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    k = max(0, min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1)))))
    return sorted(xs)[k]


def _report(results: list[tuple[float, bool, int]], wall: float, target_rps: int) -> None:
    lat = [r[0] for r in results]
    ok = sum(1 for r in results if r[1])
    n = len(results)
    print("\n===== 压测结果 =====")
    print(f"总请求      : {n}")
    print(f"成功        : {ok} ({ok / n:.1%})" if n else "无请求")
    print(f"实际吞吐    : {n / wall:.1f} RPS（目标 {target_rps}）")
    print(f"耗时        : {wall:.1f}s")
    print(f"状态码      : {dict(sorted(Counter(r[2] for r in results).items()))}")
    limited = sum(1 for r in results if r[2] == 429)
    if limited:
        print(f"限流 429    : {limited} ({limited / n:.1%})")
    if lat:
        print(f"时延 mean   : {statistics.mean(lat) * 1000:.0f} ms")
        print(f"时延 p50    : {_pct(lat, 50) * 1000:.0f} ms")
        print(f"时延 p95    : {_pct(lat, 95) * 1000:.0f} ms")
        print(f"时延 p99    : {_pct(lat, 99) * 1000:.0f} ms")
        print(f"时延 max    : {max(lat) * 1000:.0f} ms")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=DEFAULT_URL)
    p.add_argument("--rps", type=int, default=100)
    p.add_argument("--duration", type=int, default=30)
    p.add_argument("--token", default=None, help="Bearer token；PUBLIC_QUERY_ENABLED=false 时需要")
    args = p.parse_args()
    asyncio.run(run(args.url, args.rps, args.duration, args.token))
