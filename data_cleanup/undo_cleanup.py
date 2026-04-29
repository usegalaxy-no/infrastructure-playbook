#!/usr/bin/env python3
"""
undo_cleanup.py — Revert deletions made by galaxy_cleanup.py.

Reads a TSV log file produced by galaxy_cleanup.py and undeletes every entry
in it, in reverse order (datasets and collections before histories, so that
a history is not undeleted before its contents are restored).

Only "deleted" items can be reverted — purged items are gone permanently.
The script will report an error for any item that has already been purged.

Dry-run is the default; pass --undelete to perform actual reversions.

Usage:
    python galaxy_undo.py --url <GALAXY_URL> --api-key <ADMIN_API_KEY> \\
        --email <USER_EMAIL> --log <LOGFILE> [--undelete] [--verbose]

Requirements:
    pip install bioblend
"""

import argparse
import logging
import sys
from pathlib import Path

try:
    from bioblend.galaxy import GalaxyInstance
except ImportError:
    sys.exit("ERROR: bioblend is not installed. Run: pip install bioblend")


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

def parse_log(log_path: Path) -> list[dict]:
    """
    Parse a galaxy_cleanup.py TSV log file and return a list of entries.

    Each entry is a dict with keys: timestamp, kind, object_id, history_id.
    Comment lines (starting with #) and blank lines are ignored.
    """
    entries = []
    with log_path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 4:
                raise ValueError(
                    f"Unexpected format on line {lineno}: {line!r} "
                    f"(expected 4 tab-separated fields, got {len(parts)})"
                )
            timestamp, kind, object_id, history_id = parts
            entries.append({
                "timestamp": timestamp,
                "kind": kind,
                "object_id": object_id,
                "history_id": history_id if history_id != "-" else None,
            })
    return entries


# ---------------------------------------------------------------------------
# Undo logic
# ---------------------------------------------------------------------------

