#!/usr/bin/env python3

import argparse
import bisect
import math
import random
import statistics
from pathlib import Path

import pandas as pd


SEED_REQUIRED_COLUMNS = [
    "app_requests_per_minute",
    "ingress_requests_per_minute",
    "cpu_seconds_per_minute",
    "app_p95_seconds",
    "ingress_p95_seconds",
]

DEFAULT_PREDICTOR_COLUMN = "ingress_requests_per_minute"
CPU_NOISE_ABS_MAX = 10.0
P95_NOISE_ABS_MAX = 0.1


def parse_time(value: str) -> pd.Timestamp:
    timestamp = pd.to_datetime(value, utc=True)
    if pd.isna(timestamp):
        raise ValueError(f"Invalid datetime: {value}")
    return timestamp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a minute-level synthetic workload dataset by selecting a "
            "World Cup 1998 request window and seeding extra metrics from an "
            "observed Prometheus export CSV."
        )
    )
    parser.add_argument(
        "seed_csv",
        help=(
            "Observed minute-level seed CSV exported from Prometheus, for example "
            "helper/prime_service_metrics.csv"
        ),
    )
    parser.add_argument(
        "wc_csv",
        help=(
            "World Cup 1998 second-level request trace CSV with columns like "
            "datetime,requests"
        ),
    )
    parser.add_argument(
        "output_csv",
        help="Output CSV file path for the generated synthetic dataset",
    )
    parser.add_argument(
        "--wc-start-time",
        required=True,
        help=(
            "Start timestamp inside the WC1998 trace, for example "
            "1998-06-10T14:00:00+00:00"
        ),
    )
    parser.add_argument(
        "--wc-end-time",
        help="Exclusive end timestamp inside the WC1998 trace",
    )
    parser.add_argument(
        "--duration-minutes",
        type=int,
        help=(
            "Duration of the selected WC1998 window in minutes. If omitted and "
            "--wc-end-time is also omitted, the seed duration is used."
        ),
    )
    parser.add_argument(
        "--guardrail-k",
        type=int,
        default=5,
        help=(
            "Number of nearest seed minutes by predictor value to use when "
            "transferring p95 metrics."
        ),
    )
    parser.add_argument(
        "--include-provenance",
        action="store_true",
        help="Append seed matching columns for debugging and thesis traceability.",
    )
    parser.add_argument(
        "--random-seed",
        type=int,
        help="Optional seed for reproducible random noise in generated metrics.",
    )
    return parser.parse_args()


def load_seed(seed_path: str) -> pd.DataFrame:
    seed_df = pd.read_csv(seed_path)

    if "timestamp" in seed_df.columns:
        seed_df["timestamp"] = pd.to_datetime(seed_df["timestamp"], utc=True, errors="coerce")
    if "wc_1998_timestamp" in seed_df.columns:
        seed_df["wc_1998_timestamp"] = pd.to_datetime(
            seed_df["wc_1998_timestamp"], utc=True, errors="coerce"
        )

    missing_columns = [column for column in SEED_REQUIRED_COLUMNS if column not in seed_df.columns]
    if missing_columns:
        raise ValueError(
            f"Seed CSV is missing required columns: {', '.join(missing_columns)}"
        )

    numeric_columns = list(SEED_REQUIRED_COLUMNS)
    numeric_columns.extend(["app_rps", "ingress_rps"])
    if "relative_minute" in seed_df.columns:
        numeric_columns.append("relative_minute")

    for column in numeric_columns:
        if column in seed_df.columns:
            seed_df[column] = pd.to_numeric(seed_df[column], errors="coerce")

    seed_df = seed_df.dropna(subset=[DEFAULT_PREDICTOR_COLUMN]).copy()
    if seed_df.empty:
        raise ValueError(
            f"Seed CSV does not contain any valid {DEFAULT_PREDICTOR_COLUMN} rows"
        )

    return seed_df


def load_wc_minute_trace(wc_path: str) -> pd.DataFrame:
    wc_df = pd.read_csv(wc_path)
    if "datetime" not in wc_df.columns or "requests" not in wc_df.columns:
        raise ValueError("WC CSV must contain datetime and requests columns")

    wc_df["datetime"] = pd.to_datetime(wc_df["datetime"], utc=True, errors="coerce")
    wc_df["requests"] = pd.to_numeric(wc_df["requests"], errors="coerce")
    wc_df = wc_df.dropna(subset=["datetime", "requests"]).copy()
    if wc_df.empty:
        raise ValueError("WC CSV does not contain any valid datetime/requests rows")

    wc_df["wc_1998_timestamp"] = wc_df["datetime"].dt.floor("min")
    minute_df = (
        wc_df.groupby("wc_1998_timestamp", as_index=False)["requests"]
        .sum()
        .rename(columns={"requests": "ingress_requests_per_minute"})
        .sort_values("wc_1998_timestamp")
        .reset_index(drop=True)
    )
    minute_df["ingress_rps"] = minute_df["ingress_requests_per_minute"] / 60.0
    return minute_df


