from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = REPO_ROOT / "data" / "logs.jsonl"
DASHBOARD_CONFIG_PATH = REPO_ROOT / "config" / "dashboard.yaml"

st.set_page_config(page_title="Day 13 AI Observability", layout="wide")


def load_config() -> dict:
    return yaml.safe_load(DASHBOARD_CONFIG_PATH.read_text(encoding="utf-8"))["dashboard"]


def load_records() -> pd.DataFrame:
    if not LOG_PATH.exists():
        return pd.DataFrame()
    rows = []
    for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    df = pd.DataFrame(rows)
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], errors="coerce")
    return df


def threshold_line(value: float, threshold: dict, unit: str) -> str:
    op = threshold["operator"]
    limit = threshold["value"]
    ok = value <= limit if op == "lte" else value >= limit
    symbol = "<=" if op == "lte" else ">="
    badge = "OK" if ok else "BREACH"
    return f"Threshold: {symbol} {limit} {unit} — {badge}"


config = load_config()
df = load_records()

st.title(config["title"])
st.caption(
    f"Time range: last {config['time_range_minutes']} min | "
    f"Refresh: {config['refresh_seconds']}s | Source: data/logs.jsonl"
)

if df.empty:
    st.warning("Chưa có data/logs.jsonl. Chạy API + scripts/load_test.py trước.")
    st.stop()

now = df["ts"].max()
window_start = now - pd.Timedelta(minutes=config["time_range_minutes"])
window = df[df["ts"] >= window_start]

panels = {p["id"]: p for p in config["panels"]}
responses = window[window["event"] == "response_sent"]
requests_ = window[window["event"] == "request_received"]
failures = window[window["event"] == "request_failed"]

col1, col2, col3 = st.columns(3)

with col1:
    p = panels["latency"]
    st.subheader(p["title"])
    if not responses.empty:
        p50, p95, p99 = responses["latency_ms"].quantile([0.5, 0.95, 0.99])
        st.metric(f"P95 ({p['unit']})", f"{p95:.0f}")
        st.write(f"P50={p50:.0f} | P95={p95:.0f} | P99={p99:.0f} {p['unit']}")
        st.write(threshold_line(p95, p["threshold"], p["unit"]))
        st.line_chart(responses.set_index("ts")["latency_ms"])
    else:
        st.info("Chưa có response_sent trong window.")

with col2:
    p = panels["traffic"]
    st.subheader(p["title"])
    count = len(requests_)
    rate = count / max(config["time_range_minutes"], 1)
    st.metric(f"Rate ({p['unit']})", f"{rate:.2f}")
    st.write(f"Total requests: {count}")
    st.write(threshold_line(rate, p["threshold"], p["unit"]))
    if not requests_.empty:
        st.bar_chart(requests_.set_index("ts").resample("1min").size())

with col3:
    p = panels["errors"]
    st.subheader(p["title"])
    total_req = len(requests_)
    total_fail = len(failures)
    error_rate = (total_fail / total_req * 100) if total_req else 0.0
    st.metric(f"Error rate ({p['unit']})", f"{error_rate:.2f}")
    st.write(threshold_line(error_rate, p["threshold"], p["unit"]))
    if not failures.empty:
        st.bar_chart(failures["error_type"].value_counts())
    else:
        st.write("Không có lỗi trong window.")

col4, col5, col6 = st.columns(3)

with col4:
    p = panels["cost"]
    st.subheader(p["title"])
    if not responses.empty:
        total_cost = responses["cost_usd"].sum()
        st.metric(f"Total cost ({p['unit']})", f"{total_cost:.4f}")
        st.write(threshold_line(total_cost, p["threshold"], p["unit"]))
        st.line_chart(responses.set_index("ts").resample("1min")["cost_usd"].sum())
    else:
        st.info("Chưa có dữ liệu cost.")

with col5:
    p = panels["tokens"]
    st.subheader(p["title"])
    if not responses.empty:
        tokens_in = responses["tokens_in"].sum()
        tokens_out = responses["tokens_out"].sum()
        total_tokens = tokens_in + tokens_out
        st.metric(f"Total tokens ({p['unit']})", f"{total_tokens:.0f}")
        st.write(f"in={tokens_in:.0f} | out={tokens_out:.0f}")
        st.write(threshold_line(total_tokens, p["threshold"], p["unit"]))
        st.bar_chart(pd.DataFrame({"tokens_in": [tokens_in], "tokens_out": [tokens_out]}))
    else:
        st.info("Chưa có dữ liệu tokens.")

with col6:
    p = panels["quality"]
    st.subheader(p["title"])
    if not responses.empty:
        mean_quality = responses["quality_score"].mean()
        st.metric(f"Quality mean ({p['unit']})", f"{mean_quality:.2f}")
        st.write(threshold_line(mean_quality, p["threshold"], p["unit"]))
        st.line_chart(responses.set_index("ts")["quality_score"])
    else:
        st.info("Chưa có dữ liệu quality.")
