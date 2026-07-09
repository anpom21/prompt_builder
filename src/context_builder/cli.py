from __future__ import annotations

import argparse
import logging

from context_builder.ui import launch_app


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Context Builder for repository-aware JSON context structures"
    )
    parser.add_argument("paths", nargs="*", help="Files or folders to load on startup")
    parser.add_argument("--verbose", action="store_true", help="Print detailed progress information")
    parser.add_argument("--session", help="Context session JSON file to load on startup")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.verbose:
        logging.getLogger(__name__).info("Verbose mode enabled")

    return launch_app(
        default_paths=args.paths,
        verbose=args.verbose,
        session_path=args.session,
    )