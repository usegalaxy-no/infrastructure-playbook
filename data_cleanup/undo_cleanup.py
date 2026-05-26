#!/usr/bin/env python3
"""
galaxy_undo.py — Revert deletions logged by galaxy_cleanup.py.

Reads a TSV deletion log produced by galaxy_cleanup.py and undeletes each entry. 
Histories and collections are undeleted with individual API calls;
datasets are undeleted in batches via a single DELETE /api/datasets request
per history (with deleted=False to reverse the deletion).

Undelete rules:
  - A log entry with kind "history" causes the entire history to be undeleted.
    This also restores all datasets and collections inside it, so any
    individual "dataset" or "collection" entries in the same log that belong
    to the same history are redundant. The script warns about such entries and
    skips them to avoid unnecessary API calls.
  - A log entry with kind "collection" causes that collection to be undeleted
    individually.
  - Log entries with kind "dataset" that share the same history_id are grouped
    and undeleted together.

Failures (e.g. already-purged items) are logged and skipped; processing
continues with the remaining entries.

Usage:
    python galaxy_undo.py --url <GALAXY_URL> --api-key <ADMIN_API_KEY> \
        --email <USER_EMAIL> --log <LOGFILE> [--dry-run] [--verbose]

Requirements:
    pip install bioblend
"""

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

try:
    from bioblend.galaxy import GalaxyInstance
except ImportError:
    sys.exit("ERROR: bioblend is not installed. Run: pip install bioblend")


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

def parse_log(log_path: Path, logger: logging.Logger) -> list[dict]:
    """
    Parse a TSV deletion log into a list of entry dicts with keys:
        created, kind, object_id, history_id

    Comment lines (starting with #) and blank lines are skipped.
    Malformed lines are warned about and skipped.
    """
    entries = []
    with log_path.open(encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) != 4:
                logger.warning(
                    "Line %d: expected 4 tab-separated fields, got %d — skipping: %r",
                    lineno, len(parts), line,
                )
                continue
            created, kind, object_id, history_id = parts
            if kind not in ("history", "collection", "dataset"):
                logger.warning(
                    "Line %d: unknown kind %r — skipping.", lineno, kind
                )
                continue
            entries.append({
                "created": created,
                "kind": kind,
                "object_id": object_id,
                "history_id": history_id if history_id != "-" else None,
            })
    return entries


