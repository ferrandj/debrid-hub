from __future__ import annotations

import time
from datetime import datetime

import pytest

from debrid_hub.watchfolder import (
    WatchFolderCleaner,
    drop_filename,
    purge_expired,
    sanitize_label,
    write_drop,
)
from debrid_hub.config import Settings


class TestSanitizeLabel:
    def test_replaces_unsafe_characters(self):
        assert sanitize_label("Some Movie (2026)/weird:name?.mkv") == "Some_Movie_2026_weird_name_.mkv"

    def test_empty_falls_back_to_download(self):
        assert sanitize_label("") == "download"
        assert sanitize_label("   ") == "download"

    def test_truncates_long_labels(self):
        assert len(sanitize_label("x" * 500)) <= 80


class TestDropFilename:
    def test_includes_sanitized_label_and_timestamp(self):
        now = datetime(2026, 7, 24, 15, 30, 12)
        assert drop_filename("Ubuntu 22.04", now) == "Ubuntu_22.04_20260724-153012.crawljob"


class TestWriteDrop:
    def test_writes_one_blank_line_separated_block_per_url(self, tmp_path):
        folder = tmp_path / "watch"
        path = write_drop(str(folder), "My Download", ["https://a", "https://b"])
        assert path.parent == folder
        assert path.suffix == ".crawljob"
        assert path.read_text() == (
            "deepAnalyseEnabled=true\ntext=https://a\n\n"
            "deepAnalyseEnabled=true\ntext=https://b\n"
        )

    def test_single_url_has_no_stray_blank_line(self, tmp_path):
        folder = tmp_path / "watch"
        path = write_drop(str(folder), "x", ["https://a"])
        assert path.read_text() == "deepAnalyseEnabled=true\ntext=https://a\n"

    def test_creates_folder_if_missing(self, tmp_path):
        folder = tmp_path / "nested" / "watch"
        path = write_drop(str(folder), "x", ["https://a"])
        assert path.exists()

    def test_raises_without_folder(self):
        with pytest.raises(ValueError):
            write_drop("", "x", ["https://a"])

    def test_raises_without_urls(self, tmp_path):
        with pytest.raises(ValueError):
            write_drop(str(tmp_path), "x", [])


class TestPurgeExpired:
    def test_removes_only_files_older_than_cutoff(self, tmp_path):
        old = tmp_path / "old.txt"
        old.write_text("x")
        old_time = time.time() - 3600
        import os
        os.utime(old, (old_time, old_time))

        fresh = tmp_path / "fresh.txt"
        fresh.write_text("x")

        removed = purge_expired(str(tmp_path), max_age_minutes=1)
        assert removed == 1
        assert not old.exists()
        assert fresh.exists()

    def test_noop_when_disabled(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("x")
        assert purge_expired(str(tmp_path), max_age_minutes=0) == 0
        assert purge_expired("", max_age_minutes=10) == 0
        assert f.exists()

    def test_noop_on_missing_folder(self, tmp_path):
        assert purge_expired(str(tmp_path / "nope"), max_age_minutes=1) == 0


class TestWatchFolderCleaner:
    async def test_does_not_start_task_when_unconfigured(self):
        cleaner = WatchFolderCleaner(Settings())
        cleaner.start()
        assert cleaner._task is None
        await cleaner.stop()

    async def test_stop_is_safe_without_start(self):
        cleaner = WatchFolderCleaner(Settings())
        await cleaner.stop()
