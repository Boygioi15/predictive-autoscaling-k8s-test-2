from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class LoadTestStore:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._script_path = data_dir / "script.json"
        self._metadata_path = data_dir / "metadata.json"
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def get_snapshot(self) -> dict[str, Any]:
        return {
            "script": self._read_json(self._script_path),
            "metadata": self._read_json(self._metadata_path),
        }

    def save_script(self, *, filename: str, content: str) -> dict[str, Any]:
        lines = content.splitlines()
        payload = {
            "filename": filename,
            "content": content,
            "uploadedAt": datetime.now(UTC).isoformat(),
            "lineCount": len(lines),
            "preview": lines[:12],
        }
        self._write_json(self._script_path, payload)
        return payload

    def save_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "uploadedAt": datetime.now(UTC).isoformat(),
            "payload": metadata,
        }
        self._write_json(self._metadata_path, payload)
        return payload

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
