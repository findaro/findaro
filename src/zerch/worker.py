"""Ingest worker: `python -m zerch.worker`. Run a single instance per deployment in M1."""

from __future__ import annotations

import asyncio
import logging
import signal

from zerch import usage
from zerch.ingest.processor import requeue_stale, run_pending
from zerch.state import create_state

log = logging.getLogger("zerch.worker")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("opensearch").setLevel(logging.WARNING)
    state = await create_state()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await requeue_stale(state)
    log.info("worker ready (embedder=%s dim=%d)", state.embedder.name, state.embedder.dim)
    next_flush = loop.time() + state.settings.usage_flush_interval
    try:
        while not stop.is_set():
            if loop.time() >= next_flush:
                next_flush = loop.time() + state.settings.usage_flush_interval
                try:
                    await usage.flush(state)
                except Exception:  # noqa: BLE001 - counters stay in Redis until the next flush
                    log.exception("usage flush error")
            try:
                n = await run_pending(state)
            except Exception:  # noqa: BLE001 - keep the worker alive on DB/OS hiccups
                log.exception("worker loop error")
                n = 0
            if n == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=state.settings.worker_poll_interval)
                except TimeoutError:
                    pass
    finally:
        try:
            await usage.flush(state)
        except Exception:  # noqa: BLE001
            log.exception("usage flush error")
        await state.close()


if __name__ == "__main__":
    asyncio.run(main())
