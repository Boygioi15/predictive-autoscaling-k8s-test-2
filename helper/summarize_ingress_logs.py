#!/usr/bin/env python3

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize ingress-nginx JSON access logs into per-second request counts."
    )
    parser.add_argument(
        "--input",
        default="-",
        help="Input file path, or - to read from stdin.",
    )
    parser.add_argument(
        "--output",
        default="shares/ingress_request_report.csv",
        help="Output CSV path.",
    )
    parser.add_argument(
        "--ingress",
        default="ingress-backend",
        help="Only count requests for this ingress name.",
    )
    parser.add_argument(
        "--stream",
        action="store_true",
        help="Read a live stream and append closed seconds as they complete.",
    )
    return parser.parse_args()


def _open_input(input_path: str):
    if input_path == "-":
        return sys.stdin
    return open(input_path, encoding="utf-8")


def _extract_json_payload(raw_line: str) -> str | None:
    line = raw_line.strip()
    if not line:
        return None

    json_start = line.find("{")
    if json_start < 0:
        return None

    return line[json_start:]


def _second_bucket(value: str) -> str:
    timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return timestamp.replace(microsecond=0).isoformat()


def _write_header(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["second", "count"])


def _append_rows(output_path: Path, rows: list[tuple[str, int]]) -> None:
    if not rows:
        return
    with output_path.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        for second, count in rows:
            writer.writerow([second, count])


def _matches_ingress(payload: dict, ingress_name: str) -> bool:
    payload_ingress = payload.get("ingress")
    if payload_ingress is None:
        return True
    return payload_ingress == ingress_name


def _stream_counts(input_handle, output_path: Path, ingress_name: str) -> None:
    pending_counts: dict[str, int] = defaultdict(int)
    latest_second = None

    _write_header(output_path)

    for raw_line in input_handle:
        line = _extract_json_payload(raw_line)
        if line is None:
            continue

        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue

        if not _matches_ingress(payload, ingress_name):
            continue

        request_time = payload.get("time")
        if not request_time:
            continue

        second_bucket = _second_bucket(request_time)
        pending_counts[second_bucket] += 1

        if latest_second is None or second_bucket > latest_second:
            latest_second = second_bucket
            closed_rows = [
                (second, pending_counts.pop(second))
                for second in sorted(list(pending_counts.keys()))
                if second < latest_second
            ]
            _append_rows(output_path, closed_rows)

    remaining_rows = [(second, pending_counts[second]) for second in sorted(pending_counts)]
    _append_rows(output_path, remaining_rows)


def main() -> int:
    args = _parse_args()
    output_path = Path(args.output)

    input_handle = _open_input(args.input)
    try:
        if args.stream:
            _stream_counts(input_handle, output_path, args.ingress)
            return 0

        counts: dict[str, int] = defaultdict(int)
        for raw_line in input_handle:
            line = _extract_json_payload(raw_line)
            if line is None:
                continue

            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue

            if not _matches_ingress(payload, args.ingress):
                continue

            request_time = payload.get("time")
            if not request_time:
                continue

            counts[_second_bucket(request_time)] += 1
    finally:
        if input_handle is not sys.stdin:
            input_handle.close()

    _write_header(output_path)
    _append_rows(output_path, sorted(counts.items()))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
