from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from app import content


class ContentLoadingTests(unittest.TestCase):
    def test_load_json_reads_files_as_utf8(self) -> None:
        with patch.object(Path, "exists", return_value=True), patch.object(
            Path,
            "read_text",
            autospec=True,
            return_value='{"ok": true}',
        ) as mock_read:
            data = content._load_json(Path("dummy.json"), {})

        self.assertEqual(data, {"ok": True})
        _, kwargs = mock_read.call_args
        self.assertEqual(kwargs.get("encoding"), "utf-8-sig")


if __name__ == "__main__":
    unittest.main()
