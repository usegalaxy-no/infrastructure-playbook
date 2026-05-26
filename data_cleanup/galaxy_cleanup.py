#!/usr/bin/env python3
"""
galaxy_cleanup.py — Galaxy data cleanup script using the BioBlend API.

Marks datasets, dataset collections, and histories for deletion on a per-user
and period basis. No data is purged by this script. Shared or published histories
are never touched. Dry-run is the default; pass --delete to perform actual deletions.

Deletion rules:
  - A dataset is eligible for deletion if its create_time is equal to or older
    than the target year.
  - A collection is eligible if its create_time is equal to or older than the
    target year. Because data collections contain shallow copies of datasets
    whose create_time equals the collection's own create_time, it is sufficient
    to check the top-level collection timestamp — no recursive traversal is needed.
  - A history is deleted as a unit (without individually deleting its contents first)
    if either:
      (a) [Tier 1] its update_time is equal to or older than the target year —
          meaning nothing in the history has been modified since then, so all
          contents are necessarily eligible; or
      (b) [Tier 2] after inspecting all contents, every item is found to be
          eligible for deletion (or is an unknown content type that blocks
          deletion — see below).
    In both cases only the history is logged; undeleting it restores all
    contents in a single step.
  - If a history cannot be fully deleted, eligible collections are deleted
    individually (one API call each) and eligible datasets are batch-deleted
    in a single API call. Each deleted item is logged individually.
  - Unknown content types (neither dataset nor dataset_collection) are ignored
    during inspection but treated as ineligible, blocking whole-history deletion.

Sharing rules:
  - Sharing/publication is checked at the history level only, via the
    /api/histories/{id}/sharing endpoint. Individual datasets and collections
    are not checked for sharing, since it was determined that this is
    not really necessary for UseGalaxy.no
  - Histories that are shared or published are never touched

Usage:
    python galaxy_cleanup.py --url <GALAXY_URL> --api-key <ADMIN_API_KEY> \
        --email <USER_EMAIL> --year <YEAR> [--delete] [--log <LOGFILE>] \
        [--verbose]

Requirements:
    pip install bioblend
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from bioblend.galaxy import GalaxyInstance
except ImportError:
    sys.exit("ERROR: bioblend is not installed. Run: pip install bioblend")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_galaxy_time(time_str: str | None) -> datetime | None:
    """Parse a Galaxy ISO-8601 timestamp into an aware datetime (UTC)."""
    if not time_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(time_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def year_of(time_str: str | None) -> int | None:
    """Return the year component of a Galaxy timestamp, or None."""
    dt = parse_galaxy_time(time_str)
    return dt.year if dt is not None else None


def created_in_or_before(time_str: str | None, year: int) -> bool:
    """Return True if the timestamp falls in or before the given year."""
    y = year_of(time_str)
    return y is not None and y <= year


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

class GalaxyCleanup:
    def __init__(
        self,
        galaxy_url: str,
        api_key: str,
        user_email: str,
        year: int,
        dry_run: bool,
        log_path: Path,
        verbose: bool = False,
    ):
        # Admin GalaxyInstance — used only for privileged calls (user lookup,
        # API key retrieval, sharing checks). Never used for data browsing or
        # deletion.
        self.admin_gi = GalaxyInstance(url=galaxy_url, key=api_key)
        self.galaxy_url = galaxy_url

        # User-scoped GalaxyInstance — initialised in run() once we have the
        # target user's API key. All data browsing and deletions go through
        # this so Galaxy's own permission rules apply.
        self.gi: GalaxyInstance | None = None

        self.user_email = user_email
        self.target_year = year
        self.dry_run = dry_run
        self.log_path = log_path
        self.verbose = verbose

        # Accumulates TSV log lines: created, kind, object_id, history_id
        self.deletion_log: list[str] = []

        self.counts = {
            "datasets_deleted": 0,
            "collections_deleted": 0,
            "histories_deleted": 0,
            "skipped_shared": 0,
            "skipped_out_of_range": 0,
            "histories_kept": 0,
            "histories_partial": 0,
            "histories_inspected": 0,
            "histories_problems": 0,
        }

        self._setup_logging()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _setup_logging(self):
        self.logger = logging.getLogger("galaxy_cleanup")
        self.logger.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        ch.setFormatter(fmt)
        self.logger.addHandler(ch)

    def _log_deletion(
        self,
        timestamp: str | None,
        kind: str,
        obj_id: str,
        name: str,
        history_id: str | None = None,
    ):
        date_str = (timestamp or "unknown")[:10]
        line = f"{date_str}\t{kind}\t{obj_id}\t{history_id or '-'}"
        self.deletion_log.append(line)
        prefix = "[DRY-RUN] " if self.dry_run else ""
        self.logger.debug(
            "%sMARK FOR DELETION  %-10s  id=%-18s  name=%s",
            prefix, kind, obj_id, name,
        )

    def _write_log(self):
        with self.log_path.open("w", encoding="utf-8") as fh:
            fh.write("# created\tkind\tobject_id\thistory_id\n")
            for line in self.deletion_log:
                fh.write(line + "\n")
        self.logger.info("Deletion log written to: %s", self.log_path)

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

    def _get_user_histories(self) -> list[dict]:
        """Return all active (non-deleted) histories for the user-scoped instance."""
        return self.gi.histories.get_histories(deleted=False)

    def _get_history_detail(self, history_id: str) -> dict:
        return self.gi.histories.show_history(history_id, contents=False)

    def _get_history_contents(self, history_id: str) -> list[dict]:
        """Return all active (non-deleted) top-level items in a history.

        Deleted items are excluded by the deleted=False filter, so they do not
        appear as "remaining" contents when we check whether a history is empty.
        """
        return self.gi.histories.show_history(history_id, contents=True, deleted=False)

#    def _get_collection_detail(self, history_id: str, collection_id: str) -> dict:
#        return self.gi.histories.show_dataset_collection(history_id, collection_id)

    def _history_is_shared(self, history_id: str) -> bool:
        """
        Return True if this history is shared or published in any way,
        by calling /api/histories/{id}/sharing, which covers:
          - published:          visible to all Galaxy users
          - importable:         accessible to anyone with the share link
          - users_shared_with:  explicitly shared with named individuals

        Defaults to True (treat as shared) on any error, to be conservative.
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
                    self.logger.debug(
                        "History %s is accessible via share link.", history_id
                    )
                    return True
                if sharing.get("users_shared_with"):
                    self.logger.debug(
                        "History %s is shared with %d individual user(s).",
                        history_id, len(sharing["users_shared_with"]),
                    )
                    return True
                return False
            else:
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

    def _batch_delete_datasets(self, history_id: str, dataset_ids: list[str]):
        """
        Delete multiple datasets in a single DELETE /api/datasets request.
        Each dataset is identified by its HDA id.
        """
        payload = {
            "datasets": [{"src": "hda", "id": did} for did in dataset_ids],
            "purge": False,
        }
        response = self.gi.make_delete_request(
            f"{self.gi.base_url}/api/datasets",
            payload=payload,
        )
        if response.status_code not in (200, 204):
            raise RuntimeError(
                f"Batch dataset delete returned HTTP {response.status_code}: "
                f"{response.text}"
            )


    # ------------------------------------------------------------------
    # Eligibility checks (pure inspection — no deletions)
    # ------------------------------------------------------------------

    def _dataset_is_eligible(self, item: dict) -> bool:
        """Return True if a history content summary dict represents an eligible dataset."""
        return created_in_or_before(item.get("create_time"), self.target_year)

    def _collection_is_eligible(self, item: dict) -> bool:
        """
        Return True if a top-level collection is eligible for deletion.

        Galaxy collections contain shallow copies of datasets whose create_time
        equals the collection's own create_time, so checking the top-level
        timestamp is sufficient — no recursive inspection of elements is needed.
        """
        return created_in_or_before(item.get("create_time"), self.target_year)

    def _classify_contents(
        self, contents: list[dict]
    ) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
        """
        Partition history contents into five lists:
          - eligible_datasets:      datasets with create_time <= target year
          - ineligible_datasets:    datasets with create_time > target year
          - eligible_collections:   collections with create_time <= target year
          - ineligible_collections: collections with create_time > target year
          - ineligible_items:       unknown types

        Unknown content types are placed in ineligible_items, which blocks
        whole-history deletion but does not prevent partial cleanup.
        """
        eligible_datasets: list[dict] = []
        ineligible_datasets: list[dict] = []
        eligible_collections: list[dict] = []
        ineligible_collections: list[dict] = []
        ineligible_items: list[dict] = []

        for item in contents:
            content_type = item.get("history_content_type")
            if content_type == "dataset":
                if self._dataset_is_eligible(item):
                    eligible_datasets.append(item)
                else:
                    ineligible_datasets.append(item)
            elif content_type == "dataset_collection":
                if self._collection_is_eligible(item):
                    eligible_collections.append(item)
                else:
                    ineligible_collections.append(item)
            else:
                self.logger.debug(
                    "Unknown content type '%s' for item %s — treating as ineligible.",
                    content_type, item.get("id", "?"),
                )
                ineligible_items.append(item)

        return eligible_datasets, ineligible_datasets, eligible_collections, ineligible_collections, ineligible_items

    # ------------------------------------------------------------------
    # Main cleanup logic
    # ------------------------------------------------------------------

    def run(self):
        mode = "DRY-RUN" if self.dry_run else "LIVE DELETION"
        self.logger.info("=" * 60)
        self.logger.info("Galaxy Cleanup  |  mode=%s", mode)
        self.logger.info("Target user  : %s", self.user_email)
        self.logger.info("Target year  : %s", self.target_year)
        self.logger.info("=" * 60)

        user = self._get_target_user()
        user_id = user["id"]
        self.logger.info("Resolved user id: %s", user_id)

        user_api_key = self._get_user_api_key(user_id)
        self.gi = GalaxyInstance(url=self.galaxy_url, key=user_api_key)
        self.logger.info("Obtained user-scoped API key for %s", self.user_email)

        histories = self._get_user_histories()
        self.logger.info("Found %d histories to inspect.", len(histories))
        self.counts["histories_inspected"] = len(histories)

        for history_summary in histories:
            self._process_history(history_summary)

        self._write_log()
        self._print_summary()

    def _process_history(self, history_summary: dict):
        history_id = history_summary["id"]
        history_name = history_summary.get("name", "<unnamed>")
        self.logger.info("Inspecting history: \"%s\" (%s)", history_name, history_id)

        # Safety: never touch shared/published histories.
        if self._history_is_shared(history_id):
            self.logger.debug(
                "History %s is shared/published — skipping entirely.", history_id
            )
            self.counts["skipped_shared"] += 1
            self.counts["histories_kept"] += 1
            return

        update_time = history_summary.get("update_time")

        # ------------------------------------------------------------------
        # Tier 1 fast path: update_time <= target year.
        #
        # Nothing in this history has been modified since the target year, so
        # every item inside it is necessarily eligible. Delete the history as a
        # unit without fetching or inspecting its contents. Undeleting restores
        # all contents in a single step.
        # ------------------------------------------------------------------
        if created_in_or_before(update_time, self.target_year):
            self.logger.debug(
                "History %s: update_time %s <= %d — Tier 1, deleting as a unit.",
                history_id, update_time, self.target_year,
            )
            self._log_deletion(update_time, "history", history_id, history_name)
            if not self.dry_run:
                try:
                    self.gi.histories.delete_history(history_id, purge=False)
                except Exception as exc:
                    self.logger.error(
                        "Failed to delete history %s: %s", history_id, exc
                    )
                    return
            self.counts["histories_deleted"] += 1
            return

        # ------------------------------------------------------------------
        # update_time > target year: fetch detail to get create_time.
        #
        # Copied/imported datasets always receive a fresh create_time stamp,
        # so a history created after the target year cannot contain any
        # eligible items. Skip it entirely without fetching contents.
        # ------------------------------------------------------------------
        try:
            detail = self._get_history_detail(history_id)
        except Exception as exc:
            self.logger.warning(
                "Could not fetch detail for history %s: %s — skipping.",
                history_id, exc,
            )
            self.counts["histories_problems"] += 1
            self.counts["histories_kept"] += 1
            return

        create_time = detail.get("create_time")
        if not created_in_or_before(create_time, self.target_year):
            self.logger.debug(
                "History %s was created after %d — skipping.",
                history_id, self.target_year,
            )
            self.counts["skipped_out_of_range"] += 1
            self.counts["histories_kept"] += 1
            return

        # ------------------------------------------------------------------
        # Tier 2: history was created within range but has been modified since
        # the target year. Inspect all contents to classify eligibility, then
        # decide in one step what to delete.
        # ------------------------------------------------------------------
        try:
            contents = self._get_history_contents(history_id)
        except Exception as exc:
            self.logger.warning(
                "Could not fetch contents of history %s: %s — skipping.",
                history_id, exc,
            )
            self.counts["histories_problems"] += 1
            return

        (
            eligible_datasets,
            ineligible_datasets,
            eligible_collections,
            ineligible_collections,
            ineligible_items,
        ) = self._classify_contents(contents)

        nothing_ineligible = not ineligible_datasets and not ineligible_collections and not ineligible_items
        something_eligible = bool(eligible_datasets or eligible_collections)
        history_is_empty = not contents

        if (nothing_ineligible and something_eligible) or history_is_empty:
            # ------------------------------------------------------------------
            # Tier 2 — whole-history deletion: every item is eligible.
            # Delete the history as a unit; log only the history entry.
            # ------------------------------------------------------------------
            self.logger.debug(
                "History %s: all %d item(s) eligible — deleting as a unit.",
                history_id, len(contents),
            )
            self._log_deletion(create_time, "history", history_id, history_name)
            if not self.dry_run:
                try:
                    self.gi.histories.delete_history(history_id, purge=False)
                except Exception as exc:
                    self.logger.error(
                        "Failed to delete history %s: %s", history_id, exc
                    )
                    return
            self.counts["histories_deleted"] += 1

        elif something_eligible:
            # ------------------------------------------------------------------
            # Tier 2 — partial deletion: some items are ineligible, so the
            # history must be kept. Delete eligible collections individually,
            # then batch-delete all eligible datasets in one API call.
            # ------------------------------------------------------------------
            self.logger.debug(
                "History %s: %d eligible dataset(s), %d eligible collection(s), "
                "%d ineligible item(s) — partial deletion.",
                history_id,
                len(eligible_datasets),
                len(eligible_collections),
                len(ineligible_datasets) + len(ineligible_collections) + len(ineligible_items),
            )

            # Delete eligible collections individually (no batch endpoint).
            for item in eligible_collections:
                collection_id = item["id"]
                name = item.get("name", "<unnamed>")
                create_time_c = item.get("create_time")
                self._log_deletion(
                    create_time_c, "collection", collection_id, name, history_id
                )
                if not self.dry_run:
                    try:
                        self.gi.histories.delete_dataset_collection(
                            history_id, collection_id
                        )
                    except Exception as exc:
                        self.logger.error(
                            "Failed to delete collection %s: %s", collection_id, exc
                        )
                self.counts["collections_deleted"] += 1

            # Log each eligible dataset individually for auditability, then
            # delete them all in a single batch API call.
            for item in eligible_datasets:
                self._log_deletion(
                    item.get("create_time"),
                    "dataset",
                    item["id"],
                    item.get("name", "<unnamed>"),
                    history_id,
                )
                self.counts["datasets_deleted"] += 1

            if not self.dry_run and eligible_datasets:
                dataset_ids = [item["id"] for item in eligible_datasets]
                try:
                    self._batch_delete_datasets(history_id, dataset_ids)
                except Exception as exc:
                    self.logger.error(
                        "Batch delete failed for %d dataset(s) in history %s: %s",
                        len(dataset_ids), history_id, exc,
                    )

            self.logger.debug("Keeping %d collections", len(ineligible_collections))
            if len(ineligible_collections) < 5:
                for item in ineligible_collections:
                    self.logger.debug("  - %s (%s) [%s]", item.get("name", "<unnamed>"), item["id"], item.get("create_time")[:10])

            self.logger.debug("Keeping %d datasets", len(ineligible_datasets))
            if len(ineligible_datasets) < 5:
                for item in ineligible_datasets:
                    self.logger.debug("  - %s (%s) [%s]", item.get("name", "<unnamed>"), item["id"], item.get("create_time")[:10])

            self.counts["histories_partial"] += 1
            self.counts["histories_kept"] += 1

        else:
            # Nothing in this history is eligible.
            self.logger.debug(
                "History %s: no eligible items — skipping.", history_id
            )
            self.counts["skipped_out_of_range"] += 1
            self.counts["histories_kept"] += 1

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def _print_summary(self):
        mode = "DRY-RUN" if self.dry_run else "LIVE"
        self.logger.info("=" * 60)
        self.logger.info("Summary (%s)", mode)
        self.logger.info("  Histories inspected            : %d", self.counts["histories_inspected"])
        self.logger.info("  Histories marked for deletion  : %d", self.counts["histories_deleted"])
        self.logger.info("  Histories kept                 : %d", self.counts["histories_kept"])
        self.logger.info("    - shared/published           : %d", self.counts["skipped_shared"])
        self.logger.info("    - all data was too recent    : %d", self.counts["skipped_out_of_range"]) # either history is too new or all the data is
        self.logger.info("    - only some data was deleted : %d", self.counts["histories_partial"])
        self.logger.info("    - problems during processing : %d", self.counts["histories_problems"])
        self.logger.info("  Datasets marked for deletion   : %d", self.counts["datasets_deleted"])
        self.logger.info("  Collections marked for deletion: %d", self.counts["collections_deleted"])
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
            "Mark Galaxy data for deletion for a given user and target year. "
            "Runs as a dry-run by default; use --delete to apply changes."
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
        help="Email address of the Galaxy user whose data should be cleaned up.",
    )
    parser.add_argument(
        "--year", required=True,
        help=(
            "Target year. Datasets created in this year or before are "
            "candidates for deletion. Example: '2022'."
        ),
    )
    parser.add_argument(
        "--delete", action="store_true", default=False,
        help="Actually perform deletions. Without this flag, only a dry-run is done.",
    )
    parser.add_argument(
        "--log", default="deleted_",
        help=(
            "Path to the TSV log file for deleted entries "
            "(default: deleted_<email>_<year>.log)."
        ),
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", default=False,
        help="Enable DEBUG level log output.",
    )

    args = parser.parse_args()

    current_year = datetime.now().year
    try:
        year = int(args.year.strip())
    except ValueError:
        parser.error("--year must be an integer year (e.g. 2022).")

    if not (2000 <= year <= current_year):
        parser.error(f"--year must be between 2000 and {current_year}.")

    log_path = (
        Path(f"deleted_{args.email}_{year}.log")
        if args.log == "deleted_"
        else Path(args.log)
    )

    cleanup = GalaxyCleanup(
        galaxy_url=args.url,
        api_key=args.api_key,
        user_email=args.email,
        year=year,
        dry_run=not args.delete,
        log_path=log_path,
        verbose=args.verbose,
    )
    cleanup.run()


if __name__ == "__main__":
    main()
