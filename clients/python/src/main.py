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
import connectors

# Configure Streamlit page
st.set_page_config(page_title="Firebolt Benchmarking Tool", layout="wide")

# App Title
st.title("🔥 Firebolt Benchmarking Tool")

# Helper to reset session state
def reset_session():
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()

# Helper to calculate estimated hourly costs
def calculate_hourly_cost(vendor, cluster_info):
    """Calculate estimated hourly cost based on cluster configuration."""
    try:
        if vendor == "firebolt":
            # Firebolt pricing: 16 FBU per hour = $5.60 per hour (based on $0.35 per FBU)
            fbu_rate = cluster_info.get('fbu_rate', '0')
            if fbu_rate and fbu_rate != 'Unknown':
                # Convert Decimal string to float 
                fbu_rate_num = float(str(fbu_rate).replace('Decimal(', '').replace(')', '').replace("'", ''))
                # Firebolt pricing: $0.35 per FBU, so multiply FBU rate by $0.35
                return fbu_rate_num * 0.35
            return 0.0
            
        elif vendor == "snowflake":
            # Snowflake pricing by warehouse size (Standard Edition)
            size = cluster_info.get('size', '').upper()
            min_clusters = cluster_info.get('min_cluster_count', 1)
            max_clusters = cluster_info.get('max_cluster_count', 1)
            avg_clusters = (int(min_clusters) + int(max_clusters)) / 2 if str(min_clusters).isdigit() and str(max_clusters).isdigit() else 1
            
            # Snowflake Standard Edition pricing: $2.00 per credit per hour
            credit_cost = 3.0  # $3 per credit per hour (enterprise edition, US East)
            size_credits = {
                'X-SMALL': 1, 'SMALL': 2, 'MEDIUM': 4, 'LARGE': 8, 
                'X-LARGE': 16, '2X-LARGE': 32, '3X-LARGE': 64, '4X-LARGE': 128,
                '5X-LARGE': 256, '6X-LARGE': 512
            }
            credits_per_hour = size_credits.get(size, 1)
            return credits_per_hour * credit_cost * avg_clusters
            
        elif vendor == "redshift":
            # Redshift pricing based on node type and count
            nodes = cluster_info.get('nodes', [])
            total_cost = 0.0
            
            # If we have actual node information with real node types
            actual_node_found = False
            for node in nodes:
                node_type = node.get('node_type', '')
                node_count = node.get('node_count', 0)
                
                # Redshift pricing (estimated, varies by region)
                node_prices = {
                    'dc2.large': 0.25,      # $0.25/hour
                    'dc2.8xlarge': 4.80,    # $4.80/hour  
                    'ds2.xlarge': 0.85,     # $0.85/hour
                    'ds2.8xlarge': 6.80,    # $6.80/hour
                    'ra3.xlplus': 3.26,     # $3.26/hour
                    'ra3.4xlarge': 13.04,   # $13.04/hour
                    'ra3.16xlarge': 52.16   # $52.16/hour
                }
                
                if node_type in node_prices:
                    actual_node_found = True
                    hourly_cost = node_prices[node_type]
                    total_cost += hourly_cost * int(node_count) if str(node_count).isdigit() else hourly_cost
            
            # If no actual node types found, estimate based on cluster name/size
            if not actual_node_found:
                host = cluster_info.get('host', '')
                
                # Based on the known cluster: ra3.xlplus | 3 nodes | 91.6 TB
                if 'firenewt-cluster' in host.lower():
                    return 3.26 * 3  # 3x ra3.xlplus nodes at $3.26/hour each = $9.78/hour
                
                # Fallback estimates for other clusters
                elif 'large' in host.lower():
                    return 13.04  # Assume ra3.4xlarge for large clusters
                elif 'xlarge' in host.lower() or 'xl' in host.lower():
                    return 52.16  # Assume ra3.16xlarge for xlarge clusters
                elif 'medium' in host.lower():
                    return 6.80   # Assume ds2.8xlarge for medium clusters
                else:
                    # Default estimate for typical production Redshift cluster
                    # Most production clusters use ra3.4xlarge (2-4 nodes)
                    return 26.08  # Assume 2x ra3.4xlarge nodes ($13.04 each)
                
            return total_cost
            
        elif vendor == "google":
            # BigQuery pricing - slot-based pricing
            # BigQuery on-demand is $5 per TB processed, but for dedicated slots:
            # Standard slots are ~$0.04 per slot per hour
            # Assume 500 slots for typical workload
            return 500 * 0.04  # $20/hour for 500 slots
            
        return 0.0
        
    except Exception as e:
        print(f"Error calculating cost for {vendor}: {e}")
        return 0.0

