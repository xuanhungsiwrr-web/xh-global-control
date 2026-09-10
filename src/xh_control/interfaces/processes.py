"""Stop owned process trees and wait for confirmed process exit."""

import asyncio
import os
import signal


async def terminate_tree(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    if os.name == "nt":
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/PID", str(process.pid), "/T", "/F",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        code = await killer.wait()
        if code and process.returncode is None:
            raise RuntimeError("PROCESS_TREE_STOP_UNCONFIRMED")
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    await asyncio.wait_for(process.wait(), 10)
