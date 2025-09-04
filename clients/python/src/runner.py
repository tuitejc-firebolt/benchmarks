import csv
import itertools
import json
import logging
import os
import pathlib
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Queue
from typing import Any, Dict, List, Optional

import connectors
import exporters  # changed from 'from .exporters import CSVExporter, VisualExporter'

ITERATIONS_PER_QUERY = 1  # <-- set this to 1 to run exactly 25 queries

@dataclass
class QueryResult:
    query_number: int
    execution_time: float
    concurrent_run: int
    success: bool
    error: Optional[str] = None
    vendor: Optional[str] = None
    query_name: Optional[str] = None

class ConnectionPool:
    def __init__(self, connector, credentials: Dict, pool_size: int = 5):
        self.connector = connector
        self.credentials = credentials
        self.pool_size = pool_size
        self.connections = Queue(maxsize=pool_size)
        self._lock = threading.Lock()
        self._fill_pool()

    def _fill_pool(self):
        for _ in range(self.pool_size):
            # Create a new connector instance for each connection
            connector = self.connector.__class__(config=self.credentials)
            connector.connect()
            self.connections.put(connector)

    def get_connection(self):
        return self.connections.get()

    def return_connection(self, connector):
        self.connections.put(connector)

    def close_all(self):
        while not self.connections.empty():
            connector = self.connections.get()
            connector.close()

