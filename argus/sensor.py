from __future__ import annotations

import asyncio
import contextlib
import signal

from argus.database import init_db
from argus.repository import using_remote_repository
from argus.scheduler_registry import create_scheduler


async def run_sensor() -> None:
    if not using_remote_repository():
        init_db()
    scheduler = create_scheduler(enabled=True)
    scheduler.start()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(signum, stop_event.set)
    try:
        await stop_event.wait()
    finally:
        await scheduler.stop()


def main() -> None:
    asyncio.run(run_sensor())


if __name__ == "__main__":
    main()
