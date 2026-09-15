"""Discloud entrypoint; the canonical runner lives in ALU_Gauntlet.main."""
import asyncio
from ALU_Gauntlet.main import runner

if __name__ == "__main__":
    asyncio.run(runner())