class GalaxyUndo:
    def __init__(
        self,
        galaxy_url: str,
        api_key: str,
        user_email: str,
        log_path: Path,
        dry_run: bool,
        verbose: bool = False,
    ):
        self.admin_gi = GalaxyInstance(url=galaxy_url, key=api_key)
        self.galaxy_url = galaxy_url
        self.user_email = user_email
        self.log_path = log_path
        self.dry_run = dry_run
        self.verbose = verbose

        # User-scoped GalaxyInstance — set in run() after resolving the user.
        self.gi: GalaxyInstance | None = None

        self.counts = {
            "datasets_undeleted": 0,
            "collections_undeleted": 0,
            "histories_undeleted": 0,
            "already_active": 0,
            "purged": 0,
            "errors": 0,
        }

        self.setup_logging()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def setup_logging(self):
        self.logger = logging.getLogger("galaxy_undo")
        self.logger.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        ch.setFormatter(fmt)
        self.logger.addHandler(ch)

    # ------------------------------------------------------------------
    # Galaxy helpers
    # ------------------------------------------------------------------

    def get_target_user(self) -> dict:
        users = self.admin_gi.users.get_users()
        for user in users:
            if user.get("email", "").lower() == self.user_email.lower():
                return user
        sys.exit(f"ERROR: No Galaxy user found with email '{self.user_email}'")

    def get_user_api_key(self, user_id: str) -> str:
        try:
            key = self.admin_gi.users.get_user_apikey(user_id)
            if key and key != "Not available.":
                return key
        except Exception:
            pass
        try:
            return self.admin_gi.users.create_user_apikey(user_id)
        except Exception as exc:
            sys.exit(
                f"ERROR: Could not obtain API key for user {self.user_email}: {exc}"
            )

    # ------------------------------------------------------------------
    # Undelete operations
    # ------------------------------------------------------------------

    def undelete_dataset(self, history_id: str, dataset_id: str):
        prefix = "[DRY-RUN] " if self.dry_run else ""
        try:
            detail = self.gi.histories.show_dataset(history_id, dataset_id)
        except Exception as exc:
            self.logger.error(
                "Could not fetch dataset %s in history %s: %s",
                dataset_id, history_id, exc,
            )
            self.counts["errors"] += 1
            return

        if detail.get("purged"):
            self.logger.warning(
                "Dataset %s has been purged and cannot be recovered.", dataset_id
            )
            self.counts["purged"] += 1
            return

        if not detail.get("deleted"):
            self.logger.debug(
                "Dataset %s is already active — skipping.", dataset_id
            )
            self.counts["already_active"] += 1
            return

        self.logger.info("%sUNDELETE  dataset     id=%s", prefix, dataset_id)
        if not self.dry_run:
            try:
                self.gi.histories.update_dataset(
                    history_id, dataset_id, deleted=False
                )
            except Exception as exc:
                self.logger.error(
                    "Failed to undelete dataset %s: %s", dataset_id, exc
                )
                self.counts["errors"] += 1
                return
        self.counts["datasets_undeleted"] += 1

    def undelete_collection(self, history_id: str, collection_id: str):
        prefix = "[DRY-RUN] " if self.dry_run else ""
        try:
            detail = self.gi.histories.show_dataset_collection(
                history_id, collection_id
            )
        except Exception as exc:
            self.logger.error(
                "Could not fetch collection %s in history %s: %s",
                collection_id, history_id, exc,
            )
            self.counts["errors"] += 1
            return

        if detail.get("purged"):
            self.logger.warning(
                "Collection %s has been purged and cannot be recovered.",
                collection_id,
            )
            self.counts["purged"] += 1
            return

        if not detail.get("deleted"):
            self.logger.debug(
                "Collection %s is already active — skipping.", collection_id
            )
            self.counts["already_active"] += 1
            return

        self.logger.info("%sUNDELETE  collection  id=%s", prefix, collection_id)
        if not self.dry_run:
            try:
                self.gi.histories.update_dataset_collection(
                    history_id, collection_id, deleted=False
                )
            except Exception as exc:
                self.logger.error(
                    "Failed to undelete collection %s: %s", collection_id, exc
                )
                self.counts["errors"] += 1
                return
        self.counts["collections_undeleted"] += 1

    def undelete_history(self, history_id: str):
        prefix = "[DRY-RUN] " if self.dry_run else ""
        try:
            detail = self.gi.histories.show_history(history_id)
        except Exception as exc:
            self.logger.error(
                "Could not fetch history %s: %s", history_id, exc
            )
            self.counts["errors"] += 1
            return

        if detail.get("purged"):
            self.logger.warning(
                "History %s has been purged and cannot be recovered.", history_id
            )
            self.counts["purged"] += 1
            return

        if not detail.get("deleted"):
            self.logger.debug(
                "History %s is already active — skipping.", history_id
            )
            self.counts["already_active"] += 1
            return

        self.logger.info("%sUNDELETE  history     id=%s", prefix, history_id)
        if not self.dry_run:
            try:
                self.gi.histories.undelete_history(history_id)
            except Exception as exc:
                self.logger.error(
                    "Failed to undelete history %s: %s", history_id, exc
                )
                self.counts["errors"] += 1
                return
        self.counts["histories_undeleted"] += 1

    # ------------------------------------------------------------------
    # Main
    # ------------------------------------------------------------------

    def run(self):
        mode = "DRY-RUN" if self.dry_run else "LIVE UNDELETE"
        self.logger.info("=" * 60)
        self.logger.info("Galaxy Undo  |  mode=%s", mode)
        self.logger.info("Target user : %s", self.user_email)
        self.logger.info("Log file    : %s", self.log_path)
        self.logger.info("=" * 60)

        # Parse log file
        try:
            entries = parse_log(self.log_path)
        except Exception as exc:
            sys.exit(f"ERROR: Could not parse log file: {exc}")

        if not entries:
            self.logger.info("Log file is empty — nothing to undo.")
            return

        self.logger.info("Found %d entries to revert.", len(entries))

        # Resolve user and obtain user-scoped API key
        user = self.get_target_user()
        user_id = user["id"]
        self.logger.info("Resolved user id: %s", user_id)

        user_api_key = self.get_user_api_key(user_id)
        self.gi = GalaxyInstance(url=self.galaxy_url, key=user_api_key)

        # Process in reverse order so datasets/collections are restored before
        # their parent histories, and newer deletions are reverted first.
        datasets    = [e for e in entries if e["kind"] == "dataset"]
        collections = [e for e in entries if e["kind"] == "collection"]
        histories   = [e for e in entries if e["kind"] == "history"]
        unknown     = [e for e in entries if e["kind"] not in ("dataset", "collection", "history")]

        for e in unknown:
            self.logger.warning("Unknown kind %r for id %s — skipping.", e["kind"], e["object_id"])

        # Restore in order: datasets → collections → histories
        for e in reversed(datasets):
            self.undelete_dataset(e["history_id"], e["object_id"])

        for e in reversed(collections):
            self.undelete_collection(e["history_id"], e["object_id"])

        for e in reversed(histories):
            self.undelete_history(e["object_id"])

        self.print_summary()

    def print_summary(self):
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        self.logger.info("=" * 60)
        self.logger.info("Summary (%s)", mode)
        self.logger.info("  Datasets undeleted    : %d", self.counts["datasets_undeleted"])
        self.logger.info("  Collections undeleted : %d", self.counts["collections_undeleted"])
        self.logger.info("  Histories undeleted   : %d", self.counts["histories_undeleted"])
        self.logger.info("  Already active        : %d", self.counts["already_active"])
        self.logger.info("  Purged (unrecoverable): %d", self.counts["purged"])
        self.logger.info("  Errors                : %d", self.counts["errors"])
        self.logger.info("=" * 60)
        if self.dry_run:
            self.logger.info(
                "This was a DRY-RUN. Re-run with --undelete to perform actual reversions."
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Revert deletions made by galaxy_cleanup.py by reading its log file. "
            "Runs as a dry-run by default; use --undelete to apply changes."
        )
    )
    parser.add_argument(
        "--url", required=True,
        help="Base URL of the Galaxy server, e.g. https://your-galaxy.example.org",
    )
    parser.add_argument(
        "--api-key", required=True,
        help="Admin API key (must have admin privileges to act on other users).",
    )
    parser.add_argument(
        "--email", required=True,
        help="Email address of the Galaxy user whose data should be restored.",
    )
    parser.add_argument(
        "--log", required=True,
        help="Path to the TSV log file produced by galaxy_cleanup.py.",
    )
    parser.add_argument(
        "--undelete", action="store_true", default=False,
        help="Actually perform undeletions. Without this flag, only a dry-run is done.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", default=False,
        help="Enable DEBUG level log output.",
    )

    args = parser.parse_args()

    log_path = Path(args.log)
    if not log_path.exists():
        parser.error(f"Log file not found: {log_path}")

    undo = GalaxyUndo(
        galaxy_url=args.url,
        api_key=args.api_key,
        user_email=args.email,
        log_path=log_path,
        dry_run=not args.undelete,
        verbose=args.verbose,
    )
    undo.run()


if __name__ == "__main__":
    main()
