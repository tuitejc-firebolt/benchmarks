import os
import time
import threading
import logging
import json
import pandas as pd
from pathlib import Path
import queue
import streamlit as st

from runner import BenchmarkRunner

# Configure Streamlit page
st.set_page_config(page_title="DB Benchmark Runner", layout="wide")

# Helper to reset session state
def reset_session():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# Initialize shared queue for results
if "seq_results_queue" not in st.session_state:
    st.session_state["seq_results_queue"] = queue.Queue()
if "seq_results" not in st.session_state:
    st.session_state["seq_results"] = []
if "seq_running" not in st.session_state:
    st.session_state["seq_running"] = False
if "seq_error" not in st.session_state:
    st.session_state["seq_error"] = None
if "warmup_status" not in st.session_state:
    st.session_state["warmup_status"] = None

# --- Sidebar UI ---
default_creds_path = str(Path(__file__).parent.parent.parent.parent / "config" / "credentials" / "credentials.json")
benchmark_name = st.sidebar.text_input("Benchmark Name", value="FireScale")
creds_file = st.sidebar.text_input("Credentials File", value=default_creds_path)
vendor_options = ["firebolt", "redshift", "snowflake", "google"]
vendors = st.sidebar.multiselect("Vendors", vendor_options, default=["firebolt"])
pool_size = st.sidebar.number_input("Query Set Runs", min_value=1, value=1, step=1)
concurrency = st.sidebar.number_input("Concurrent Queries", min_value=1, value=1, step=1)
seed = st.sidebar.number_input("Random Seed", min_value=1, value=1, step=1)
output_dir = st.sidebar.text_input("Output Directory", value="benchmark_results")
execute_setup = st.sidebar.checkbox("Execute Setup Before Benchmark", value=False)
run_warmup = st.sidebar.checkbox("Run Warmup Scripts", value=True)

# --- Benchmark Section ---
st.header("Benchmark")
run_seq = st.button("Run Benchmark", key="run_seq_btn")
seq_reset = st.button("Reset", on_click=reset_session, key="reset_seq_btn")  # Move reset button here
seq_progress = st.empty()
total_time_box = st.empty()  # New: for total run time KPI at the top
warmup_status_box = st.empty()
kpi_cols = st.columns(4)
seq_chart = st.empty()
concurrency_chart = st.empty()  # New: for concurrency per second chart
seq_table = st.empty()
seq_error = st.empty()

def run_worker(results_queue, vendors, benchmark_name, creds_file, pool_size, output_dir, benchmark_path, execute_setup, run_warmup, worker_id):
    try:
        runner = BenchmarkRunner(
            benchmark_name=benchmark_name,
            creds_file=creds_file,
            vendors=vendors,
            pool_size=pool_size,
            concurrency=1,
            output_dir=output_dir,
            benchmark_path=str(benchmark_path),
            execute_setup=execute_setup,
            results_queue=results_queue,
            run_warmup=run_warmup,
            warmup_status_callback=lambda msg: st.session_state.update({"warmup_status": msg}),
        )
        runner.run_benchmark()
        print(f"[run_worker] Worker {worker_id} finished.", flush=True)
    except Exception as e:
        print(f"[run_worker] Worker {worker_id} error: {e}", flush=True)
        results_queue.put({"vendor": "system", "query_name": f"worker_{worker_id}_error", "duration": 0, "rows": 0, "status": "error", "error": str(e), "timestamp": time.time(), "concurrent_run": worker_id})

if run_seq:
    st.session_state["seq_running"] = True
    st.session_state["seq_results"].clear()
    st.session_state["seq_error"] = None
    st.session_state["seq_results_queue"] = queue.Queue()
    st.session_state["seq_start_time"] = time.time()
    st.session_state["seq_end_time"] = None
    st.session_state["warmup_status"] = None

    benchmark_path = Path(__file__).parent.parent.parent.parent / 'benchmarks' / benchmark_name

    for i in range(concurrency):
        t = threading.Thread(
            target=run_worker,
            args=(
                st.session_state["seq_results_queue"],
                vendors,
                benchmark_name,
                creds_file,
                pool_size,
                output_dir,
                benchmark_path,
                execute_setup,
                run_warmup,
                i
            ),
            daemon=True
        )
        t.start()

# --- Warmup status UI ---
if st.session_state.get("warmup_status"):
    warmup_status_box.info(st.session_state["warmup_status"])
else:
    warmup_status_box.empty()

# --- Results and Progress ---
results_queue = st.session_state.get("seq_results_queue")
if results_queue:
    while not results_queue.empty():
        st.session_state["seq_results"].append(results_queue.get())

results = st.session_state.get("seq_results", [])
vendors = vendors  # already set from sidebar
total_queries = 25 * len(vendors) * pool_size * concurrency
completed_queries = len(results)
progress_pct = min(1.0, completed_queries / total_queries) if total_queries else 0

# End the loop as soon as all queries are done
if st.session_state.get("seq_running") and completed_queries >= total_queries:
    st.session_state["seq_running"] = False
    st.session_state["seq_end_time"] = time.time()
    st.session_state["warmup_status"] = None

seq_progress.progress(
    progress_pct,
    f"Running... {completed_queries}/{total_queries} queries"
    if st.session_state.get("seq_running")
    else "Benchmark complete."
)

# --- Total Run Time KPI at the top ---
if st.session_state.get("seq_start_time") and st.session_state.get("seq_end_time"):
    total_time = st.session_state["seq_end_time"] - st.session_state["seq_start_time"]
