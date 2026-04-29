#!/usr/bin/env python3
"""
galaxy_cleanup.py — Galaxy data cleanup script using the BioBlend API.

Marks datasets, dataset collections, and histories for deletion on a per-user,
per-year-range basis. No data is purged by this script. Shared or published data
is never touched. Dry-run is the default; pass --delete to perform actual deletions.

Deletion rules:
  - A dataset is deleted if its create_time falls within the target year range.
  - A collection is deleted if ALL its leaf datasets are deleted (by this run
    or already deleted before).
  - A history is deleted if ALL its contents are deleted (by this run or already
    deleted before), regardless of when the history itself was created.

Usage:
    python galaxy_cleanup.py --url <GALAXY_URL> --api-key <ADMIN_API_KEY> \
        --email <USER_EMAIL> --year <YEAR_OR_RANGE> [--delete] [--log <LOGFILE>]

    YEAR_OR_RANGE examples:  2022   or   2022-2024

Requirements:
    pip install bioblend
"""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from bioblend.galaxy import GalaxyInstance
    from bioblend.galaxy.histories import HistoryClient
    from bioblend.galaxy.datasets import DatasetClient
except ImportError:
    sys.exit(
        "ERROR: bioblend is not installed. Run: pip install bioblend"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_galaxy_time(time_str: str | None) -> datetime | None:
    """Parse a Galaxy ISO-8601 timestamp into an aware datetime (UTC)."""
    if not time_str:
        return None
    # Galaxy typically returns e.g. "2023-04-01T12:00:00.000000"
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def created_in_range(time_str: str | None, start_year: int, end_year: int) -> bool:
    """Return True if the timestamp falls within [start_year, end_year] inclusive."""
    dt = parse_galaxy_time(time_str)
    if dt is None:
        return False
    return start_year <= dt.year <= end_year


def obj_is_shared_or_published(obj: dict) -> bool:
    """
    Return True if a Galaxy object dict indicates it is published, importable,
    or otherwise shared, based solely on its own fields.

    Used for datasets and collections, which have no dedicated /sharing
    endpoint. Histories should use GalaxyCleanup._history_is_shared() instead,
    which makes a single call to /api/histories/{id}/sharing and checks all
    sharing aspects in one go.
    """
    danger_keys = (
        "published",      # openly published to all users
        "importable",     # shared via link (anyone with URL can import)
        "shared",         # explicitly shared (some API versions expose this)
    )
    for key in danger_keys:
        if obj.get(key):
            return True
    return False


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

class GalaxyCleanup:
    def __init__(
        self,
        galaxy_url: str,
        api_key: str,
        user_email: str,
        start_year: int,
        end_year: int,
        dry_run: bool,
        log_path: Path,
        verbose: bool = False,
    ):
        # Admin GalaxyInstance — used only for privileged calls (user lookup,
        # fetching user API keys). Never used for data browsing or deletion.
        self.admin_gi = GalaxyInstance(url=galaxy_url, key=api_key)
        self.galaxy_url = galaxy_url

        # User-scoped GalaxyInstance — set in run() once we obtain the target
        # user's API key. All data access and deletions go through this.
        self.gi: GalaxyInstance | None = None

        self.user_email = user_email
        self.start_year = start_year
        self.end_year = end_year
        self.dry_run = dry_run
        self.log_path = log_path
        self.verbose = verbose

        # Accumulates log entries: list of TSV lines (timestamp, kind, id, history_id)
        self.deletion_log: list[str] = []
        # Set of object IDs logged for deletion this run — used for fast lookup
        # without re-parsing the log lines.
        self.deleted_ids: set[str] = set()

        # Counts for summary
        self.counts = {
            "datasets_deleted": 0,
            "collections_deleted": 0,
            "histories_deleted": 0,
            "skipped_shared": 0,
            "skipped_out_of_range": 0,
            "skipped_not_fully_deleted": 0,
            "histories_kept": 0,
        }

        self.setup_logging()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def setup_logging(self):
        self.logger = logging.getLogger("galaxy_cleanup")
        self.logger.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        ch.setFormatter(fmt)
        self.logger.addHandler(ch)

    def log_deletion(self, timestamp: str, kind: str, obj_id: str, name: str, history_id: str | None = None):
        # TSV columns: timestamp, kind, object_id, history_id (- if not applicable)
        timestamp = timestamp[0:10] # only use date
        line = f"{timestamp}	{kind}	{obj_id}	{history_id or '-'}"
        self.deletion_log.append(line)
        self.deleted_ids.add(obj_id)
        prefix = "[DRY-RUN] " if self.dry_run else ""
        self.logger.debug(
            "%sMARK FOR DELETION  %-12s  id=%-30s  name=%s",
            prefix, kind, obj_id, name,
        )

    def write_log(self):
        with self.log_path.open("w", encoding="utf-8") as fh:
            fh.write("# created\tkind\tobject_id\thistory_id\n")
            for line in self.deletion_log:
                fh.write(line + "\n")
        self.logger.info("Deletion log written to: %s", self.log_path)

    # ------------------------------------------------------------------
    # Galaxy helpers
    # ------------------------------------------------------------------

    def get_target_user(self) -> dict:
        """Return the Galaxy user object for *user_email* (admin call)."""
        users = self.admin_gi.users.get_users()
        for user in users:
            if user.get("email", "").lower() == self.user_email.lower():
                return user
        sys.exit(f"ERROR: No Galaxy user found with email '{self.user_email}'")

    def get_user_api_key(self, user_id: str) -> str:
        """Retrieve (or create) an API key for the target user via the admin API."""
        try:
            key = self.admin_gi.users.get_user_apikey(user_id)
            if key and key != "Not available.":
                return key
        except Exception:
            pass
        # If the user has no key yet, create one.
        try:
            return self.admin_gi.users.create_user_apikey(user_id)
        except Exception as exc:
            sys.exit(
                f"ERROR: Could not obtain API key for user {self.user_email}: {exc}"
            )

    def get_user_histories(self, user_id: str) -> list[dict]:
        """Return all active (non-deleted) histories owned by *user_id*.

        We only fetch active histories since deleted ones are skipped immediately
        anyway — there is nothing for the script to do with them.
        """
        return self.gi.histories.get_histories(deleted=False)

    def get_history_detail(self, history_id: str) -> dict:
        return self.gi.histories.show_history(history_id, contents=False)

    def get_history_contents(self, history_id: str) -> list[dict]:
        """Return all active (non-deleted) top-level items in a history.

        We only fetch active items since deleted ones are skipped immediately.
        For the history emptiness check in maybe_delete_history we re-fetch
        with the same filter: if no active items remain, the history is empty.
        """
        return self.gi.histories.show_history(history_id, contents=True, deleted=False)

    def get_dataset_detail(self, history_id: str, dataset_id: str) -> dict:
        return self.gi.histories.show_dataset(history_id, dataset_id)

    def get_collection_detail(self, history_id: str, collection_id: str) -> dict:
        return self.gi.histories.show_dataset_collection(history_id, collection_id)

    def history_is_shared(self, history_id: str) -> bool:
        """
        Return True if this history is shared or published in any way, by
        calling the /api/histories/{id}/sharing endpoint which covers all cases:

          - published:          visible to all Galaxy users
          - importable:         accessible to anyone with the share link
          - users_shared_with:  explicitly shared with named individual users

        A single API call is sufficient for all three checks, so there is no
        need to separately inspect the history detail object for sharing flags.
        """
        try:
            response = self.admin_gi.make_get_request(
                f"{self.admin_gi.base_url}/api/histories/{history_id}/sharing"
            )
            if response.status_code == 200:
                sharing = response.json()
                if sharing.get("published"):
                    self.logger.debug("History %s is published.", history_id)
                    return True
                if sharing.get("importable"):
                    self.logger.debug("History %s is accessible via share link.", history_id)
                    return True
                if sharing.get("users_shared_with"):
                    self.logger.debug(
                        "History %s is shared with %d individual user(s).",
                        history_id, len(sharing["users_shared_with"]),
                    )
                    return True
                return False
            else:
                # Unknown response — be conservative.
                self.logger.warning(
                    "History %s: unexpected status %d from /sharing endpoint — "
                    "treating as shared to be safe.",
                    history_id, response.status_code,
                )
                return True
        except Exception as exc:
            self.logger.warning(
                "Could not check sharing info for history %s: %s — "
                "treating as shared to be safe.",
                history_id, exc,
            )
            return True

    # ------------------------------------------------------------------
    # Collection helpers
    # ------------------------------------------------------------------

    def collection_all_entries_deleted(self, elements: list) -> bool:
        """
        Recursively check that every leaf dataset in a collection is deleted
        (either already deleted before this run, or scheduled for deletion by
        this run). Returns True only if ALL leaves are accounted for.
        """
        def check(element: dict) -> bool:
            element_type = element.get("element_type", "")

            if element_type == "dataset_collection":
                sub = element.get("object", {})
                sub_elements = sub.get("elements", [])
                if not sub_elements:
                    # Empty nested collection — conservative: not eligible
                    return False
                return all(check(e) for e in sub_elements)

            elif element_type == "hda":
                obj = element.get("object", {})
                if obj.get("deleted"):
                    return True  # Already deleted before this run
                if self.dry_run and obj.get("id") in self.deleted_ids:
                    return True  # Scheduled for deletion by this run
                if not self.dry_run and obj.get("id") in self.deleted_ids:
                    return True  # Was deleted earlier in this run
                self.logger.debug(
                    "Collection leaf dataset %s (%s) is not deleted — "
                    "collection not eligible.",
                    obj.get("id", "?"), obj.get("name", "?"),
                )
                return False

            else:
                # Unknown element type — be conservative
                self.logger.debug(
                    "Unknown collection element_type '%s'; collection not eligible.",
                    element_type,
                )
                return False

        return all(check(e) for e in elements)

    # ------------------------------------------------------------------
    # Main cleanup logic
    # ------------------------------------------------------------------

    def run(self):
        mode = "DRY-RUN" if self.dry_run else "LIVE DELETION"
        self.logger.info("=" * 60)
        self.logger.info("Galaxy Cleanup  |  mode=%s", mode)
        self.logger.info("Target user  : %s", self.user_email)
        year_range = (
            str(self.start_year) if self.start_year == self.end_year
            else f"{self.start_year}-{self.end_year}"
        )
        self.logger.info("Target years : %s", year_range)
        self.logger.info("=" * 60)

        user = self.get_target_user()
        user_id = user["id"]
        self.logger.info("Resolved user id: %s", user_id)

        # Obtain the target user's own API key and build a user-scoped
        # GalaxyInstance. All data browsing and deletion goes through this
        # so Galaxy's visibility and permission rules apply correctly.
        user_api_key = self.get_user_api_key(user_id)
        self.gi = GalaxyInstance(url=self.galaxy_url, key=user_api_key)
        self.logger.info("Obtained user-scoped API key for %s", self.user_email)

        histories = self.get_user_histories(user_id)
        self.logger.info("Found %d histories to inspect.", len(histories))

        for history_summary in histories:
            self.process_history(history_summary)

        self.write_log()
        self.print_summary()

    def process_history(self, history_summary: dict):
        history_id = history_summary["id"]
        history_name = history_summary.get("name", "<unnamed>")
        self.logger.debug("Inspecting history: %s (%s)", history_name, history_id)

        # Skip histories created after the end year — they are too new to
        # contain any eligible datasets, and we want to keep them regardless.
        create_time = history_summary.get("create_time")
        dt = parse_galaxy_time(create_time)
        if dt is not None and dt.year > self.end_year:
            self.logger.debug(
                "History %s was created in %d, after end year %d — skipping.",
                history_id, dt.year, self.end_year,
            )
            self.counts["histories_kept"] += 1
            return

        # --- Safety: never touch shared/published histories ---
        if self.history_is_shared(history_id):
            self.logger.debug(
                "History %s is shared/published — skipping entirely.", history_id
            )
            self.counts["skipped_shared"] += 1
            return

        # Fetch full history detail (needed for create_time in maybe_delete_history).
        try:
            detail = self.get_history_detail(history_id)
        except Exception as exc:
            self.logger.warning(
                "Could not fetch detail for history %s: %s — skipping.", history_id, exc
            )
            return

        # --- Process contents ---
        try:
            contents = self.get_history_contents(history_id)
        except Exception as exc:
            self.logger.warning(
                "Could not fetch contents of history %s: %s — skipping.", history_id, exc
            )
            return

        for item in contents:
            if item.get("history_content_type") == "dataset":
                self.process_dataset(item, history_id)
            elif item.get("history_content_type") == "dataset_collection":
                self.process_collection(item, history_id)
            # Unknown types are ignored (safe default)

        # --- Decide whether to delete the history itself ---
        self.maybe_delete_history(detail, history_id, history_name)

    def process_dataset(self, item: dict, history_id: str):
        dataset_id = item["id"]
        name = item.get("name", "<unnamed>")

        create_time = item.get("create_time")
        if not created_in_range(create_time, self.start_year, self.end_year):
            self.counts["skipped_out_of_range"] += 1
            return

        # Fetch full detail to check sharing
        try:
            detail = self.get_dataset_detail(history_id, dataset_id)
        except Exception as exc:
            self.logger.warning(
                "Could not fetch detail for dataset %s: %s — skipping.", dataset_id, exc
            )
            return

        if obj_is_shared_or_published(detail):
            self.logger.debug("Dataset %s is shared/published — skipping.", dataset_id)
            self.counts["skipped_shared"] += 1
            return

        # All checks passed — mark for deletion
        self.log_deletion(create_time, "dataset", dataset_id, name, history_id)
        if not self.dry_run:
            try:
                self.gi.histories.delete_dataset(history_id, dataset_id, purge=False)
            except Exception as exc:
                self.logger.error(
                    "Failed to delete dataset %s: %s", dataset_id, exc
                )
                return
        self.counts["datasets_deleted"] += 1

    def process_collection(self, item: dict, history_id: str):
        collection_id = item["id"]
        name = item.get("name", "<unnamed>")

        # Fetch full collection detail (needed for element listing)
        try:
            detail = self.get_collection_detail(history_id, collection_id)
        except Exception as exc:
            self.logger.warning(
                "Could not fetch detail for collection %s: %s — skipping.",
                collection_id, exc,
            )
            return

        if obj_is_shared_or_published(detail):
            self.logger.debug(
                "Collection %s is shared/published — skipping.", collection_id
            )
            self.counts["skipped_shared"] += 1
            return

        elements = detail.get("elements", [])

        if not elements:
            # Empty collection — be conservative, do not delete
            self.logger.debug(
                "Collection %s is empty — skipping (conservative).", collection_id
            )
            return

        if not self.collection_all_entries_deleted(elements):
            self.counts["skipped_not_fully_deleted"] += 1
            return

        # All leaf datasets are deleted — mark collection for deletion
        create_time = detail.get("create_time")
        self.log_deletion(create_time, "collection", collection_id, name, history_id)
        if not self.dry_run:
            try:
                self.gi.histories.delete_dataset_collection(
                    history_id, collection_id
                )
            except Exception as exc:
                self.logger.error(
                    "Failed to delete collection %s: %s", collection_id, exc
                )
                return
        self.counts["collections_deleted"] += 1

    def maybe_delete_history(
        self, detail: dict, history_id: str, history_name: str
    ):
        """Delete a history if all its contents are now deleted (either
        pre-existing or by this script). The history's own creation date is
        not considered — only the emptiness of its contents matters."""

        # Re-fetch active contents. In live mode, items deleted earlier in this
        # run won't appear. In dry-run mode they still appear, so we check
        # deleted_ids to account for what would have been deleted.
        try:
            contents = self.get_history_contents(history_id)
        except Exception as exc:
            self.logger.warning(
                "Cannot re-fetch contents of history %s for eligibility check: %s",
                history_id, exc,
            )
            return

        remaining = [
            item for item in contents
            if item["id"] not in self.deleted_ids
        ]

        all_gone = len(remaining) == 0
        if not all_gone:
            for item in remaining:
                self.logger.debug(
                    "History %s has non-deleted item %s (%s) — cannot delete history.",
                    history_id, item["id"], item.get("name", "?"),
                )

        if not all_gone:
            self.counts["skipped_not_fully_deleted"] += 1
            self.counts["histories_kept"] += 1
            return

        create_time = detail.get("create_time")
        self.log_deletion(create_time, "history", history_id, history_name)
        if not self.dry_run:
            try:
                self.gi.histories.delete_history(history_id, purge=False)
            except Exception as exc:
                self.logger.error(
                    "Failed to delete history %s: %s", history_id, exc
                )
                return
        self.counts["histories_deleted"] += 1

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def print_summary(self):
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        self.logger.info("=" * 60)
        self.logger.info("Summary (%s)", mode)
        self.logger.info("  Datasets marked for deletion   : %d", self.counts["datasets_deleted"])
        self.logger.info("  Collections marked for deletion: %d", self.counts["collections_deleted"])
        self.logger.info("  Histories marked for deletion  : %d", self.counts["histories_deleted"])
        self.logger.info("  Skipped (shared/published)     : %d", self.counts["skipped_shared"])
        self.logger.info("  Skipped (out of year range)    : %d", self.counts["skipped_out_of_range"])
        self.logger.info("  Skipped (history not fully del): %d", self.counts["skipped_not_fully_deleted"])
        self.logger.info("  Histories kept (not emptied)   : %d", self.counts["histories_kept"])
        self.logger.info("=" * 60)
        if self.dry_run:
            self.logger.info(
                "This was a DRY-RUN. Re-run with --delete to perform actual deletions."
            )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=(
            "Mark Galaxy data for deletion for a given user and year range. "
            "Runs as a dry-run by default; use --delete to apply changes."
        )
    )
    parser.add_argument(
        "--url", required=True,
        help="Base URL of the Galaxy server, e.g. https://usegalaxy.org",
    )
    parser.add_argument(
        "--api-key", required=True,
        help="Admin API key (must have admin privileges to act on other users).",
    )
    parser.add_argument(
        "--email", required=True,
        help="Email address of the Galaxy user whose data should be cleaned up.",
    )
    parser.add_argument(
        "--year", required=True,
        help=(
            "Target year or year range. Datasets created within this range are "
            "candidates for deletion. Examples: '2022' or '2022-2024'."
        ),
    )
    parser.add_argument(
        "--delete", action="store_true", default=False,
        help="Actually perform deletions. Without this flag, only a dry-run is done.",
    )
    parser.add_argument(
        "--log",
        default="deleted_",
        help="Path to the log file for deleted entries (default: deleted_<user>_<time>.log).",
    )

    parser.add_argument(
        "--verbose", "-v", action="store_true", default=False,
        help="Enable DEBUG level log output.",
    )

    args = parser.parse_args()

    # Parse year / year-range argument
    current_year = datetime.now().year
    year_arg = args.year.strip()
    if "-" in year_arg:
        parts = year_arg.split("-", 1)
        try:
            start_year, end_year = int(parts[0]), int(parts[1])
        except ValueError:
            parser.error("--year range must be in the form YYYY-YYYY, e.g. 2022-2024.")
    else:
        try:
            start_year = end_year = int(year_arg)
        except ValueError:
            parser.error("--year must be a year (e.g. 2022) or a range (e.g. 2022-2024).")

    if not (2000 <= start_year <= current_year and 2000 <= end_year <= current_year):
        parser.error(f"Years must be between 2000 and {current_year}.")
    if start_year > end_year:
        parser.error(f"Start year ({start_year}) must not be greater than end year ({end_year}).")

    if args.log == "deleted_":
        log_path = Path(f"deleted_{args.email}_{year_arg}.log")
    else:
        log_path = Path(args.log)

    cleanup = GalaxyCleanup(
        galaxy_url=args.url,
        api_key=args.api_key,
        user_email=args.email,
        start_year=start_year,
        end_year=end_year,
        dry_run=not args.delete,
        log_path=log_path,
        verbose=args.verbose,
    )
    cleanup.run()


if __name__ == "__main__":
    main()
