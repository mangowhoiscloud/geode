"""Tests for ResultCache TTL expiry and content hash verification."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest
from core.cli.result_cache import _DEFAULT_TTL_SECONDS, ResultCache


class TestResultCacheExpiry:
    """Tests for 24h TTL-based cache expiry."""

    @pytest.fixture()
    def cache_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "result_cache"
        d.mkdir()
        return d

    @pytest.fixture()
    def cache(self, cache_dir: Path) -> ResultCache:
        return ResultCache(cache_dir=cache_dir)

    def test_put_adds_cached_at(self, cache: ResultCache):
        before = time.time()
        cache.put({"ip_name": "Berserk", "tier": "S", "score": 81.3})
        after = time.time()
        entry = cache.get("Berserk")
        assert entry is not None
        assert before <= entry["_cached_at"] <= after

    def test_put_adds_content_hash(self, cache: ResultCache):
        cache.put({"ip_name": "Berserk", "tier": "S", "score": 81.3})
        entry = cache.get("Berserk")
        assert entry is not None
        assert "_content_hash" in entry
        assert len(entry["_content_hash"]) == 16  # truncated SHA-256

    def test_fresh_entry_not_expired(self, cache: ResultCache):
        cache.put({"ip_name": "Berserk", "tier": "S"})
        result = cache.get("Berserk")
        assert result is not None

    def test_expired_entry_returns_none(self, cache_dir: Path):
        cache = ResultCache(cache_dir=cache_dir, ttl_seconds=0.01)
        cache.put({"ip_name": "Berserk", "tier": "S"})
        time.sleep(0.02)
        result = cache.get("Berserk")
        assert result is None

    def test_custom_ttl(self, cache_dir: Path):
        cache = ResultCache(cache_dir=cache_dir, ttl_seconds=3600)
        cache.put({"ip_name": "Berserk", "tier": "S"})
        result = cache.get("Berserk")
        assert result is not None

    def test_legacy_entry_without_cached_at_not_expired(self, cache: ResultCache):
        # Simulate a legacy entry without _cached_at
        cache._cache["legacy"] = {"ip_name": "Legacy", "tier": "A"}
        result = cache.get("Legacy")
        assert result is not None

    def test_default_ttl_is_24_hours(self):
        assert _DEFAULT_TTL_SECONDS == 86400


class TestResultCacheContentHash:
    """Tests for content hash verification."""

    @pytest.fixture()
    def cache_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "result_cache"
        d.mkdir()
        return d

    @pytest.fixture()
    def cache(self, cache_dir: Path) -> ResultCache:
        return ResultCache(cache_dir=cache_dir)

    def test_hash_matches_on_normal_load(self, cache: ResultCache, cache_dir: Path):
        cache.put({"ip_name": "Berserk", "tier": "S", "score": 81.3})
        # Reload from disk
        cache2 = ResultCache(cache_dir=cache_dir)
        result = cache2.get("Berserk")
        assert result is not None
        assert result["tier"] == "S"

    def test_corrupted_entry_skipped_on_disk_load(self, cache: ResultCache, cache_dir: Path):
        cache.put({"ip_name": "Berserk", "tier": "S", "score": 81.3})
        # Tamper with the file
        fpath = cache_dir / "berserk.json"
        data = json.loads(fpath.read_text(encoding="utf-8"))
        data["tier"] = "C"  # corrupt the data but keep the old hash
        fpath.write_text(json.dumps(data), encoding="utf-8")
        # Reload -- should skip corrupted entry
        cache2 = ResultCache(cache_dir=cache_dir)
        result = cache2.get("Berserk")
        assert result is None

    def test_legacy_entry_without_hash_accepted(self, cache_dir: Path):
        # Write an entry without _content_hash
        fpath = cache_dir / "legacy.json"
        data = {"ip_name": "Legacy", "tier": "B", "_cached_at": time.time()}
        fpath.write_text(json.dumps(data), encoding="utf-8")
        cache = ResultCache(cache_dir=cache_dir)
        result = cache.get("Legacy")
        assert result is not None

    def test_hash_excludes_cache_metadata(self, cache: ResultCache):
        """_cached_at and _content_hash should not affect the hash itself."""
        data = {"ip_name": "Test", "tier": "A", "score": 70.0}
        cache.put(data)
        entry = cache.get("Test")
        assert entry is not None
        # Recompute hash -- should match
        assert cache._is_hash_valid(entry) is True


class TestResultCacheDiskExpiry:
    """Tests for expired entries being skipped during disk load."""

    def test_expired_files_skipped_on_load(self, tmp_path: Path):
        cache_dir = tmp_path / "result_cache"
        cache_dir.mkdir()
        # Write an expired entry
        fpath = cache_dir / "old.json"
        data = {
            "ip_name": "Old",
            "tier": "C",
            "_cached_at": time.time() - 100000,  # way past 24h
            "_content_hash": "",  # empty hash = skip hash check
        }
        fpath.write_text(json.dumps(data), encoding="utf-8")
        # Write a fresh entry
        fpath2 = cache_dir / "fresh.json"
        data2 = {
            "ip_name": "Fresh",
            "tier": "S",
            "_cached_at": time.time(),
        }
        # Compute hash for fresh
        clean = {k: v for k, v in data2.items() if not k.startswith("_c")}
        h = hashlib.sha256(json.dumps(clean, sort_keys=True).encode()).hexdigest()[:16]
        data2["_content_hash"] = h
        fpath2.write_text(json.dumps(data2), encoding="utf-8")

        cache = ResultCache(cache_dir=cache_dir)
        assert cache.get("Old") is None
        assert cache.get("Fresh") is not None

    def test_put_does_not_mutate_input(self, tmp_path: Path):
        """put() should not mutate the caller's dict."""
        cache_dir = tmp_path / "result_cache"
        cache_dir.mkdir()
        cache = ResultCache(cache_dir=cache_dir)
        original = {"ip_name": "Test", "tier": "A"}
        cache.put(original)
        assert "_cached_at" not in original
        assert "_content_hash" not in original


class TestResultCacheBackwardCompat:
    """Backward compatibility tests."""

    def test_result_cache_alias(self):
        from core.cli.result_cache import _ResultCache

        assert _ResultCache is ResultCache

    def test_basic_get_put(self, tmp_path: Path):
        cache_dir = tmp_path / "result_cache"
        cache_dir.mkdir()
        cache = ResultCache(cache_dir=cache_dir)
        cache.put({"ip_name": "Berserk", "tier": "S"})
        result = cache.get("Berserk")
        assert result is not None
        assert result["tier"] == "S"

    def test_lru_eviction(self, tmp_path: Path):
        cache_dir = tmp_path / "result_cache"
        cache_dir.mkdir()
        cache = ResultCache(max_size=2, cache_dir=cache_dir)
        cache.put({"ip_name": "A", "tier": "S"})
        cache.put({"ip_name": "B", "tier": "A"})
        cache.put({"ip_name": "C", "tier": "B"})
        # A should be evicted
        assert cache.get("A") is None
        assert cache.get("B") is not None
        assert cache.get("C") is not None
