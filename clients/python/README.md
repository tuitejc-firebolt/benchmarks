# Python Benchmark Client

This Python project provides a benchmarking tool for various data warehouse vendors, allowing users to compare performance across different systems. The tool supports multiple vendors, including Snowflake, Firebolt, Redshift, and BigQuery, and can execute custom SQL queries for benchmarking.

## Features

- Connect to multiple data warehouse vendors.
- Execute benchmark queries and collect results.
- Optionally execute a setup SQL file before running benchmarks.
- Easily configurable through command-line arguments.
- Supports both general SQL files for benchmarks and vendor-specific SQL files.

## Requirements

Make sure to install the required packages listed in `requirements.txt`.

```bash
pip install -r requirements.txt
```

If you have other Python-based projects, it's recommended to do this via
[venv](https://docs.python.org/3/library/venv.html) or [uv](https://github.com/astral-sh/uv).

## Usage

To run the benchmark, use the following command:

```bash
streamlit run /Users/jon.tuite/Firescale/benchmarks/clients/python/src/main.py
```
## Flexibility in SQL File Usage

This project allows for flexibility in how SQL files are used:

- **General SQL Files**: Each benchmark folder contains a general `benchmark.sql` and `setup.sql` file that can be used for all vendors. These files contain common queries that apply to all vendors.

- **Vendor-Specific SQL Files**: If a vendor has specific requirements or optimizations, you can create a `benchmark.sql` and `setup.sql` file within the vendor's folder. If these vendor-specific files exist, they will be used instead of the general files.

This structure allows you to easily manage and execute queries that are tailored to specific vendors while still providing a common set of queries for all vendors.
