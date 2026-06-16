import argparse
import requests
import pandas as pd

PROM_URL = "http://localhost:9090"
STEP = "60s"

QUERIES = {
    # Request per minute captured by app
    "app_requests_per_minute": '''
        sum(
          rate(
            http_request_duration_seconds_count{
              service="prime-service"
            }[1m]
          )
        ) * 60
    ''',

    # Request per minute captured by ingress
    "ingress_requests_per_minute": '''
        sum(
          rate(
            nginx_ingress_controller_requests{
              ingress="ingress-backend"
            }[1m]
          )
        ) * 60
    ''',

    # Total CPU-seconds used by prime-service deployment in that minute
    "cpu_seconds_per_minute": '''
        sum(
          increase(
            container_cpu_usage_seconds_total{
              namespace="default",
              pod=~"prime-service-deployment-.*",
              container!="POD",
              container!=""
            }[1m]
          )
        )
    ''',

    # App p95 latency for that minute
    "app_p95_seconds": '''
        histogram_quantile(
          0.95,
          sum by (le) (
            rate(
              http_request_duration_seconds_bucket{
                service="prime-service"
              }[1m]
            )
          )
        )
    ''',

    # Ingress p95 latency for that minute
    "ingress_p95_seconds": '''
        histogram_quantile(
          0.95,
          sum by (le) (
            rate(
              nginx_ingress_controller_request_duration_seconds_bucket{
                ingress="ingress-backend"
              }[1m]
            )
          )
        )
    ''',
}
def parse_time(value: str) -> pd.Timestamp:
    ts = pd.to_datetime(value, utc=True)

    if pd.isna(ts):
        raise ValueError(f"Invalid datetime: {value}")

    return ts


def query_range(metric_name, promql, start, end):
    url = f"{PROM_URL}/api/v1/query_range"

    params = {
        "query": promql,
        "start": start.timestamp(),
        "end": end.timestamp(),
        "step": STEP,
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()

    data = response.json()

    if data["status"] != "success":
        raise RuntimeError(f"Prometheus query failed for {metric_name}: {data}")

    result = data["data"]["result"]

    if not result:
        print(f"Warning: no data for {metric_name}")
        return pd.DataFrame(columns=["timestamp", metric_name])

    rows = []

    for series in result:
        for ts, value in series["values"]:
            try:
                value = float(value)
            except ValueError:
                value = None

            rows.append({
                "timestamp": pd.to_datetime(float(ts), unit="s", utc=True),
                metric_name: value,
            })

    df_metric = pd.DataFrame(rows)

    if df_metric.empty:
        return pd.DataFrame(columns=["timestamp", metric_name])

    # Should already be one series because of sum(...), but this is safe
    df_metric = (
        df_metric
        .groupby("timestamp", as_index=False)[metric_name]
        .sum()
        .sort_values("timestamp")
    )

    return df_metric

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("output_file", help="Output CSV file path")

    parser.add_argument(
        "start_time",
        help="Experiment start time, example: 2026-06-12T17:00:00+07:00",
    )

    parser.add_argument(
        "end_time",
        help="Experiment end time, example: 2026-06-12T19:00:00+07:00",
    )

    parser.add_argument(
        "wc_1998_start_time",
        help="Start timestamp of selected World Cup 1998 range, example: 1998-04-30T21:30:17+00:00",
    )

    args = parser.parse_args()
    output_file = args.output_file
    start = parse_time(args.start_time)
    end = parse_time(args.end_time)
    wc_1998_start = parse_time(args.wc_1998_start_time)

    if end <= start:
        raise ValueError("end_time must be after start_time")

    merged_df = None

    for metric_name, promql in QUERIES.items():
        print(f"Querying {metric_name}...")

        metric_df = query_range(
            metric_name=metric_name,
            promql=promql,
            start=start,
            end=end,
        )

        if merged_df is None:
            merged_df = metric_df
        else:
            merged_df = pd.merge(
                merged_df,
                metric_df,
                on="timestamp",
                how="outer",
            )

    merged_df = merged_df.sort_values("timestamp").reset_index(drop=True)

    elapsed_seconds = (merged_df["timestamp"] - start).dt.total_seconds()

    merged_df["relative_minute"] = elapsed_seconds.div(60).astype(int)

    merged_df["wc_1998_timestamp"] = (
        wc_1998_start + pd.to_timedelta(merged_df["relative_minute"], unit="m")
    )

    # Optional derived RPS
    merged_df["app_rps"] = merged_df["app_requests_per_minute"] / 60
    merged_df["ingress_rps"] = merged_df["ingress_requests_per_minute"] / 60

    merged_df = merged_df[
        [
            "timestamp",
            "wc_1998_timestamp",
            "app_requests_per_minute",
            "ingress_requests_per_minute",
            "cpu_seconds_per_minute",
            "app_p95_seconds",
            "ingress_p95_seconds",
            "app_rps",
            "ingress_rps",
        ]
    ]

    merged_df.to_csv(output_file, index=False)

    merged_df.head()

if __name__ == "__main__":
    main()
