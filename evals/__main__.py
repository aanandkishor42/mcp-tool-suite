"""Allow running evals as `python -m evals`."""
import asyncio

from .run import main as run_main

if __name__ == "__main__":
    asyncio.run(run_main())