elif st.session_state.get("seq_start_time"):
    total_time = time.time() - st.session_state["seq_start_time"]
else:
    total_time = None

if total_time is not None:
    total_time_box.markdown(f"### Total Run Time: {total_time:.2f} seconds")
else:
    total_time_box.empty()

# --- KPIs and Charts ---
if results:
    df = pd.DataFrame(results)
    # --- Fix: Ensure query_name and query_text are always string for Arrow compatibility ---
    df["query_name"] = df["query_name"].astype(str)
    # Always use the actual SQL text from the 'query' field
    df["query_text"] = df["query"].astype(str) if "query" in df.columns else df["query_name"].astype(str)

    vendor_stats = df.groupby("vendor")["duration"].agg(["max", "min", "mean", "sum"]).reset_index()
    vendor_stats = vendor_stats.rename(columns={"mean": "avg", "sum": "total"})

    vendor_colors = {
        "firebolt": "#F72A30",
        "redshift": "#FF9900",
        "snowflake": "#29B5E8",
        "google": "#34A853"
    }

    def color_bar_chart(data, metric):
        import altair as alt
        data = data.copy()
        data["color"] = data["vendor"].map(vendor_colors).fillna("#888888")
        chart = (
            alt.Chart(data)
            .mark_bar()
            .encode(
                y=alt.Y("vendor:N", sort=None, title="Vendor"),
                x=alt.X(f"{metric}:Q", title=metric.capitalize()),
                color=alt.Color("vendor:N", scale=alt.Scale(domain=list(vendor_colors.keys()), range=list(vendor_colors.values())), legend=None),
                tooltip=["vendor", metric]
            )
            .properties(height=120)
        )
        return chart

    with kpi_cols[0]:
        st.markdown("**Max Response Time (s)**")
        st.altair_chart(color_bar_chart(vendor_stats, "max"), use_container_width=True)
    with kpi_cols[1]:
        st.markdown("**Min Response Time (s)**")
        st.altair_chart(color_bar_chart(vendor_stats, "min"), use_container_width=True)
    with kpi_cols[2]:
        st.markdown("**Avg Response Time (s)**")
        st.altair_chart(color_bar_chart(vendor_stats, "avg"), use_container_width=True)
    with kpi_cols[3]:
        st.markdown("**Total Time (s)**")
        st.altair_chart(color_bar_chart(vendor_stats, "total"), use_container_width=True)

    # --- Line chart: x = query_number (1-25), y = avg duration per query_name, per vendor ---
    st.markdown("#### Query Duration by Vendor")
    df["query_number"] = df.groupby("vendor")["query_name"].transform(lambda x: pd.factorize(x)[0] + 1)
    avg_df = df.groupby(["vendor", "query_number", "query_name"], as_index=False)["duration"].mean()
    import altair as alt
    line_chart = (
        alt.Chart(avg_df)
        .mark_line(point=True)
        .encode(
            x=alt.X("query_number:O", title="Query Number"),
            y=alt.Y("duration:Q", title="Avg Duration (s)"),
            color=alt.Color("vendor:N", scale=alt.Scale(domain=list(vendor_colors.keys()), range=list(vendor_colors.values())), legend=alt.Legend(title="Vendor")),
            tooltip=["vendor", "query_name", "duration", "query_number"]
        )
        .properties(height=300)
    )
    seq_chart.altair_chart(line_chart, use_container_width=True)

    # --- Concurrency per second chart ---
    if "timestamp" in df.columns:
        def parse_ts(ts):
            try:
                return pd.to_datetime(ts)
            except Exception:
                try:
                    return pd.to_datetime(float(ts), unit="s")
                except Exception:
                    return pd.NaT
        df["start_time"] = df["timestamp"].apply(parse_ts)
        min_time = df["start_time"].min()
        df = df[df["start_time"].notnull()]
        # Fix: Use relative seconds from min_time for x-axis
        df["elapsed_sec"] = ((df["start_time"] - min_time).dt.total_seconds()).astype(int)
        concurrency_df = df.groupby("elapsed_sec").size().reset_index(name="queries")
        concurrency_chart.altair_chart(
            alt.Chart(concurrency_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("elapsed_sec:Q", title="Second"),
                y=alt.Y("queries:Q", title="Queries Started"),
                tooltip=["elapsed_sec", "queries"]
            )
            .properties(height=200, title="Concurrency Per Second"),
            use_container_width=True
        )
    else:
        concurrency_chart.empty()

    # --- Table: show query text (truncated, with tooltip for full text), remove concurrent_run ---
    def truncate_query(q, length=60):
        return q if len(q) <= length else q[:length] + "..."

    df["query_text_trunc"] = df["query_text"].apply(truncate_query)
    # Ensure all columns are string/object for Arrow compatibility
    df["vendor"] = df["vendor"].astype(str)
    df["status"] = df["status"].astype(str)
    df["query_number"] = df["query_number"].astype("Int64")
    df["duration"] = pd.to_numeric(df["duration"], errors="coerce")
    df["rows"] = pd.to_numeric(df["rows"], errors="coerce")
    table_cols = ["vendor", "query_number", "duration", "rows", "status", "query_text_trunc"]
    table_display = df[table_cols].rename(columns={"query_text_trunc": "Query Text"})
    st.dataframe(table_display, use_container_width=True)

if st.session_state.get("seq_error"):
    seq_error.error(st.session_state["seq_error"])

if st.session_state.get("seq_running"):
    time.sleep(1)
    st.rerun()