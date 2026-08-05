"""CLI entry points for ai-popline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from content_pipeline.job_store import JobStore
from content_pipeline.models import JobStatus, TaskInput
from content_pipeline.orchestrator import run_task_file
from content_pipeline.settings import load_settings


def main() -> int:
    """Main CLI entry point for ai-popline."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description="AI Popline Content Pipeline")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    doctor_parser = subparsers.add_parser("doctor", help="Check environment, paths, and external tools")
    doctor_parser.add_argument("--bundle", type=Path, help="Write a diagnostics bundle zip")

    subparsers.add_parser("capabilities", help="List available content pipelines")

    run_parser = subparsers.add_parser("run", help="Run a task from a JSON file")
    run_parser.add_argument("--task", required=True, type=Path, help="Path to task JSON file")

    serve_parser = subparsers.add_parser("serve", help="Start the HTTP API server")
    serve_parser.add_argument("--host", help="Exact loopback or ZeroTier interface IP")
    serve_parser.add_argument("--port", type=int)
    serve_parser.add_argument("--ssl-certfile", type=Path)
    serve_parser.add_argument("--ssl-keyfile", type=Path)

    subparsers.add_parser("mcp", help="Start the MCP server")

    validate_parser = subparsers.add_parser("validate-task", help="Validate a task JSON file")
    validate_parser.add_argument("--task", required=True, type=Path)

    jobs_parser = subparsers.add_parser("jobs", help="Inspect or clean stored jobs")
    jobs_subparsers = jobs_parser.add_subparsers(dest="jobs_command")

    jobs_list = jobs_subparsers.add_parser("list", help="List recent jobs")
    jobs_list.add_argument("--status", choices=[status.value for status in JobStatus])
    jobs_list.add_argument("--content-type")
    jobs_list.add_argument("--limit", type=int, default=50)

    jobs_show = jobs_subparsers.add_parser("show", help="Show a job snapshot")
    jobs_show.add_argument("task_id")

    jobs_events = jobs_subparsers.add_parser("events", help="Show recent job events")
    jobs_events.add_argument("task_id")
    jobs_events.add_argument("--limit", type=int, default=50)

    jobs_cleanup = jobs_subparsers.add_parser("cleanup", help="Delete old jobs")
    jobs_cleanup.add_argument("--older-than-days", type=int, default=30)

    args = parser.parse_args()

    if args.command == "doctor":
        from .doctor import run_doctor, run_doctor_bundle

        if args.bundle:
            return run_doctor_bundle(args.bundle)
        return run_doctor()
    if args.command == "capabilities":
        from .capabilities import run_capabilities

        return run_capabilities()
    if args.command == "run":
        result = run_task_file(args.task)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] in {"succeeded", "partial"} else 1
    if args.command == "serve":
        import uvicorn

        from content_pipeline.api.network import ensure_bind_address_is_local, validate_bind_configuration

        settings = load_settings()
        host = args.host or settings.web_bind_host
        port = args.port if args.port is not None else settings.web_port
        if not 1 <= port <= 65535:
            raise SystemExit("web port must be between 1 and 65535")
        ssl_certfile = args.ssl_certfile or settings.web_tls_certfile
        ssl_keyfile = args.ssl_keyfile or settings.web_tls_keyfile
        errors = validate_bind_configuration(
            settings,
            host=host,
            ssl_certfile=ssl_certfile,
            ssl_keyfile=ssl_keyfile,
        )
        if errors:
            raise SystemExit("unsafe web listener:\n- " + "\n- ".join(errors))
        try:
            ensure_bind_address_is_local(host)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        for path, label in ((ssl_certfile, "TLS certificate"), (ssl_keyfile, "TLS key")):
            if path is not None and not path.is_file():
                raise SystemExit(f"{label} does not exist: {path}")

        uvicorn.run(
            "content_pipeline.api.app:app",
            host=host,
            port=port,
            ssl_certfile=str(ssl_certfile) if ssl_certfile else None,
            ssl_keyfile=str(ssl_keyfile) if ssl_keyfile else None,
            proxy_headers=False,
            server_header=False,
        )
        return 0
    if args.command == "mcp":
        from content_pipeline.mcp_server import main as mcp_main

        return mcp_main()
    if args.command == "validate-task":
        task = TaskInput.model_validate_json(args.task.read_text(encoding="utf-8"))
        print(json.dumps(task.model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0
    if args.command == "jobs":
        return _run_jobs_command(args)

    parser.print_help()
    return 0


def _run_jobs_command(args: argparse.Namespace) -> int:
    settings = load_settings()
    store = JobStore(settings.data_dir)

    if args.jobs_command == "list":
        status = JobStatus(args.status) if args.status else None
        jobs = store.list_jobs(status=status, content_type=args.content_type, limit=args.limit)
        print(json.dumps([job.model_dump(mode="json") for job in jobs], ensure_ascii=False, indent=2))
        return 0

    if args.jobs_command == "show":
        print(json.dumps(store.get(args.task_id).model_dump(mode="json"), ensure_ascii=False, indent=2))
        return 0

    if args.jobs_command == "events":
        events_path = store.events_path(args.task_id)
        if not events_path.is_file():
            raise FileNotFoundError(f"task not found: {args.task_id}")
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        print(json.dumps(events[-args.limit :], ensure_ascii=False, indent=2))
        return 0

    if args.jobs_command == "cleanup":
        removed = store.cleanup_old_jobs(max_age_days=args.older_than_days)
        print(json.dumps({"removed": removed}, ensure_ascii=False, indent=2))
        return 0

    raise SystemExit("missing jobs subcommand")


if __name__ == "__main__":
    raise SystemExit(main())