# Helper to get cluster information
@st.cache_data(ttl=300, show_spinner=False)  # Cache for 5 minutes, no spinner to avoid duplication
def get_cluster_information(vendor, creds_file, debug_mode=False):
    """Get cluster information for a specific vendor."""
    try:
        # Set up logging if debug mode is enabled
        if debug_mode:
            logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            logger = logging.getLogger(__name__)
            logger.debug(f"Getting cluster info for {vendor}")
        
        # Load credentials
        with open(creds_file, 'r') as f:
            credentials = json.load(f)
        
        if vendor not in credentials:
            return {"error": f"No credentials found for {vendor}"}
        
        if debug_mode:
            logger.debug(f"Credentials loaded for {vendor}")
        
        # Get the connector class and create instance
        connector_class = connectors.get_connector_class(vendor)
        connector = connector_class(config=credentials[vendor])
        
        if debug_mode:
            logger.debug(f"Connector created for {vendor}")
        
        # Get cluster info
        cluster_info = connector.get_cluster_info()
        
        if debug_mode:
            logger.debug(f"Cluster info retrieved: {cluster_info}")
        
        # Clean up
        connector.close()
        
        return cluster_info
    except Exception as e:
        error_msg = f"Failed to get cluster info: {str(e)}"
        if debug_mode:
            import traceback
            error_msg += f"\nTraceback: {traceback.format_exc()}"
        return {"error": error_msg}

# Helper to test Firebolt queries for debugging
def test_firebolt_queries(creds_file):
    """Test various Firebolt queries to see what information is available."""
    try:
        with open(creds_file, 'r') as f:
            credentials = json.load(f)
        
        if "firebolt" not in credentials:
            return {"error": "No Firebolt credentials found"}
        
        connector_class = connectors.get_connector_class("firebolt")
        connector = connector_class(config=credentials["firebolt"])
        
        test_results = {}
        
        # Test various queries
        test_queries = [
            ("SHOW ENGINES", "show_engines"),
            ("SELECT * FROM information_schema.engines LIMIT 5", "info_schema_engines"),
            ("SELECT * FROM information_schema.schemata LIMIT 5", "info_schema_schemata"),
            ("SELECT engine_name FROM information_schema.engines", "engine_names_only"),
            ("SHOW DATABASES", "show_databases"),
        ]
        
        for query, label in test_queries:
            try:
                result = connector.execute_query(query)
                test_results[label] = {
                    "query": query,
                    "success": True,
                    "result": result[:3] if result else [],  # Only show first 3 rows
                    "row_count": len(result) if result else 0
                }
            except Exception as e:
                test_results[label] = {
                    "query": query,
                    "success": False,
                    "error": str(e)
                }
        
        connector.close()
        return test_results
        
    except Exception as e:
        return {"error": f"Failed to test queries: {str(e)}"}

# Helper to check table row counts in Firebolt
def check_table_counts(creds_file):
    """Check if all required tables exist and have data in Firebolt."""
    try:
        with open(creds_file, 'r') as f:
            credentials = json.load(f)
        
        if "firebolt" not in credentials:
            return {"error": "No Firebolt credentials found"}
        
        connector_class = connectors.get_connector_class("firebolt")
        connector = connector_class(config=credentials["firebolt"])
        
        table_results = {}
        
        # Check all required tables
        tables_to_check = ["uservisits", "rankings", "agents", "searchwords", "ipaddresses"]
        
        for table in tables_to_check:
            try:
                # Check if table exists and get row count
                count_query = f"SELECT COUNT(*) as row_count FROM {table}"
                result = connector.execute_query(count_query)
                row_count = result[0]['row_count'] if result else 0
                
                # Get sample data
                sample_query = f"SELECT * FROM {table} LIMIT 3"
                sample_result = connector.execute_query(sample_query)
                
                table_results[table] = {
                    "exists": True,
                    "row_count": row_count,
                    "sample_data": sample_result
                }
            except Exception as e:
                table_results[table] = {
                    "exists": False,
                    "error": str(e),
                    "row_count": 0
                }
        
        connector.close()
        return table_results
        
    except Exception as e:
        return {"error": f"Failed to check tables: {str(e)}"}

