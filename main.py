"""
Main orchestrator for the Screen Tracker application.
Periodically captures screenshots, detects the active application, runs OCR,
stores metadata in SQLite, and commits/pushes screenshots to GitHub.
"""

import argparse
from datetime import datetime
import json
import logging
import signal
import sys
import time

from app_detector import ActiveAppDetector
from capturer import ScreenCapturer
from config import Config
from database import TrackerDatabase
from github_sync import GitHubSync
from ocr_engine import OCREngine
from web_server import WebDashboard

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ScreenTracker")

_RUNNING = True


def _handle_shutdown(signum, frame):
    global _RUNNING
    logger.info("Shutdown signal received (%s). Gracefully stopping...", signum)
    _RUNNING = False


class ScreenTrackerApp:
    """Coordinates capturing, active app extraction, OCR, database storage, and GitHub sync."""

    def __init__(self, config: Config):
        self.config = config
        self.db = TrackerDatabase(self.config.db_path)
        self.capturer = ScreenCapturer(self.config.output_dir)
        self.app_detector = ActiveAppDetector()
        self.ocr = OCREngine(
            lang=self.config.ocr_language,
            tesseract_cmd=self.config.tesseract_cmd,
        )
        self.git = GitHubSync(
            repo_dir=self.config.git_repo_dir,
            remote=self.config.git_remote,
            branch=self.config.git_branch,
            commit_prefix=self.config.git_commit_prefix,
        )

    def run_single_cycle(self) -> int:
        """
        Executes a single capture-extract-store-push cycle.
        Returns the database record ID.
        """
        logger.info("--- Starting Capture Cycle ---")

        # 1. Capture screen
        timestamp, img_path, raw_bytes, pil_img = self.capturer.capture()

        # 2. Extract active application & window title
        app_info = self.app_detector.get_active_app()
        app_name = app_info.get("app_name", "Unknown")
        window_title = app_info.get("window_title", "")
        logger.info("Active Application: '%s' | Window: '%s'", app_name, window_title)

        # 3. Extract text via OCR
        image_for_ocr = pil_img if pil_img is not None else img_path
        extracted_text = self.ocr.extract_text(image_for_ocr)
        preview_text = (extracted_text[:120] + "...") if len(extracted_text) > 120 else extracted_text
        logger.info("Extracted OCR Text (%d chars): %r", len(extracted_text), preview_text)

        # 4. Save to Database
        image_blob = raw_bytes if self.config.store_image_blob else None
        record_id = self.db.insert_screenshot(
            timestamp=timestamp,
            app_name=app_name,
            window_title=window_title,
            extracted_text=extracted_text,
            image_path=str(img_path),
            image_blob=image_blob,
        )

        # 5. Push to GitHub if enabled
        if self.config.git_enabled:
            logger.info("GitHub sync enabled. Committing & pushing %s...", img_path)
            success, commit_hash, err = self.git.commit_and_push(img_path, app_name, timestamp)
            if success and commit_hash:
                self.db.mark_as_pushed(record_id, commit_hash)
                logger.info("Screenshot #%d synced to GitHub (Commit: %s)", record_id, commit_hash[:7])
            elif err:
                logger.warning("GitHub sync note: %s", err)

        logger.info("--- Cycle Complete (Record #%d) ---", record_id)
        return record_id

    def run_daemon(self):
        """Continuously captures screenshots over time at configured interval."""
        global _RUNNING
        logger.info(
            "Screen Tracker daemon started. Interval: %s seconds. (Press Ctrl+C to stop)",
            self.config.interval_seconds,
        )

        while _RUNNING:
            start_time = time.time()
            try:
                self.run_single_cycle()
            except Exception as e:
                logger.error("Error occurred in capture cycle: %s", e, exc_info=True)

            # Sleep remaining time of the interval
            elapsed = time.time() - start_time
            sleep_time = max(0.0, self.config.interval_seconds - elapsed)

            # Responsive sleep check
            while _RUNNING and sleep_time > 0:
                chunk = min(1.0, sleep_time)
                time.sleep(chunk)
                sleep_time -= chunk

        logger.info("Screen Tracker stopped.")


