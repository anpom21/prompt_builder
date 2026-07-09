from __future__ import annotations

import argparse
import logging
import sys

from prompt_builder.ui import launch_app


def main() -> int:
    parser = argparse.ArgumentParser(description="Prompt builder for Python context bundles")
    parser.add_argument("paths", nargs="*", help="Files or folders to load on startup")
    parser.add_argument("--verbose", action="store_true", help="Print detailed progress information")
    parser.add_argument("--session", help="Prompt session JSON file to load on startup")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.verbose:
        logging.getLogger(__name__).info("Verbose mode enabled")

    return launch_app(default_paths=args.paths, verbose=args.verbose, session_path=args.session)


if __name__ == "__main__":
    raise SystemExit(main())
