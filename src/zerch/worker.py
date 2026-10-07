"""Ingest worker: `python -m zerch.worker`. Run a single instance per deployment in M1."""

from __future__ import annotations

import asyncio
import logging
import signal

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
    try:
        while not stop.is_set():
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
        await state.close()


if __name__ == "__main__":
    asyncio.run(main())
