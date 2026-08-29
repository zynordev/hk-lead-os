"""Run a prompt file through the existing HK-Agents bridge without argv limits."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt_file", type=Path)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()

    workers_root = Path(os.environ["HK_AGENTS_ROOT"])
    sys.path.insert(0, str(workers_root))
    from hk_agents.universal_bridge import UniversalBridge

    prompt = args.prompt_file.read_text(encoding="utf-8")
    summary = asyncio.run(UniversalBridge(workers_root).delegate_goal(prompt, workers=args.workers, concurrency=args.concurrency))
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
