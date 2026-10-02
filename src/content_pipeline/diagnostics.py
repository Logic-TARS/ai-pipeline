from __future__ import annotations

import sys

from content_pipeline.photo_process_debug import main

__all__ = ["main"]

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
