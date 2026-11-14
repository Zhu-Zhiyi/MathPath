"""Check the classroom's integration into the real app, isolated from user data."""
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import lecture_provider
import lecture_store
import main
import desktop


class ClassroomEntryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="mathpath-classroom-entry-", ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        environment = patch.dict(os.environ, {"MATHPATH_DATA_DIR": directory.name})
        environment.start()
        self.addCleanup(environment.stop)
        for name in ("upload_video", "analyze_clip", "delete_remote"):
            guard = patch.object(lecture_provider, name, side_effect=AssertionError("No video requests allowed"))
            guard.start()
            self.addCleanup(guard.stop)
        self.client = TestClient(main.app, base_url="http://127.0.0.1:8123")
        self.addCleanup(self.client.close)

    def test_entry_and_assets_load_without_creating_or_sending_video(self):
        self.assertIn('id="classroom-button"', self.client.get("/").text)
        page = self.client.get("/classroom")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.headers["cache-control"], "no-store")
        for name in ("classroom.css", "classroom.js"):
            self.assertIn(name, page.text)
            self.assertEqual(self.client.get("/static/" + name).status_code, 200)
        self.assertEqual(self.client.get("/lectures").json(), [])
        self.assertFalse(lecture_store.data_root().exists())

    def test_foreign_origin_cannot_read_upload_start_or_delete_lectures(self):
        for method, path, headers in [
            ("GET", "/lectures", {"Origin": "https://foreign.example"}),
            ("POST", "/lectures?filename=lesson.mp4", {"Origin": "null"}),
            ("POST", "/lectures/unknown/analyze", {"Host": "foreign.example"}),
            ("DELETE", "/lectures/unknown", {"Origin": "https://foreign.example"}),
        ]:
            with self.subTest(method=method, path=path):
                result = self.client.request(method, path, headers=headers)
                self.assertEqual(result.status_code, 403)
        self.assertFalse(lecture_store.data_root().exists())

    def test_app_shutdown_cancels_video_workers(self):
        with patch.object(main, "shutdown_workers") as stop:
            with TestClient(main.app, base_url="http://127.0.0.1:8123") as client:
                self.assertEqual(client.get("/health").status_code, 200)
            stop.assert_called_once_with()

    def test_desktop_offline_checks_cannot_contact_video_provider(self):
        boundary = desktop.OfflineBoundary()
        boundary.install()
        try:
            with self.assertRaises(desktop.DesktopError):
                lecture_provider._request("POST", lecture_provider.BASE_URL, "synthetic-never-sent")
            self.assertEqual(boundary.counts["model_requests"], 1)
            self.assertEqual(boundary.counts["credential_reads"], 0)
        finally:
            boundary.restore()