def resolve_wc_range(
    minute_df: pd.DataFrame,
    seed_df: pd.DataFrame,
    wc_start_time: str,
    wc_end_time: str | None,
    duration_minutes: int | None,
) -> pd.DataFrame:
    start_time = parse_time(wc_start_time).floor("min")

    if wc_end_time and duration_minutes:
        raise ValueError("Use either --wc-end-time or --duration-minutes, not both")

    if wc_end_time:
        end_time = parse_time(wc_end_time).floor("min")
    elif duration_minutes:
        if duration_minutes <= 0:
            raise ValueError("--duration-minutes must be positive")
        end_time = start_time + pd.Timedelta(minutes=duration_minutes)
    else:
        inferred_minutes = (
            int(seed_df["relative_minute"].max()) + 1
            if "relative_minute" in seed_df.columns
            else len(seed_df)
        )
        end_time = start_time + pd.Timedelta(minutes=inferred_minutes)

    if end_time <= start_time:
        raise ValueError("Selected WC range must end after it starts")

    selected = minute_df[
        (minute_df["wc_1998_timestamp"] >= start_time)
        & (minute_df["wc_1998_timestamp"] < end_time)
    ].copy()
    if selected.empty:
        raise ValueError("Selected WC range did not produce any minute-level rows")

    selected = selected.sort_values("wc_1998_timestamp").reset_index(drop=True)
    selected["relative_minute"] = (
        (selected["wc_1998_timestamp"] - selected["wc_1998_timestamp"].iloc[0])
        .dt.total_seconds()
        .div(60)
        .astype(int)
    )
    selected["timestamp"] = selected["wc_1998_timestamp"]
    return selected


def fit_linear_model(x_values: list[float], y_values: list[float]) -> tuple[float, float] | None:
    if len(x_values) != len(y_values) or len(x_values) == 0:
        return None

    if len(x_values) == 1:
        return 0.0, y_values[0]

    mean_x = statistics.fmean(x_values)
    mean_y = statistics.fmean(y_values)
    denominator = sum((x - mean_x) ** 2 for x in x_values)
    if math.isclose(denominator, 0.0):
        return 0.0, mean_y

    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values))
    slope = numerator / denominator
    intercept = mean_y - slope * mean_x
    return slope, intercept


def predict_linear(model: tuple[float, float] | None, x_value: float) -> float | None:
    if model is None:
        return None
    slope, intercept = model
    return max(0.0, slope * x_value + intercept)


def nearest_seed_indices(sorted_values: list[float], target_value: float, k: int) -> list[int]:
    if not sorted_values:
        return []

    k = max(1, min(k, len(sorted_values)))
    right = bisect.bisect_left(sorted_values, target_value)
    left = right - 1
    indices: list[int] = []

    while len(indices) < k and (left >= 0 or right < len(sorted_values)):
        choose_left = False
        if left >= 0 and right < len(sorted_values):
            left_distance = abs(sorted_values[left] - target_value)
            right_distance = abs(sorted_values[right] - target_value)
            choose_left = left_distance <= right_distance
        elif left >= 0:
            choose_left = True

        if choose_left:
            indices.append(left)
            left -= 1
        else:
            indices.append(right)
            right += 1

    return indices


def median_from_series(values: pd.Series) -> float | None:
    valid = [value for value in values.tolist() if pd.notna(value)]
    if not valid:
        return None
    return float(statistics.median(valid))


def add_bounded_noise(
    value: float | None,
    max_abs_noise: float,
    rng: random.Random,
) -> float | None:
    if value is None or pd.isna(value):
        return value
    return max(0.0, float(value) + rng.uniform(-max_abs_noise, max_abs_noise))


