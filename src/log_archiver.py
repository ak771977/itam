"""
LOG ARCHIVER
Automatically archives daily logs into monthly zip files.
"""
from __future__ import annotations

import glob
import logging
import os
import re
import zipfile
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class LogArchiver:
    """Archive daily logs into monthly zip files."""

    def __init__(self, logs_dir: str = "logs", archive_dir: str | None = None, months_to_keep: int = 3, log_filename: str = "xu_ml_bot.log"):
        self.logs_dir = logs_dir
        self.archive_dir = archive_dir or os.path.join(logs_dir, "archives")
        self.months_to_keep = months_to_keep
        self.log_basename = os.path.basename(log_filename or "xu_ml_bot.log")
        os.makedirs(self.archive_dir, exist_ok=True)

    def archive_old_logs(self):
        """Archive daily log files into monthly zip files and prune older archives."""
        try:
            logger.info("Starting log archiving...")
            log_pattern = os.path.join(self.logs_dir, f"{self.log_basename}.*")
            log_files = glob.glob(log_pattern)

            if not log_files:
                logger.info("No old logs to archive")
                return

            archived_count = 0
            for log_file in log_files:
                basename = os.path.basename(log_file)
                pattern = rf"{re.escape(self.log_basename)}\.(\d{{4}}-\d{{2}}-\d{{2}})"
                match = re.search(pattern, basename)
                if not match:
                    continue

                date_str = match.group(1)
                log_date = datetime.strptime(date_str, "%Y-%m-%d")
                if (datetime.now() - log_date).days < 1:
                    continue

                month_key = log_date.strftime("%Y-%m")
                zip_filename = os.path.join(self.archive_dir, f"{month_key}.zip")

                try:
                    with zipfile.ZipFile(zip_filename, "a", zipfile.ZIP_DEFLATED) as zipf:
                        existing_files = zipf.namelist()
                        log_basename = os.path.basename(log_file)

                        if log_basename not in existing_files:
                            zipf.write(log_file, arcname=log_basename)
                            logger.info("Archived: %s → %s", log_basename, f"{month_key}.zip")
                            os.remove(log_file)
                            archived_count += 1
                        else:
                            os.remove(log_file)
                            logger.info("Removed duplicate: %s", log_basename)
                            archived_count += 1

                except Exception as exc:
                    logger.error("Failed to archive %s: %s", log_file, exc)

            if archived_count > 0:
                logger.info("Archived %d log file(s)", archived_count)

            self._cleanup_old_archives()

        except Exception as exc:
            logger.error("Error during log archiving: %s", exc)

    def _cleanup_old_archives(self):
        """Remove zip files older than X months."""
        try:
            zip_pattern = os.path.join(self.archive_dir, "*.zip")
            zip_files = glob.glob(zip_pattern)
            if not zip_files:
                return

            cutoff_date = datetime.now() - timedelta(days=self.months_to_keep * 30)
            removed_count = 0
            for zip_file in zip_files:
                match = re.search(r"(\d{4}-\d{2})\.zip", zip_file)
                if not match:
                    continue

                month_str = match.group(1)
                zip_date = datetime.strptime(month_str + "-01", "%Y-%m-%d")
                if zip_date < cutoff_date:
                    os.remove(zip_file)
                    logger.info("Removed old archive: %s", os.path.basename(zip_file))
                    removed_count += 1

            if removed_count > 0:
                logger.info("Cleaned up %d old archive(s)", removed_count)

        except Exception as exc:
            logger.error("Error cleaning up archives: %s", exc)

    def get_archive_stats(self):
        """Get statistics about archived logs."""
        zip_pattern = os.path.join(self.archive_dir, "*.zip")
        zip_files = glob.glob(zip_pattern)
        total_size = 0
        archive_info = []

        for zip_file in zip_files:
            size = os.path.getsize(zip_file)
            total_size += size
            with zipfile.ZipFile(zip_file, "r") as zipf:
                file_count = len(zipf.namelist())
            archive_info.append(
                {
                    "filename": os.path.basename(zip_file),
                    "size_mb": size / (1024 * 1024),
                    "files": file_count,
                }
            )

        return {
            "total_archives": len(zip_files),
            "total_size_mb": total_size / (1024 * 1024),
            "archives": sorted(archive_info, key=lambda x: x["filename"], reverse=True),
        }
