"""CLI entry points for ai-popline."""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    """Main CLI entry point for ai-popline."""
    try:
        sys.stdout.reconfigure(errors="backslashreplace")
        sys.stderr.reconfigure(errors="backslashreplace")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description="AI Popline Content Pipeline")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # doctor
    subparsers.add_parser("doctor", help="Check environment, paths, and external tools")
    subparsers.add_parser("capabilities", help="List available content pipelines")

    # task runner (backward compat)
    task_parser = subparsers.add_parser("run", help="Run a task from a JSON file")
    task_parser.add_argument("--task", required=True, type=str, help="Path to task JSON file")

    args = parser.parse_args()

    if args.command == "doctor":
        from .doctor import run_doctor

        return run_doctor()
    elif args.command == "capabilities":
        from .capabilities import run_capabilities

        return run_capabilities()
    elif args.command == "run":
        from pathlib import Path

        from content_pipeline.orchestrator import run_task_file

        result = run_task_file(Path(args.task))
        import json

        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] in {"succeeded", "partial"} else 1
    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