# ---------------------------------------------------------------------------
# Core logic
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
        # Admin GalaxyInstance — used only for user lookup and API key
        # retrieval. Never used for data access or undeletions.
        self.admin_gi = GalaxyInstance(url=galaxy_url, key=api_key)
        self.galaxy_url = galaxy_url

        # User-scoped GalaxyInstance — set in run() once we have the target
        # user's API key. All undeletions go through this instance.
        self.gi: GalaxyInstance | None = None

        self.user_email = user_email
        self.log_path = log_path
        self.dry_run = dry_run
        self.verbose = verbose

        self.counts = {
            "histories_undeleted": 0,
            "collections_undeleted": 0,
            "datasets_undeleted": 0,
            "skipped_redundant": 0,
            "already_active": 0,
            "purged": 0,
            "failed": 0,
        }

        self._setup_logging()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _setup_logging(self):
        self.logger = logging.getLogger("galaxy_undo")
        self.logger.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        ch.setFormatter(fmt)
        self.logger.addHandler(ch)

    # ------------------------------------------------------------------
    # Galaxy API helpers
    # ------------------------------------------------------------------

    def _get_target_user(self) -> dict:
        """Return the Galaxy user object for user_email (admin call)."""
        for user in self.admin_gi.users.get_users():
            if user.get("email", "").lower() == self.user_email.lower():
                return user
        sys.exit(f"ERROR: No Galaxy user found with email '{self.user_email}'")

    def _get_user_api_key(self, user_id: str) -> str:
        """Retrieve (or create) an API key for the target user via the admin API."""
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


    def _undelete_history(self, history_id: str):
        prefix = "[DRY-RUN] " if self.dry_run else ""
        try:
            detail = self.gi.histories.show_history(history_id)
        except Exception as exc:
            self.logger.error(
                "Could not fetch history %s: %s", history_id, exc
            )
            self.counts["failed"] += 1
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
                self.counts["failed"] += 1
                return
        self.counts["histories_undeleted"] += 1


    def _undelete_collection(self, history_id: str, collection_id: str):
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
            self.counts["failed"] += 1
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
                self.counts["failed"] += 1
                return
        self.counts["collections_undeleted"] += 1


    def _batch_undelete_datasets(self, history_id: str, dataset_ids: list[str]):
        """
        Undelete multiple datasets.
        Although Galaxy allows batch-deletion of multiple datasets at the
        same time, there is unfortunately no functionality to undelete
        multiple datasets with one API call, so we must loop through the list
        """
        for dataset_id in dataset_ids:
            self._undelete_dataset(history_id, dataset_id)


    def _undelete_dataset(self, history_id: str, dataset_id: str):
        prefix = "[DRY-RUN] " if self.dry_run else ""
        try:
            detail = self.gi.histories.show_dataset(history_id, dataset_id)
        except Exception as exc:
            self.logger.error(
                "Could not fetch dataset %s in history %s: %s",
                dataset_id, history_id, exc,
            )
            self.counts["failed"] += 1
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
                self.counts["failed"] += 1
                return
        self.counts["datasets_undeleted"] += 1

    # ------------------------------------------------------------------
    # Main undo logic
    # ------------------------------------------------------------------

    def run(self):
        mode = "DRY-RUN" if self.dry_run else "LIVE UNDELETE"
        self.logger.info("=" * 60)
        self.logger.info("Galaxy Undo  |  mode=%s", mode)
        self.logger.info("Target user : %s", self.user_email)
        self.logger.info("Log file    : %s", self.log_path)
        self.logger.info("=" * 60)

        entries = parse_log(self.log_path, self.logger)
        if not entries:
            self.logger.info("No entries found in log — nothing to do.")
            return
        self.logger.info("Parsed %d log entries.", len(entries))

        user = self._get_target_user()
        user_id = user["id"]
        self.logger.info("Resolved user id: %s", user_id)

        user_api_key = self._get_user_api_key(user_id)
        self.gi = GalaxyInstance(url=self.galaxy_url, key=user_api_key)
        self.logger.info("Obtained user-scoped API key for %s", self.user_email)

        # Collect the set of history IDs that appear as "history" kind entries.
        # Individual dataset/collection entries belonging to these histories are
        # redundant (undeleting the history restores them) and will be skipped.
        history_level_ids: set[str] = {
            e["object_id"] for e in entries if e["kind"] == "history"
        }

        # Partition remaining entries by kind, warning about redundant ones.
        collection_entries: list[dict] = []
        # dataset entries grouped by history_id for batching
        datasets_by_history: dict[str, list[str]] = defaultdict(list)

        for entry in entries:
            kind = entry["kind"]
            obj_id = entry["object_id"]
            history_id = entry["history_id"]

            if kind == "history":
                # Handled separately below.
                continue

            # Check if this entry belongs to a history that will be undeleted
            # as a unit, making this entry redundant.
            if history_id in history_level_ids:
                self.logger.warning(
                    "Entry %s (%s) belongs to history %s which is also logged "
                    "for full undelete — skipping redundant entry.",
                    obj_id, kind, history_id,
                )
                self.counts["skipped_redundant"] += 1
                continue

            if kind == "collection":
                collection_entries.append(entry)
            elif kind == "dataset":
                if history_id is None:
                    self.logger.warning(
                        "Dataset entry %s has no history_id — skipping.", obj_id
                    )
                    self.counts["failed"] += 1
                    continue
                datasets_by_history[history_id].append(obj_id)

        # ------------------------------------------------------------------
        # 1. Undelete histories
        # ------------------------------------------------------------------
        history_entries = [e for e in entries if e["kind"] == "history"]
        for entry in history_entries:
            history_id = entry["object_id"]
            self.logger.info(
                "%sUndeleting history %s (created %s) ...",
                "[DRY-RUN] " if self.dry_run else "",
                history_id, entry["created"],
            )
            self._undelete_history(history_id)

        # ------------------------------------------------------------------
        # 2. Undelete collections individually
        # ------------------------------------------------------------------
        for entry in collection_entries:
            collection_id = entry["object_id"]
            history_id = entry["history_id"]
            self.logger.info(
                "%sUndeleting collection %s in history %s (created %s) ...",
                "[DRY-RUN] " if self.dry_run else "",
                collection_id, history_id, entry["created"],
            )
            self._undelete_collection(history_id, collection_id)

        # ------------------------------------------------------------------
        # 3. Batch-undelete datasets, grouped by history
        # ------------------------------------------------------------------
        for history_id, dataset_ids in datasets_by_history.items():
            self.logger.info(
                "%sBatch-undeleting %d dataset(s) in history %s ...",
                "[DRY-RUN] " if self.dry_run else "",
                len(dataset_ids), history_id,
            )
            self._batch_undelete_datasets(history_id, dataset_ids)

        # ------------------------------------------------------------------
        self._print_summary()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _print_summary(self):
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        self.logger.info("=" * 60)
        self.logger.info("Summary (%s)", mode)
        self.logger.info(
            "  Histories undeleted    : %d", self.counts["histories_undeleted"]
        )
        self.logger.info(
            "  Collections undeleted  : %d", self.counts["collections_undeleted"]
        )
        self.logger.info(
            "  Datasets undeleted     : %d", self.counts["datasets_undeleted"]
        )
        self.logger.info(
            "  Skipped (redundant)    : %d", self.counts["skipped_redundant"]
        )
        self.logger.info(
            "  Skipped (active)       : %d", self.counts["already_active"]
        )
        self.logger.info(
            "  Failed (already purged): %d", self.counts["purged"]
        )
        self.logger.info(
            "  Failed (other reasons) : %d", self.counts["failed"]
        )
        self.logger.info("=" * 60)
        if self.dry_run:
            self.logger.info(
                "This was a DRY-RUN. Re-run with --undelete to apply changes."
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Revert deletions logged by galaxy_cleanup.py. "
            "Applies changes immediately unless --dry-run is passed."
        )
    )
    parser.add_argument(
        "--url", required=True,
        help="Base URL of the Galaxy server, e.g. https://usegalaxy.no",
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
        help="Path to the TSV deletion log produced by galaxy_cleanup.py.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=False,
        help="Show what would be undeleted without making any changes.",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", default=False,
        help="Enable DEBUG level log output.",
    )

    args = parser.parse_args()

    log_path = Path(args.log)
    if not log_path.exists():
        sys.exit(f"ERROR: Log file not found: {log_path}")

    undo = GalaxyUndo(
        galaxy_url=args.url,
        api_key=args.api_key,
        user_email=args.email,
        log_path=log_path,
        dry_run=args.dry_run,
        verbose=args.verbose,
    )
    undo.run()


if __name__ == "__main__":
    main()