def main():
    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)

    parser = argparse.ArgumentParser(
        description="Automated Screen Tracker: Periodic Screenshots, Active App Detection, OCR, SQLite & GitHub Push"
    )
    parser.add_argument("--interval", type=float, help="Seconds between screenshots (default: 60)")
    parser.add_argument("--once", action="store_true", help="Run one capture cycle and exit")
    parser.add_argument("--output-dir", type=str, help="Directory to save screenshots")
    parser.add_argument("--db", type=str, help="SQLite database path")
    parser.add_argument("--store-blob", action="store_true", help="Store raw image bytes directly inside SQLite")
    parser.add_argument("--git", action="store_true", help="Enable committing and pushing to GitHub")
    parser.add_argument("--remote", type=str, help="Git remote name (default: origin)")
    parser.add_argument("--branch", type=str, help="Git branch to push to (default: main)")
    parser.add_argument("--repo-dir", type=str, help="Git repository directory (default: current directory)")

    # Web Dashboard commands
    parser.add_argument("--web", action="store_true", help="Launch real-time web viewer dashboard alongside capture daemon")
    parser.add_argument("--web-only", action="store_true", help="Launch only the web viewer dashboard without capturing")
    parser.add_argument("--web-port", type=int, default=8080, help="Web dashboard port (default: 8080)")

    # Query & Utility commands
    parser.add_argument("--stats", action="store_true", help="Print summary statistics from database")
    parser.add_argument("--recent", type=int, nargs="?", const=10, help="Display recent N captures")
    parser.add_argument("--query", type=str, help="Search extracted OCR text in the database")

    args = parser.parse_args()

    cfg = Config.from_env()
    if args.interval:
        cfg.interval_seconds = args.interval
    if args.output_dir:
        cfg.output_dir = args.output_dir
    if args.db:
        cfg.db_path = args.db
    if args.store_blob:
        cfg.store_image_blob = True
    if args.git:
        cfg.git_enabled = True
    if args.remote:
        cfg.git_remote = args.remote
    if args.branch:
        cfg.git_branch = args.branch
    if args.repo_dir:
        cfg.git_repo_dir = args.repo_dir

    db = TrackerDatabase(cfg.db_path)

    # Handle query commands
    if args.stats:
        stats = db.get_stats()
        print("\n=== Screen Tracker Statistics ===")
        print(f"Total Captured: {stats['total_captured']}")
        print(f"GitHub Pushed : {stats['github_pushed']}")
        print(f"Pending Push  : {stats['pending_push']}")
        print("\nTop Applications:")
        for app in stats["top_apps"]:
            print(f"  - {app['app_name']}: {app['count']} captures")
        print("=================================\n")
        return

    if args.recent is not None:
        recent = db.get_recent(limit=args.recent)
        print(f"\n=== Last {len(recent)} Screenshot Captures ===")
        for r in recent:
            print(f"ID #{r['id']} | {r['timestamp']} | App: {r['app_name']} | Pushed: {bool(r['github_pushed'])}")
            print(f"   Window : {r['window_title']}")
            print(f"   File   : {r['image_path']}")
            text_snippet = (r['extracted_text'] or '').strip().replace('\n', ' ')
            if len(text_snippet) > 80:
                text_snippet = text_snippet[:80] + "..."
            print(f"   Text   : {text_snippet or '(No text detected)'}")
            print("-" * 50)
        return

    if args.query:
        results = db.search_text(args.query)
        print(f"\n=== Found {len(results)} matches for query '{args.query}' ===")
        for r in results:
            print(f"ID #{r['id']} | {r['timestamp']} | App: {r['app_name']}")
            print(f"   Image: {r['image_path']}")
            print(f"   Match: {r['extracted_text'][:120]}...")
            print("-" * 50)
        return

    app = ScreenTrackerApp(cfg)

    # Start Web Dashboard if requested
    web_server = None
    if args.web or args.web_only:
        web_server = WebDashboard(app_instance=app, port=args.web_port)
        web_server.start()

    if args.web_only:
        logger.info("Running in web-only mode. Navigate to http://localhost:%d (Ctrl+C to quit)", args.web_port)
        try:
            while _RUNNING:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            if web_server:
                web_server.stop()
        return

    try:
        if args.once:
            app.run_single_cycle()
        else:
            app.run_daemon()
    finally:
        if web_server:
            web_server.stop()


if __name__ == "__main__":
    main()