class BenchmarkRunner:
    def __init__(
        self,
        benchmark_name: str,
        creds_file: str,
        vendors: List[str] = None,
        pool_size: int = ITERATIONS_PER_QUERY,
        concurrency: int = 1,
        output_dir: str = 'benchmark_results',
        execute_setup: bool = False,
        benchmark_path: str = "",
        results_queue: Optional[Queue] = None,  # <-- add this parameter
        run_warmup=True,
        warmup_status_callback=None,
        logging_level: str = "Information",
    ):
        self.benchmark_name = benchmark_name
        self.vendors = vendors
        self.concurrency = concurrency
        #  pool_size cannot be smaller than the expected concurrency level
        self.pool_size =  pool_size if concurrency <= pool_size else concurrency
        self.output_dir = output_dir
        self.execute_setup = execute_setup
        self.logger = logging.getLogger(__name__)
        self.logging_level = logging_level  # Store logging level for use in other methods
        
        # Configure logging level
        if logging_level.lower() == "debug":
            self.logger.setLevel(logging.DEBUG)
            logging.getLogger().setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)
            logging.getLogger().setLevel(logging.INFO)
            
        self.benchmark_path = benchmark_path
        self.connection_pools = {}
        self.results_queue = results_queue  # store the queue
        self.run_warmup = run_warmup
        self.warmup_status_callback = warmup_status_callback
        
        # Load credentials
        with open(creds_file, 'r') as f:
            self.credentials = json.load(f)
            
        # Initialize connectors
        self.connectors = {}
        for vendor in vendors:
            if vendor not in self.credentials:
                raise ValueError(f"No credentials found for vendor: {vendor}")

            connector_class = connectors.get_connector_class(vendor)
            self.connectors[vendor] = connector_class(config=self.credentials[vendor])

    def _load_queries(self, query_file):
        if isinstance(query_file, (str, bytes, os.PathLike)):
            with open(query_file, 'r') as f:
                # Read the entire file and split by newlines first
                lines = f.readlines()
                queries = []
                current_query = []
                
                for line in lines:
                    line = line.strip()
                    # Skip empty lines
                    if not line:
                        continue
                    
                    # Smart comment removal: only remove '--' that are not inside string literals
                    processed_line = self._remove_sql_comments(line)
                    
                    # Skip lines that are now empty after removing comments
                    if not processed_line:
                        continue
                    
                    # If the line ends with a semicolon, it's a complete query
                    if processed_line.endswith(';'):
                        current_query.append(processed_line[:-1])  # Remove the semicolon
                        if current_query:  # Only add non-empty queries
                            query_text = ' '.join(current_query).strip()
                            if query_text and not query_text.isspace():  # Ensure the query is not empty or just whitespace
                                queries.append(query_text)
                                if self.logging_level.lower() == "debug":
                                    print(f"[DEBUG] Parsed query {len(queries)} from {query_file}: {query_text[:100]}...")
                        current_query = []  # Reset for the next query
                    else:
                        current_query.append(processed_line)

                # Handle any remaining query that doesn't end with a semicolon
                if current_query:
                    query_text = ' '.join(current_query).strip()
                    if query_text and not query_text.isspace():  # Ensure the query is not empty or just whitespace
                        queries.append(query_text)
                        if self.logging_level.lower() == "debug":
                            print(f"[DEBUG] Parsed final query {len(queries)} from {query_file}: {query_text[:100]}...")

                if self.logging_level.lower() == "debug":
                    print(f"[DEBUG] Total queries parsed from {query_file}: {len(queries)}")
                    
                # Critical: Ensure exactly 25 queries for all vendors
                if len(queries) != 25:
                    error_msg = f"Expected 25 queries but found {len(queries)} in {query_file}"
                    if self.logging_level.lower() == "debug":
                        print(f"[ERROR] {error_msg}")
                    else:
                        print(f"[ERROR] {error_msg}")
                    # Rather than failing, let's pad or truncate to ensure consistency
                    if len(queries) > 25:
                        print(f"[WARNING] Truncating {len(queries)} queries to 25")
                        queries = queries[:25]
                    elif len(queries) < 25:
                        print(f"[WARNING] Only {len(queries)} queries found, expected 25. Check SQL file format.")
                        # Pad with placeholder queries to maintain numbering consistency
                        while len(queries) < 25:
                            queries.append(f"-- Placeholder query {len(queries) + 1} (missing from file)")
                    
                return queries
        elif isinstance(query_file, list):
            return query_file
        else:
            raise TypeError("query_file must be a file path or list of queries")

    def _remove_sql_comments(self, line):
        """Remove SQL comments while preserving '--' inside string literals."""
        result = []
        in_single_quote = False
        in_double_quote = False
        i = 0
        
        while i < len(line):
            char = line[i]
            
            # Handle single quotes
            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                result.append(char)
            # Handle double quotes  
            elif char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                result.append(char)
            # Handle potential comment start
            elif char == '-' and i + 1 < len(line) and line[i + 1] == '-':
                # If we're inside quotes, this is not a comment
                if in_single_quote or in_double_quote:
                    result.append(char)
                else:
                    # This is a real comment, stop processing the line
                    break
            else:
                result.append(char)
            
            i += 1
        
        return ''.join(result).strip()

    def _run_query(self, vendor: str, query_name: str, query: str, concurrent_run: int) -> Dict[str, Any]:
        """Execute a single query and return its results."""
        start_time = time.time()
        connection = None
        try:
            print(f"[BenchmarkRunner] About to get connection for {vendor}", flush=True)
            import sys; sys.stdout.flush()
            connection = self.connection_pools[vendor].get_connection()
            print(f"[BenchmarkRunner] Got connection for {vendor}, running query {query_name} (concurrent_run={concurrent_run})", flush=True)
            import sys; sys.stdout.flush()
            results = connection.execute_query(query)
            print(f"[BenchmarkRunner] Finished query {query_name} for {vendor} (concurrent_run={concurrent_run}), got {len(results) if results else 0} rows", flush=True)
            import sys; sys.stdout.flush()
            duration = time.time() - start_time

            result = {
                'vendor': vendor,
                'query_name': query_name,
                'query': query,  # <-- Add the actual SQL text here
                'duration': duration,
                'rows': len(results) if results else 0,
                'status': 'success',
                'timestamp': datetime.now().isoformat(),
                'concurrent_run': concurrent_run
            }
            if self.results_queue:
                print(f"[BenchmarkRunner] Putting result for {vendor} query {query_name} into queue (before put, queue size: {self.results_queue.qsize()})", flush=True)
                import sys; sys.stdout.flush()
                self.results_queue.put(result)
                print(f"[BenchmarkRunner] Queue size after put: {self.results_queue.qsize()}", flush=True)
                import sys; sys.stdout.flush()
                try:
                    test_peek = self.results_queue.get_nowait()
                    print(f"[BenchmarkRunner] DEBUG: Immediately got from queue: {test_peek}", flush=True)
                    self.results_queue.put(test_peek)
                except Exception as e:
                    print(f"[BenchmarkRunner] DEBUG: Queue empty after put: {e}", flush=True)
                import sys; sys.stdout.flush()
            print(f"[BenchmarkRunner] COMPLETED {vendor} {query_name} (concurrent_run={concurrent_run})", flush=True)
            import sys; sys.stdout.flush()
            return result
        except Exception as e:
            self.logger.error(f"Error running query {query_name} for {vendor}: {str(e)}")
            print(f"[BenchmarkRunner] Error running query {query_name} for {vendor}: {str(e)}", flush=True)
            import sys; sys.stdout.flush()
            return {
                'vendor': vendor,
                'query_name': query_name,
                'query': query,  # <-- Add the actual SQL text here for error rows too
                'duration': time.time() - start_time,
                'rows': 0,
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat(),
                'concurrent_run': concurrent_run
            }
        finally:
            if connection:
                self.connection_pools[vendor].return_connection(connection)

    def _run_concurrent_query(self, vendor: str, query: str, query_number: int) -> List[QueryResult]:
        """Run a query concurrently and return the results."""
        results = []
        query_name = f"query {query_number}"  # Create consistent query name
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            future_to_query = {executor.submit(self._run_query, vendor, query_name, query, i+1): query for i in range(self.concurrency)}
            
            for future in as_completed(future_to_query):
                try:
                    result = future.result()
                    results.append(QueryResult(
                        query_number=query_number,
                        execution_time=result['duration'],
                        success=result['status'] == 'success',
                        error=result.get('error'),
                        vendor=result['vendor'],
                        query_name=result['query_name'],
                        concurrent_run=result['concurrent_run']
                    ))
                except Exception as e:
                    self.logger.error(f"Error in concurrent execution: {str(e)}")
        # Do NOT update st.session_state here!
        return results
    
    def _get_sql_file(self, vendor, file_type):
        # Construct the general and vendor-specific file paths
        general_file = Path(self.benchmark_path) / f"{file_type}.sql"
        vendor_dir = Path(self.benchmark_path) / f"{vendor}"
        vendor_file = vendor_dir / f"{file_type}.sql"

        # Log which directory is being checked
        self.logger.info(f"Looking for SQL file for vendor '{vendor}': {vendor_file}")
        if not vendor_dir.exists():
            self.logger.error(f"Vendor directory does not exist: {vendor_dir}")
        # Check if vendor-specific file exists, return it if it does, otherwise return the general file
        if os.path.exists(vendor_file):
            return vendor_file
        return general_file


    def run_benchmark(self) -> Dict:
        results = {}
        num_iterations = ITERATIONS_PER_QUERY if self.concurrency == 1 else 1 # Run each query multiple times to get a distribution

        def run_vendor_benchmark(vendor):
            if vendor not in self.connectors:
                self.logger.warning(f"Skipping {vendor} - connector not implemented")
                return vendor, []

            self.logger.info(f"Running benchmark for {vendor.upper()}...")

            # Execute setup script if execute_setup is True
            if self.execute_setup:
                if not self._execute_setup_script(vendor):  # Only run benchmark if setup succeeded
                    self.logger.warning("Skipping benchmark due to setup failure.")
                    return vendor, []

            if not self._execute_warmup_script(vendor): 
                # Only run benchmark if warmup succeeded
                self.logger.warning("Skipping benchmark due to warmup failure.")
                return vendor, []

            vendor_results = []

            try:
                self.connection_pools[vendor] = ConnectionPool(
                    self.connectors[vendor],
                    self.credentials[vendor],
                    self.pool_size
                )

                # Load the appropriate benchmark SQL file for the vendor
                benchmark_file = self._get_sql_file(vendor, 'benchmark')
                benchmark_queries = self._load_queries(benchmark_file)
                if not benchmark_queries:
                    raise ValueError(f"No benchmark queries found for vendor: {vendor}")
                self.logger.info(f"Loaded {len(benchmark_queries)} benchmark queries for: {vendor}")

                for query_number, query in enumerate(benchmark_queries, 1):
                    self.logger.info(f"Running query {query_number} with {self.concurrency} concurrent executions...")
                    # Run each query multiple times
                    for iteration in range(num_iterations):
                        self.logger.info(f"  Iteration {iteration + 1}/{num_iterations}")
                        query_results = self._run_concurrent_query(vendor, query, query_number)
                        vendor_results.extend(query_results)

                # Prepare data for CSV export
                csv_data = [
                    {
                        'vendor': result.vendor,
                        'query_name': result.query_name,
                        'execution_time': result.execution_time,
                        'concurrent_run': result.concurrent_run,
                        'success': result.success,
                        'error': result.error
                    }
                    for result in vendor_results
                ]

            except Exception as e:
                self.logger.error(f"Error running benchmark for {vendor}: {str(e)}")
                csv_data = []
            finally:
                 # Ensure proper cleanup
                self.connection_pools[vendor].close_all()
                self.connectors[vendor].close() 

            return vendor, csv_data

        with ThreadPoolExecutor(max_workers=len(self.vendors)) as executor:
            future_to_vendor = {executor.submit(run_vendor_benchmark, vendor): vendor for vendor in self.vendors}
            for future in as_completed(future_to_vendor):
                vendor, csv_data = future.result()
                if csv_data:
                    results[vendor] = csv_data

        if not results:
            self.logger.warning("No results were generated from the benchmark.")
        else:
            # Ensure the directory exists
            os.makedirs(self.output_dir, exist_ok=True)
            # Use the CSV Exporter to export results
            csv_exporter = exporters.CSVExporter()  # changed
            csv_exporter.export(results, self.output_dir)

            # Visual export
            visual_exporter = exporters.VisualExporter(self.output_dir)  # changed
            visual_exporter.export(results, self.output_dir)

        return results

    def _execute_setup_script(self, vendor: str):
        """Execute the setup SQL script for the vendor."""
        try:
            # Load the setup SQL file for the vendor
            setup_file = self._get_sql_file(vendor, 'setup')
            setup_queries = self._load_queries(setup_file)
            for query in setup_queries:
                self.connectors[vendor].execute_query(query)
            self.logger.info(f"Executed setup script: {setup_file}")
        except Exception as e:
            self.logger.error(f"Error executing setup script {setup_file}: {str(e)}")
            return False
        return True

    def _execute_warmup_script(self, vendor: str):
        """Execute the warmup SQL script for the vendor."""
        if not getattr(self, "run_warmup", True):
            return True
        try:
            warmup_file = self._get_sql_file(vendor, "warmup")
            warmup_queries = self._load_queries(warmup_file)
            total = len(warmup_queries)
            for idx, query in enumerate(warmup_queries):
                msg = f"Warming up database ({vendor}): Step {idx+1} of {total}"
                if self.warmup_status_callback:
                    self.warmup_status_callback(msg)
                print(f"[BenchmarkRunner] {msg}: {query[:200]}...", flush=True)
                import sys; sys.stdout.flush()
                self.connectors[vendor].execute_query(query)
                print(f"[BenchmarkRunner] Finished warmup query {idx+1}/{total} for {vendor}", flush=True)
                import sys; sys.stdout.flush()
            if self.warmup_status_callback:
                self.warmup_status_callback(None)
            self.logger.info(f"Executed warmup script: {warmup_file}")
        except Exception as e:
            self.logger.error(f"Error executing warmup script {warmup_file}: {str(e)}")
            print(f"[BenchmarkRunner] Error executing warmup script {warmup_file}: {str(e)}", flush=True)
            import sys; sys.stdout.flush()
            if self.warmup_status_callback:
                self.warmup_status_callback(None)
            return False
        return True


