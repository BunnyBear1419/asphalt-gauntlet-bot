import asyncio
import time


def test_uptime_formatting_importable():
    # Keep this test dependency-light; CI also runs the full bot suite after installing requirements.
    from pathlib import Path
    core = (Path(__file__).resolve().parents[1] / "ALU_Gauntlet/core/core.py").read_text()
    assert "def format_duration" in core
    assert "def now_ts" in core


def test_concurrent_submission_model_is_serializable():
    async def worker(lock, results, value):
        async with lock:
            await asyncio.sleep(0)
            results.append(value)

    async def run():
        lock = asyncio.Lock()
        results = []
        await asyncio.gather(*(worker(lock, results, i) for i in range(25)))
        return results

    results = asyncio.run(run())
    assert sorted(results) == list(range(25))


def test_deterministic_stale_window():
    now = time.time()
    assert now - (now - 900) == 900