# Helper to test Redshift system tables access
def test_redshift_system_tables(creds_file):
    """Test access to various Redshift system tables to debug permissions."""
    try:
        with open(creds_file, 'r') as f:
            credentials = json.load(f)
        
        if "redshift" not in credentials:
            return {"error": "No Redshift credentials found"}
        
        connector_class = connectors.get_connector_class("redshift")
        connector = connector_class(config=credentials["redshift"])
        
        test_results = {}
        
        # Test various system queries - each in isolation to avoid transaction issues
        system_queries = [
            ("SELECT version()", "version"),
            ("SELECT current_user", "current_user"),
            ("SELECT current_database()", "current_database"),
            ("SELECT COUNT(*) FROM svv_compute_node_info", "svv_compute_node_info_count"),
            ("SELECT * FROM svv_compute_node_info LIMIT 3", "svv_compute_node_info_sample"),
            ("SELECT * FROM pg_settings WHERE name LIKE '%cluster%' OR name LIKE '%node%' LIMIT 5", "pg_settings_cluster"),
            ("SELECT * FROM information_schema.tables WHERE table_schema = 'public' LIMIT 5", "public_tables"),
            ("SELECT schemaname, tablename FROM pg_tables WHERE schemaname = 'public' LIMIT 5", "pg_tables"),
            ("SELECT COUNT(DISTINCT pg_backend_pid()) as active_connections FROM pg_stat_activity WHERE state = 'active'", "active_connections"),
        ]
        
        for query, label in system_queries:
            try:
                # Create a fresh connection for each query to avoid transaction state issues
                fresh_connector = connector_class(config=credentials["redshift"])
                result = fresh_connector.execute_query(query)
                fresh_connector.close()
                
                test_results[label] = {
                    "query": query,
                    "success": True,
                    "result": result[:3] if result else [],  # Only show first 3 rows
                    "row_count": len(result) if result else 0
                }
            except Exception as e:
                test_results[label] = {
                    "query": query,
                    "success": False,
                    "error": str(e)
                }
        
        connector.close()
        return test_results
        
    except Exception as e:
        return {"error": f"Failed to test Redshift system tables: {str(e)}"}

# Initialize shared queue for results
if "seq_results_queue" not in st.session_state:
    st.session_state["seq_results_queue"] = queue.Queue()
if "seq_results" not in st.session_state:
    st.session_state["seq_results"] = []
if "seq_running" not in st.session_state:
    st.session_state["seq_running"] = False
if "seq_error" not in st.session_state:
    st.session_state["seq_error"] = None
if "cluster_costs" not in st.session_state:
    st.session_state["cluster_costs"] = {}

# --- Sidebar UI ---
default_creds_path = str(Path(__file__).parent.parent.parent.parent / "config" / "credentials" / "credentials.json")
benchmark_name = st.sidebar.text_input("Benchmark Name", value="FireScale")
creds_file = st.sidebar.text_input("Credentials File", value=default_creds_path)
vendor_options = ["firebolt", "redshift", "snowflake", "google"]
vendors = st.sidebar.multiselect("Vendors", vendor_options, default=["firebolt"])
pool_size = st.sidebar.number_input("Query Set Runs", min_value=1, value=1, step=1)
concurrency = st.sidebar.number_input("Concurrent Queries", min_value=1, value=1, step=1)
output_dir = st.sidebar.text_input("Output Directory", value="benchmark_results")
logging_level = st.sidebar.selectbox("Logging Level", ["Information", "Debug"], index=0)

# --- Benchmark Control Buttons ---
st.sidebar.markdown("---")
st.sidebar.markdown("### 🚀 Benchmark Control")
run_seq = st.sidebar.button("▶️ Run Benchmark", key="run_seq_btn", use_container_width=True)
seq_reset = st.sidebar.button("🔄 Reset", on_click=reset_session, key="reset_seq_btn", use_container_width=True)

# --- Debug Section (only show when Debug logging is selected) ---
if logging_level == "Debug":
    with st.sidebar.expander("🐛 Debug Tools"):
        if st.button("Test Firebolt Queries"):
            if "firebolt" in vendors:
                st.session_state["firebolt_test_results"] = test_firebolt_queries(creds_file)
            else:
                st.warning("Add Firebolt to vendors to test queries")
        
        if st.button("Check Table Row Counts"):
            if "firebolt" in vendors:
                st.session_state["table_counts"] = check_table_counts(creds_file)
            else:
                st.warning("Add Firebolt to vendors to check tables")
        
        if st.button("Test Redshift System Tables"):
            if "redshift" in vendors:
                st.session_state["redshift_system_test"] = test_redshift_system_tables(creds_file)
            else:
                st.warning("Add Redshift to vendors to test system tables")

