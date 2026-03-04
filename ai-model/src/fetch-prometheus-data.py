import requests
import pandas as pd
from datetime import datetime
import os 

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://127.0.0.1:9090")

QUERY = '''
sum(
  rate(container_cpu_usage_seconds_total{
    namespace="default",
    pod=~"product-.*"
  }[1m])
)
'''

START = "2026-02-01T00:00:00Z"
END   = "2026-02-01T06:00:00Z"
STEP  = "5s"   # resolution

def fetch_prometheus_range(query, start, end, step):
    url = f"{PROMETHEUS_URL}/api/v1/query_range"
    params = {
        "query": query,
        "start": start,
        "end": end,
        "step": step
    }
    resp = requests.get(url, params=params)
    resp.raise_for_status()
    return resp.json()["data"]["result"]

def to_dataframe(result):
    print(result)
    values = result[0]["values"]  # [[timestamp, value], ...]
    df = pd.DataFrame(values, columns=["timestamp", "value"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
    df["value"] = df["value"].astype(float)
    return df

if __name__ == "__main__":
    result = fetch_prometheus_range(QUERY, START, END, STEP)
    df = to_dataframe(result)

    df.to_csv("data/raw/cpu_usage.csv", index=False)
    print("Saved data/raw/cpu_usage.csv")