@dataclass
class ConcurrentQueryResult:
    query_name: str
    query_id: int
    has_error: bool
    num_output_rows: int
    start_unix_time: float
    stop_unix_time: float


class ConcurrentBenchmarkRunner:
    def __init__(
        self,
        benchmark_name: str,
        creds_file: str,
        vendor: str,
        concurrency: int,
        benchmark_duration_secs: int,
        output_dir: str,
        benchmark_path: str,
        seed: int,
    ):
        self.benchmark_name = benchmark_name
        self.vendor = vendor
        self.concurrency = concurrency
        self.benchmark_duration_secs = benchmark_duration_secs
        self.output_dir = output_dir
        self.benchmark_path = benchmark_path
        self.logger = logging.getLogger(__name__)
        self.connector_class = connectors.get_connector_class(self.vendor)
        self.seed = seed

        # Load credentials
        with open(creds_file, "r") as f:
            all_credentials = json.load(f)
            if vendor not in all_credentials:
                raise ValueError(f"No credentials found for vendor: {vendor}")
            self.credentials = all_credentials[vendor]

        # Load queries
        queries_file = self._get_sql_file(vendor)
        with open(queries_file, "r") as f:
            self.queries = json.load(f)
        if not self.queries:
            raise ValueError(f"No benchmark queries found for vendor: {vendor}")

        # Get the names of the queries
        self.query_names = list(self.queries.keys())
        self.logger.info(
            f"Loaded {len(self.query_names)} benchmark queries for: {vendor}"
        )

    def _get_sql_file(self, vendor):
        general_file = pathlib.Path(self.benchmark_path) / "queries.json"
        vendor_file = pathlib.Path(self.benchmark_path) / f"{vendor}" / "queries.json"
        return vendor_file if os.path.exists(vendor_file) else general_file

    def _run_worker(self, worker_id: int, seed: int):
        # Seed the random number generator for reproducibility
        rng = random.Random(seed)
        # Each worker thread should execute the queries in a random order
        query_names_random_permutation = rng.sample(
            self.query_names, len(self.query_names)
        )
        # Connect to the database
        connector = self.connector_class(config=self.credentials)
        connector.connect()
        results = []

        # Wait until all worker threads are ready
        self.start_barrier.wait()

        # The query ID increases by one for each executed query
        query_id = 0

        # Repeatedly iterate over the queries until the main thread sets `self.stop_event`
        for query_name in itertools.cycle(query_names_random_permutation):
            # Choose a random variation of the query
            random_query_variation = rng.choice(self.queries[query_name])
            try:
                has_error = False
                start_time = time.time()
                num_output_rows = len(connector.execute_query(random_query_variation))
                stop_time = time.time()
            except Exception as e:
                has_error = True
                self.logger.error(
                    f"Error running query {query_name} for {self.vendor}: {str(e)}"
                )

            if self.stop_event.is_set():
                # Stop the worker thread. The current query did not finish in time and should not
                # be included in `self.worker_thread_results`.
                self.worker_thread_results[worker_id] = results
                connector.close()
                return
            else:
                results.append(
                    ConcurrentQueryResult(
                        query_name=query_name,
                        query_id=query_id,
                        has_error=has_error,
                        num_output_rows=0 if has_error else num_output_rows,
                        start_unix_time=start_time,
                        stop_unix_time=stop_time,
                    )
                )
                query_id += 1

    def _write_csv(self):
        # Ensure the directory exists
        os.makedirs(self.output_dir, exist_ok=True)
        csv_file_path = os.path.join(self.output_dir, f"{self.vendor}_concurrency.csv")
        with open(csv_file_path, mode="w", newline="") as csv_file:
            field_names = [
                "worker_id",
                "query_name",
                "query_id",
                "has_error",
                "num_output_rows",
                "start_unix_time",
                "stop_unix_time",
            ]
            writer = csv.DictWriter(csv_file, fieldnames=field_names)
            writer.writeheader()
            for worker_id, worker_results in enumerate(self.worker_thread_results):
                if not worker_results:
                    self.logger.warning(f"No results found for worker {worker_id}")
                for result in worker_results:
                    row = {
                        "worker_id": worker_id,
                        "query_name": result.query_name,
                        "query_id": result.query_id,
                        "has_error": result.has_error,
                        "num_output_rows": result.num_output_rows,
                        "start_unix_time": result.start_unix_time,
                        "stop_unix_time": result.stop_unix_time,
                    }
                    writer.writerow(row)
        self.logger.info(f"Concurrency benchmark results exported to {csv_file_path}")

    def run_benchmark(self):
        self.logger.info(f"Running concurrency benchmark for {self.vendor.upper()}...")
        self.start_barrier = threading.Barrier(self.concurrency)
        self.stop_event = threading.Event()
        self.worker_thread_results = [[] for _ in range(self.concurrency)]

        # Get random seeds for the worker threads (but seed the random seed generator with `self.seed` for reproducibility)
        rng = random.Random(self.seed)
        random_seeds = rng.sample(range(42_000_000), self.concurrency)

        # Start `self.concurrency` worker threads
        threads = []
        for i in range(self.concurrency):
            thread = threading.Thread(
                target=self._run_worker, args=(i, random_seeds[i])
            )
            threads.append(thread)
            thread.start()

        # Let the worker threads work for `self.benchmark_duration_secs` seconds
        time.sleep(self.benchmark_duration_secs)
        self.stop_event.set()

        # Wait for all worker threads to finish
        for thread in threads:
            thread.join()

        self._write_csv()
        self.logger.info(f"Finished concurrency benchmark for {self.vendor.upper()}...")