# --- Compute Cluster Information ---
if vendors:
    # Use a unique key for the cluster container to prevent duplication
    cluster_container_key = f"cluster_info_{hash(tuple(sorted(vendors)))}"
    
    # Create a unique container to prevent duplication during refreshes
    with st.container(key=cluster_container_key):
        # Custom CSS for the cluster info container
        st.markdown("""
        <style>
        .cluster-container {
            background-color: #f0f2f6;
            padding: 15px;
            border-radius: 10px;
            border: 1px solid #e0e0e0;
            margin: 10px 0;
        }
        .cluster-info {
            font-size: 0.85em;
            line-height: 1.3;
        }
        .cluster-header {
            font-size: 1.1em;
            font-weight: bold;
            margin-bottom: 10px;
        }
        </style>
        """, unsafe_allow_html=True)
        
        col1, col2 = st.columns([4, 1])
        with col1:
            st.markdown('<div class="cluster-header">🖥️ Compute Cluster Information</div>', unsafe_allow_html=True)
        with col2:
            if st.button("🔄 Refresh", key="refresh_cluster_btn", use_container_width=True):
                # Clear the cache to force refresh
                get_cluster_information.clear()
                # Clear any stored cluster info to prevent duplication
                if "cluster_info_cache" in st.session_state:
                    del st.session_state["cluster_info_cache"]
                st.rerun()
        
        # Container with custom styling - use a unique div ID
        st.markdown(f'<div class="cluster-container" id="cluster-{cluster_container_key}">', unsafe_allow_html=True)
        
        cluster_cols = st.columns(len(vendors))
        
        # Initialize cluster info cache if not exists
        if "cluster_info_cache" not in st.session_state:
            st.session_state["cluster_info_cache"] = {}
        
        for i, vendor in enumerate(vendors):
            with cluster_cols[i]:
                st.markdown(f'<div class="cluster-info"><strong>{vendor.title()}</strong></div>', unsafe_allow_html=True)
                
                # Get real cluster information
                debug_mode = (logging_level == "Debug")
                
                # Create a stable cache key
                cache_key = f"{vendor}_{hash(creds_file)}_{debug_mode}"
                
                # Check if we already have this vendor's info to prevent duplication
                if cache_key not in st.session_state["cluster_info_cache"]:
                    cluster_info = get_cluster_information(vendor, creds_file, debug_mode)
                    st.session_state["cluster_info_cache"][cache_key] = cluster_info
                else:
                    cluster_info = st.session_state["cluster_info_cache"][cache_key]
                
                if "error" in cluster_info:
                    st.error(f"❌ {cluster_info['error']}", help="Connection failed")
                    if debug_mode:
                        st.code(cluster_info['error'], language='text')
                else:
                    st.success("✅ Connected")
                    
                    # Calculate estimated hourly cost
                    hourly_cost = calculate_hourly_cost(vendor, cluster_info)
                    
                    # Compact display with smaller text
                    if vendor == "firebolt":
                        st.markdown(f"""
                        <div class="cluster-info">
                        <b>Engine:</b> {cluster_info.get('engine_name', 'Unknown')}<br>
                        <b>Type:</b> {cluster_info.get('type', 'Unknown')}<br>
                        <b>Nodes:</b> {cluster_info.get('nodes', 'Unknown')}<br>
                        <b>Status:</b> {cluster_info.get('status', 'Unknown')}<br>
                        <b>FBU Rate:</b> {cluster_info.get('fbu_rate', 'Unknown')}<br>
                        <b>💰 Cost/Hour:</b> ${hourly_cost:.2f}
                        </div>
                        """, unsafe_allow_html=True)
                    elif vendor == "snowflake":
                        st.markdown(f"""
                        <div class="cluster-info">
                        <b>Warehouse:</b> {cluster_info.get('warehouse_name', 'Unknown')}<br>
                        <b>Size:</b> {cluster_info.get('size', 'Unknown')}<br>
                        <b>State:</b> {cluster_info.get('state', 'Unknown')}<br>
                        <b>Min/Max Clusters:</b> {cluster_info.get('min_cluster_count', 'Unknown')}/{cluster_info.get('max_cluster_count', 'Unknown')}<br>
                        <b>💰 Cost/Hour:</b> ${hourly_cost:.2f}
                        </div>
                        """, unsafe_allow_html=True)
                    elif vendor == "redshift":
                        nodes = cluster_info.get('nodes', [])
                        node_info = ""
                        if nodes:
                            for node in nodes:
                                node_info += f"{node.get('node_type', 'Unknown')} ({node.get('node_count', 'Unknown')})<br>"
                        st.markdown(f"""
                        <div class="cluster-info">
                        <b>Host:</b> {cluster_info.get('host', 'Unknown')}<br>
                        <b>Database:</b> {cluster_info.get('database', 'Unknown')}<br>
                        <b>Nodes:</b> {node_info if node_info else 'Unknown'}<br>
                        <b>💰 Cost/Hour:</b> ${hourly_cost:.2f}
                        </div>
                        """, unsafe_allow_html=True)
                    elif vendor == "google":
                        st.markdown(f"""
                        <div class="cluster-info">
                        <b>Project:</b> {cluster_info.get('project_name', 'Unknown')}<br>
                        <b>Dataset:</b> {cluster_info.get('dataset', 'Unknown')}<br>
                        <b>Location:</b> {cluster_info.get('location', 'Unknown')}<br>
                        <b>💰 Cost/Hour:</b> ${hourly_cost:.2f}
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        # Fallback for unknown vendors
                        info_text = ""
                        for key, value in cluster_info.items():
                            if key != "error":
                                info_text += f"<b>{key.replace('_', ' ').title()}:</b> {value}<br>"
                        info_text += f"<b>💰 Cost/Hour:</b> ${hourly_cost:.2f}"
                        st.markdown(f'<div class="cluster-info">{info_text}</div>', unsafe_allow_html=True)
                    
                    # Store hourly cost in cluster_info for later use
                    cluster_info["hourly_cost"] = hourly_cost
                    # Also store in session state for benchmark cost calculations
                    st.session_state["cluster_costs"][vendor] = hourly_cost
                    
                    # Show debug information if debug mode is enabled
                    if debug_mode:
                        with st.expander("🐛 Debug"):
                            st.json(cluster_info)
        
        st.markdown('</div>', unsafe_allow_html=True)

# --- Debug Test Results ---
if logging_level == "Debug" and "firebolt_test_results" in st.session_state:
    st.header("🐛 Firebolt Query Test Results")
    test_results = st.session_state["firebolt_test_results"]
    if "error" in test_results:
        st.error(test_results["error"])
    else:
        for test_name, result in test_results.items():
            with st.expander(f"Test: {test_name}"):
                st.code(result["query"], language="sql")
                if result["success"]:
                    st.success(f"✅ Success - {result['row_count']} rows returned")
                    if result["result"]:
                        st.json(result["result"])
                else:
                    st.error(f"❌ Error: {result['error']}")

# --- Debug Table Count Results ---
if logging_level == "Debug" and "table_counts" in st.session_state:
    st.header("🐛 Firebolt Table Row Counts")
    table_results = st.session_state["table_counts"]
    if "error" in table_results:
        st.error(table_results["error"])
    else:
        cols = st.columns(len(table_results))
        for i, (table_name, result) in enumerate(table_results.items()):
            with cols[i]:
                if result["exists"]:
                    if result["row_count"] > 0:
                        st.success(f"✅ **{table_name}**")
                        st.metric("Rows", f"{result['row_count']:,}")
                    else:
                        st.warning(f"⚠️ **{table_name}**")
                        st.metric("Rows", "0")
                        st.caption("Table exists but empty!")
                else:
                    st.error(f"❌ **{table_name}**")
                    st.caption("Table missing!")
                    if "error" in result:
                        st.caption(f"Error: {result['error']}")
        
        # Show detailed sample data
        st.subheader("Sample Data")
        for table_name, result in table_results.items():
            if result["exists"] and result.get("sample_data"):
                with st.expander(f"Sample from {table_name} table"):
                    st.json(result["sample_data"])

# --- Debug Redshift System Table Results ---
if logging_level == "Debug" and "redshift_system_test" in st.session_state:
    st.header("🐛 Redshift System Table Access Test")
    test_results = st.session_state["redshift_system_test"]
    if "error" in test_results:
        st.error(test_results["error"])
    else:
        for test_name, result in test_results.items():
            with st.expander(f"Test: {test_name}"):
                st.code(result["query"], language="sql")
                if result["success"]:
                    st.success(f"✅ Success - {result['row_count']} rows returned")
                    if result["result"]:
                        st.json(result["result"])
                else:
                    st.error(f"❌ Error: {result['error']}")
                    if "permission" in result["error"].lower() or "access" in result["error"].lower():
                        st.info("💡 This looks like a permissions issue. Your user may not have access to system tables.")

# --- Benchmark Results Section ---
seq_progress = st.empty()
kpi_cols = st.columns(4)  # Changed back from 5 to 4 columns
seq_chart = st.empty()
concurrency_chart = st.empty()  # New: for concurrency per second chart
seq_table = st.empty()
seq_error = st.empty()

def run_worker(results_queue, vendors, benchmark_name, creds_file, pool_size, output_dir, benchmark_path, logging_level, worker_id):
    try:
        runner = BenchmarkRunner(
            benchmark_name=benchmark_name,
            creds_file=creds_file,
            vendors=vendors,
            pool_size=pool_size,
            concurrency=1,
            output_dir=output_dir,
            benchmark_path=str(benchmark_path),
            execute_setup=False,  # Always False since setup should be run manually
            results_queue=results_queue,
            run_warmup=False,  # Removed warmup functionality
            warmup_status_callback=None,
            logging_level=logging_level,
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
    st.session_state["kpi_charts_rendered"] = False

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
                logging_level,
                i
            ),
            daemon=True
        )
        t.start()

# --- Results and Progress ---
results_queue = st.session_state.get("seq_results_queue")
new_results_added = False
if results_queue:
    while not results_queue.empty():
        st.session_state["seq_results"].append(results_queue.get())
        new_results_added = True

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
                y=alt.Y(
                    "vendor:N",
                    sort=None,
                    title="Vendor",
                    axis=alt.Axis(labelExpr="datum.value", labelOverlap=False, labelFontSize=14, ticks=True)
                ),
                x=alt.X(f"{metric}:Q", title=metric.capitalize()),
                color=alt.Color("vendor:N", scale=alt.Scale(domain=list(vendor_colors.keys()), range=list(vendor_colors.values())), legend=None),
                tooltip=["vendor", metric]
            )
            .properties(height=120)
        ).configure_axis(
            labelOverlap=False  # Ensure all vendor labels are always shown
        )
        return chart

    # Always render KPI charts but with stable keys to prevent flashing
    with kpi_cols[0]:
        st.markdown("**Max Response Time (s)**")
        st.altair_chart(color_bar_chart(vendor_stats, "max"), use_container_width=True, key="max_chart_stable")
    with kpi_cols[1]:
        st.markdown("**Min Response Time (s)**")
        st.altair_chart(color_bar_chart(vendor_stats, "min"), use_container_width=True, key="min_chart_stable")
    with kpi_cols[2]:
        st.markdown("**Avg Response Time (s)**")
        st.altair_chart(color_bar_chart(vendor_stats, "avg"), use_container_width=True, key="avg_chart_stable")
    with kpi_cols[3]:
        st.markdown("**Total Time (s)**")
        st.altair_chart(color_bar_chart(vendor_stats, "total"), use_container_width=True, key="total_chart_stable")

    # --- Cost Analysis Section ---
    cluster_costs = st.session_state.get("cluster_costs", {})
    if cluster_costs and any(vendor in cluster_costs for vendor in df['vendor'].unique()):
        import altair as alt  # Import altair for cost charts
        st.markdown("#### 💰 Cost Analysis")
        cost_cols = st.columns(2)
        
        with cost_cols[0]:
            # Cost per vendor based on actual time each vendor took
            cost_data = []
            
            for vendor in df['vendor'].unique():
                if vendor in cluster_costs:
                    # Calculate actual time this vendor took (sum of all query durations)
                    vendor_df = df[df['vendor'] == vendor]
                    vendor_total_time_seconds = vendor_df['duration'].sum()
                    vendor_time_hours = vendor_total_time_seconds / 3600
                    
                    vendor_cost = vendor_time_hours * cluster_costs[vendor]
                    cost_data.append({"vendor": vendor, "cost": vendor_cost})
            
            if cost_data:
                cost_df = pd.DataFrame(cost_data)
                st.markdown("**Total Benchmark Cost by Vendor**")
                cost_chart = color_bar_chart(cost_df, "cost")
                # Update the x-axis title for cost chart
                cost_chart = cost_chart.encode(x=alt.X("cost:Q", title="Cost ($)"))
                st.altair_chart(cost_chart, use_container_width=True)
        
        with cost_cols[1]:
            # Cost efficiency: Cost per query
            if cost_data:
                efficiency_data = []
                for vendor in df['vendor'].unique():
                    if vendor in cluster_costs:
                        # Calculate actual time this vendor took (sum of all query durations)
                        vendor_df = df[df['vendor'] == vendor]
                        vendor_total_time_seconds = vendor_df['duration'].sum()
                        vendor_time_hours = vendor_total_time_seconds / 3600
                        
                        vendor_queries = len(vendor_df)
                        vendor_cost = vendor_time_hours * cluster_costs[vendor]
                        cost_per_query = vendor_cost / vendor_queries if vendor_queries > 0 else 0
                        efficiency_data.append({"vendor": vendor, "cost_per_query": cost_per_query})
                
                if efficiency_data:
                    efficiency_df = pd.DataFrame(efficiency_data)
                    st.markdown("**Cost per Query by Vendor**")
                    efficiency_chart = color_bar_chart(efficiency_df, "cost_per_query")
                    efficiency_chart = efficiency_chart.encode(x=alt.X("cost_per_query:Q", title="Cost per Query ($)"))
                    st.altair_chart(efficiency_chart, use_container_width=True)

    # --- Line chart: x = query_number (1-25), y = avg duration per query_name, per vendor ---
    st.markdown("#### Query Duration by Vendor")
    
    # Extract actual query number from query_name (e.g., "query 1" -> 1)
    def extract_query_number(query_name):
        try:
            # Extract number from "query X" format
            parts = str(query_name).split()
            if len(parts) >= 2 and parts[0].lower() == "query":
                return int(parts[1])
            # Fallback: try to extract any number from the string
            import re
            numbers = re.findall(r'\d+', str(query_name))
            if numbers:
                return int(numbers[0])
            return 0
        except:
            return 0
    
    df["query_number"] = df["query_name"].apply(extract_query_number)
    
    # Filter out invalid query numbers (0) to avoid misalignment
    df = df[df["query_number"] > 0]
    
    # Debug: Show query alignment if debug mode is enabled
    if logging_level == "Debug":
        st.expander("🐛 Query Alignment Debug").write("Query Number Assignment:")
        debug_df = df[["vendor", "query_name", "query_number"]].drop_duplicates().sort_values(["query_number", "vendor"])
        st.expander("🐛 Query Alignment Debug").dataframe(debug_df, use_container_width=True)
    
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
        .properties(height=450)  # Increased from 300 to 450
    )
    seq_chart.altair_chart(line_chart, use_container_width=True, key="duration_chart")

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
        # Use relative seconds from min_time for x-axis
        df["elapsed_sec"] = ((df["start_time"] - min_time).dt.total_seconds()).astype(int)
        # Group by vendor and elapsed_sec for per-vendor concurrency
        concurrency_df = df.groupby(["vendor", "elapsed_sec"]).size().reset_index(name="queries")
        import altair as alt
        concurrency_chart.altair_chart(
            alt.Chart(concurrency_df)
            .mark_line(point=True)
            .encode(
                x=alt.X("elapsed_sec:Q", title="Second"),
                y=alt.Y("queries:Q", title="Queries Started"),
                color=alt.Color("vendor:N", scale=alt.Scale(domain=list(vendor_colors.keys()), range=list(vendor_colors.values())), legend=alt.Legend(title="Vendor")),
                tooltip=["vendor", "elapsed_sec", "queries"]
            )
            .properties(height=300, title="Concurrency Per Second (by Vendor)"),  # Increased from 200 to 300
            use_container_width=True,
            key="concurrency_chart"
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
    st.dataframe(table_display, use_container_width=True, key="results_table")

if st.session_state.get("seq_error"):
    seq_error.error(st.session_state["seq_error"])

# Only rerun if benchmark is running AND we have new results or status changes
if st.session_state.get("seq_running"):
    # Use a more conservative refresh rate and only when needed
    if new_results_added:
        time.sleep(0.5)  # Reduced from 1 second to 0.5 seconds
        st.rerun()
    else:
        # If no new results, wait longer before checking again
        time.sleep(2)
        st.rerun()