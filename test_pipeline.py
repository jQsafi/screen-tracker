"""
Comprehensive test suite for the Screen Tracker pipeline.
Tests Database, App Detector, Capturer, OCR Engine, GitHub Sync, and End-to-End cycle.
"""

from pathlib import Path
import shutil
import tempfile
import unittest

from app_detector import ActiveAppDetector
from capturer import ScreenCapturer
from config import Config
from database import TrackerDatabase
from github_sync import GitHubSync
from main import ScreenTrackerApp
from ocr_engine import OCREngine
from web_server import WebDashboard
import urllib.request
import json


class TestTrackerDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_tracker.db"
        self.db = TrackerDatabase(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_insert_and_get_recent(self):
        record_id = self.db.insert_screenshot(
            timestamp="2026-10-20T12:00:00Z",
            app_name="TestApp",
            window_title="Test Window",
            extracted_text="Hello world from OCR test",
            image_path="/tmp/test.png",
            image_blob=b"test_image_bytes",
        )
        self.assertGreaterEqual(record_id, 1)

        recent = self.db.get_recent(limit=5)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["app_name"], "TestApp")
        self.assertEqual(recent[0]["extracted_text"], "Hello world from OCR test")
        self.assertEqual(recent[0]["github_pushed"], 0)

    def test_search_text(self):
        self.db.insert_screenshot(
            timestamp="2026-10-20T12:01:00Z",
            app_name="Chrome",
            window_title="GitHub Pull Requests",
            extracted_text="Merge pull request #42 into main branch",
            image_path="/tmp/chrome.png",
        )
        results = self.db.search_text("pull request")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["app_name"], "Chrome")

    def test_mark_as_pushed_and_stats(self):
        rec_id = self.db.insert_screenshot(
            timestamp="2026-10-20T12:02:00Z",
            app_name="VSCode",
            window_title="main.py",
            extracted_text="print('hello')",
            image_path="/tmp/code.png",
        )
        self.db.mark_as_pushed(rec_id, "abc123commit")

        stats = self.db.get_stats()
        self.assertEqual(stats["total_captured"], 1)
        self.assertEqual(stats["github_pushed"], 1)
        self.assertEqual(stats["pending_push"], 0)


class TestAppDetector(unittest.TestCase):
    def test_get_active_app(self):
        detector = ActiveAppDetector()
        info = detector.get_active_app()
        self.assertIsInstance(info, dict)
        self.assertIn("app_name", info)
        self.assertIn("window_title", info)
        self.assertTrue(len(info["app_name"]) > 0)


class TestScreenCapturer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.capturer = ScreenCapturer(Path(self.temp_dir))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_capture(self):
        timestamp, img_path, raw_bytes, pil_img = self.capturer.capture()
        self.assertTrue(img_path.exists())
        self.assertGreater(img_path.stat().st_size, 0)
        self.assertIsNotNone(timestamp)
        self.assertIsNotNone(raw_bytes)


class TestGitHubSync(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.git = GitHubSync(Path(self.temp_dir))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_and_commit(self):
        self.assertTrue(self.git.init_repo())
        self.assertTrue(self.git.is_git_repo())

        # Configure dummy git author for commit test
        self.git._run_git(["config", "user.name", "Test Runner"])
        self.git._run_git(["config", "user.email", "test@example.com"])

        # Create a sample file
        sample_file = Path(self.temp_dir) / "sample_screen.png"
        sample_file.write_bytes(b"sample bytes")

        # Attempt commit (push will fail gracefully because no remote exists)
        success, commit_hash, err = self.git.commit_and_push(
            sample_file, "TestApp", "2026-10-20T12:00:00Z"
        )
        self.assertIsNotNone(commit_hash)
        self.assertTrue(len(commit_hash) >= 7)


class TestEndToEndPipeline(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cfg = Config(
            interval_seconds=1.0,
            output_dir=Path(self.temp_dir) / "screenshots",
            db_path=Path(self.temp_dir) / "test.db",
            git_enabled=False,
            store_image_blob=True,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_full_cycle(self):
        app = ScreenTrackerApp(self.cfg)
        record_id = app.run_single_cycle()
        self.assertGreaterEqual(record_id, 1)

        db = TrackerDatabase(self.cfg.db_path)
        recent = db.get_recent(limit=1)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["id"], record_id)
        self.assertTrue(Path(recent[0]["image_path"]).exists())


class TestWebDashboard(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.cfg = Config(
            interval_seconds=1.0,
            output_dir=Path(self.temp_dir) / "screenshots",
            db_path=Path(self.temp_dir) / "test.db",
            git_enabled=False,
        )
        self.app = ScreenTrackerApp(self.cfg)
        self.port = 8995
        self.web = WebDashboard(app_instance=self.app, host="127.0.0.1", port=self.port)
        self.web.start()

    def tearDown(self):
        self.web.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_dashboard_endpoints(self):
        base_url = f"http://127.0.0.1:{self.port}"

        # 1. Test HTML Dashboard
        req = urllib.request.Request(f"{base_url}/")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            body = resp.read().decode("utf-8")
            self.assertIn("Screen Tracker Dashboard", body)

        # 2. Test Stats API
        req = urllib.request.Request(f"{base_url}/api/stats")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("total_captured", data)

        # 3. Test Trigger Capture API
        post_req = urllib.request.Request(f"{base_url}/api/capture_now", data=b"{}", method="POST")
        with urllib.request.urlopen(post_req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data.get("success"))

        # 4. Test Screenshots API
        req = urllib.request.Request(f"{base_url}/api/screenshots?limit=5")
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertIn("items", data)
            self.assertGreaterEqual(len(data["items"]), 1)


if __name__ == "__main__":
    unittest.main()
