"""ai-pipeline capabilities -- list available content pipelines."""

from __future__ import annotations

__all__ = ["run_capabilities"]


def run_capabilities() -> int:
    """Print available pipeline capabilities from the registry and return exit code 0."""
    from content_pipeline.pipelines.registry import list_pipelines

    pipelines = list_pipelines()
    print("AI Pipeline -- Available Pipelines")
    print("=" * 65)
    for cap in sorted(pipelines, key=lambda m: m.content_type):
        print(f"\n  [{cap.content_type}]")
        print(f"    {cap.description}")
        if cap.required_params:
            print(f"    Required params: {', '.join(cap.required_params)}")
        print(f"    External tools: {', '.join(cap.external_tools)}")
        if cap.publish_targets:
            print(f"    Publish targets: {', '.join(cap.publish_targets)}")
        else:
            print("    Publish targets: (none)")
    print()
    return 0