def build_synthetic_dataset(
    seed_df: pd.DataFrame,
    wc_selected_df: pd.DataFrame,
    guardrail_k: int,
    include_provenance: bool,
    rng: random.Random,
) -> pd.DataFrame:
    predictor_column = DEFAULT_PREDICTOR_COLUMN
    sorted_seed = seed_df.sort_values(predictor_column).reset_index(drop=True)
    sorted_predictor = sorted_seed[predictor_column].tolist()

    app_request_model = fit_linear_model(
        sorted_seed[predictor_column].tolist(),
        sorted_seed["app_requests_per_minute"].tolist(),
    )
    cpu_model = fit_linear_model(
        sorted_seed[predictor_column].tolist(),
        sorted_seed["cpu_seconds_per_minute"].tolist(),
    )

    output_df = wc_selected_df.copy()

    predictor_values = output_df["ingress_requests_per_minute"].tolist()

    app_requests_per_minute: list[float | None] = []
    cpu_seconds_per_minute: list[float | None] = []
    app_p95_seconds: list[float | None] = []
    ingress_p95_seconds: list[float | None] = []
    provenance_seed_predictor: list[float | None] = []
    provenance_seed_relative_minute: list[int | None] = []

    for predictor_value in predictor_values:
        indices = nearest_seed_indices(sorted_predictor, float(predictor_value), guardrail_k)
        matched_seed = sorted_seed.iloc[indices]
        nearest_seed_row = matched_seed.iloc[0]

        provenance_seed_predictor.append(float(nearest_seed_row[predictor_column]))
        provenance_seed_relative_minute.append(
            int(nearest_seed_row["relative_minute"])
            if "relative_minute" in nearest_seed_row and pd.notna(nearest_seed_row["relative_minute"])
            else None
        )

        predicted_app_rpm = predict_linear(app_request_model, float(predictor_value))
        if predicted_app_rpm is None:
            predicted_app_rpm = median_from_series(matched_seed["app_requests_per_minute"])
        app_requests_per_minute.append(predicted_app_rpm)

        predicted_cpu = predict_linear(cpu_model, float(predictor_value))
        if predicted_cpu is None:
            predicted_cpu = median_from_series(matched_seed["cpu_seconds_per_minute"])
        cpu_seconds_per_minute.append(
            add_bounded_noise(predicted_cpu, CPU_NOISE_ABS_MAX, rng)
        )

        app_p95_seconds.append(
            add_bounded_noise(
                median_from_series(matched_seed["app_p95_seconds"]),
                P95_NOISE_ABS_MAX,
                rng,
            )
        )
        ingress_p95_seconds.append(
            add_bounded_noise(
                median_from_series(matched_seed["ingress_p95_seconds"]),
                P95_NOISE_ABS_MAX,
                rng,
            )
        )

    output_df["app_requests_per_minute"] = app_requests_per_minute
    output_df["cpu_seconds_per_minute"] = cpu_seconds_per_minute
    output_df["app_p95_seconds"] = app_p95_seconds
    output_df["ingress_p95_seconds"] = ingress_p95_seconds
    output_df["app_rps"] = output_df["app_requests_per_minute"] / 60.0

    ordered_columns = [
        "wc_1998_timestamp",
        "app_requests_per_minute",
        "ingress_requests_per_minute",
        "cpu_seconds_per_minute",
        "app_p95_seconds",
        "ingress_p95_seconds",
        "app_rps",
        "ingress_rps",
    ]

    if include_provenance:
        output_df["seed_match_predictor"] = provenance_seed_predictor
        output_df["seed_match_relative_minute"] = pd.array(
            provenance_seed_relative_minute, dtype="Int64"
        )
        ordered_columns.extend(["seed_match_predictor", "seed_match_relative_minute"])

    return output_df[ordered_columns]


def main() -> int:
    args = parse_args()
    rng = random.Random(args.random_seed)

    seed_df = load_seed(args.seed_csv)
    wc_minute_df = load_wc_minute_trace(args.wc_csv)
    wc_selected_df = resolve_wc_range(
        minute_df=wc_minute_df,
        seed_df=seed_df,
        wc_start_time=args.wc_start_time,
        wc_end_time=args.wc_end_time,
        duration_minutes=args.duration_minutes,
    )

    output_df = build_synthetic_dataset(
        seed_df=seed_df,
        wc_selected_df=wc_selected_df,
        guardrail_k=args.guardrail_k,
        include_provenance=args.include_provenance,
        rng=rng,
    )

    seed_min = float(seed_df[DEFAULT_PREDICTOR_COLUMN].min())
    seed_max = float(seed_df[DEFAULT_PREDICTOR_COLUMN].max())
    target_min = float(output_df["ingress_requests_per_minute"].min())
    target_max = float(output_df["ingress_requests_per_minute"].max())

    if target_min < seed_min or target_max > seed_max:
        print(
            "Warning: selected WC range extends outside the observed seed predictor range.\n"
            f"  seed_range=[{seed_min:.3f}, {seed_max:.3f}]\n"
            f"  target_range=[{target_min:.3f}, {target_max:.3f}]"
        )

    output_path = Path(args.output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_df.to_csv(output_path, index=False)

    print(f"Saved synthetic workload to {output_path}")
    print(output_df.head())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
