from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class LoopHistoryStore:
    def __init__(self, data_dir: Path, *, limit: int) -> None:
        self._data_dir = data_dir
        self._history_path = data_dir / "controller-loop-history.json"
        self._limit = limit
        self._data_dir.mkdir(parents=True, exist_ok=True)

    def get_snapshot(self, *, scaler_key: str) -> dict[str, Any]:
        payload = self._read_payload()
        scaler_payload = payload.setdefault("scalers", {}).setdefault(
            scaler_key,
            {"podLoops": [], "nodeLoops": []},
        )
        return {
            "limit": self._limit,
            "podLoops": scaler_payload["podLoops"],
            "nodeLoops": scaler_payload["nodeLoops"],
        }

    def sync_latest(
        self,
        *,
        scaler_key: str,
        pod_loop: dict[str, Any] | None,
        node_loop: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload = self._read_payload()
        scaler_payload = payload.setdefault("scalers", {}).setdefault(
            scaler_key,
            {"podLoops": [], "nodeLoops": []},
        )
        changed = False

        if self._append_if_new(scaler_payload["podLoops"], pod_loop):
            changed = True
        if self._append_if_new(scaler_payload["nodeLoops"], node_loop):
            changed = True

        if changed:
            self._write_payload(payload)

        return {
            "limit": self._limit,
            "podLoops": scaler_payload["podLoops"],
            "nodeLoops": scaler_payload["nodeLoops"],
            "changed": changed,
        }

    def _append_if_new(
        self,
        items: list[dict[str, Any]],
        loop_record: dict[str, Any] | None,
    ) -> bool:
        if not loop_record:
            return False

        loop_key = str(loop_record.get("loopKey") or "").strip()
        if not loop_key:
            return False

        if items and items[-1].get("loopKey") == loop_key:
            return False

        minute_bucket = str(loop_record.get("minuteBucket") or "").strip()
        if items:
            last_minute_bucket = str(items[-1].get("minuteBucket") or "").strip()
            if minute_bucket and minute_bucket == last_minute_bucket:
                if items[-1] == loop_record:
                    return False
                items[-1] = loop_record
                return True

        items.append(loop_record)
        if len(items) > self._limit:
            del items[: len(items) - self._limit]
        return True

    def _read_payload(self) -> dict[str, Any]:
        if not self._history_path.exists():
            return {"scalers": {}}

        try:
            with self._history_path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError:
            return {"scalers": {}}

        scalers = payload.get("scalers")
        if not isinstance(scalers, dict):
            return {"scalers": {}}

        normalized_scalers: dict[str, dict[str, list[dict[str, Any]]]] = {}
        for scaler_key, scaler_payload in scalers.items():
            if not isinstance(scaler_payload, dict):
                continue
            pod_loops = scaler_payload.get("podLoops")
            node_loops = scaler_payload.get("nodeLoops")
            normalized_scalers[str(scaler_key)] = {
                "podLoops": pod_loops if isinstance(pod_loops, list) else [],
                "nodeLoops": node_loops if isinstance(node_loops, list) else [],
            }

        return {"scalers": normalized_scalers}

    def _write_payload(self, payload: dict[str, Any]) -> None:
        with self._history_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
