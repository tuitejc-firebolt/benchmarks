# Firebolt Benchmarking Tool - Installation Guide

This guide will help you install and run the Firebolt Benchmarking Tool on a fresh computer.

## 📋 Prerequisites

### System Requirements
- **Operating System**: macOS, Linux, or Windows
- **Python**: Version 3.8 or higher
- **Memory**: At least 4GB RAM recommended
- **Network**: Internet connection for package installation and database access

### Required Accounts & Access
- **Database Access**: Credentials for at least one of:
  - Firebolt account with engine access
  - AWS Redshift cluster access
  - Snowflake warehouse access
  - Google BigQuery project access

## 🛠️ Installation Steps

### 1. Clone the Repository
```bash
git clone https://github.com/tuitejc-firebolt/benchmarks.git
cd benchmarks
```

### 2. Set Up Python Environment

#### Option A: Using conda (Recommended)
```bash
# Create a new conda environment
conda create -n firebolt-benchmark python=3.11
conda activate firebolt-benchmark
```

#### Option B: Using venv
```bash
# Create a virtual environment
python -m venv venv

# Activate it
# On macOS/Linux:
source venv/bin/activate
# On Windows:
venv\Scripts\activate
```

### 3. Install Dependencies
```bash
cd benchmarks/clients/python
pip install -r requirements.txt
```

### 4. Configure Database Credentials

#### Create Credentials File
```bash
# Copy the sample credentials file
cp ../../../config/credentials/sample_credentials.json ../../../config/credentials/credentials.json
```

#### Edit Credentials File
Open `config/credentials/credentials.json` and configure your database connections:

```json
{
  "firebolt": {
    "engine_name": "your-engine-name",
    "database": "your-database-name",
    "username": "your-username", 
    "password": "your-password",
    "account": "your-account-name"
  },
  "redshift": {
    "host": "your-cluster.region.redshift.amazonaws.com",
    "port": "5439",
    "database": "your-database",
    "user": "your-username",
    "password": "your-password"
  },
  "snowflake": {
    "account": "your-account.region",
    "user": "your-username",
    "password": "your-password", 
    "warehouse": "your-warehouse",
    "database": "your-database",
    "schema": "public"
  },
  "google": {
    "project_id": "your-project-id",
    "dataset": "your-dataset",
    "credentials_path": "path/to/service-account.json"
  }
}
```

### 5. Set Up Test Data (Required)

#### For Firebolt:
1. Ensure your Firebolt engine is running
2. Run the setup script to create tables and load data:
```bash
# The setup script will be run automatically, but you can also run it manually
# Connect to your Firebolt database and execute:
# benchmarks/FireScale/firebolt/setup.sql
```

#### For Redshift:
1. Ensure your cluster is running and accessible
2. Run the setup script to create tables and load data:
```bash
# Connect to your Redshift cluster and execute:
# benchmarks/FireScale/redshift/setup.sql
```

#### For Snowflake:
1. Ensure your warehouse is running
2. Run the setup script:
```bash
# Connect to Snowflake and execute:
# benchmarks/FireScale/snowflake/setup.sql
```

## 🚀 Running the Application

### 1. Start the Streamlit Application
```bash
cd benchmarks/clients/python/src
streamlit run main.py
```

### 2. Access the Web Interface
- The application will automatically open in your default browser
- If not, navigate to: `http://localhost:8501`

### 3. Configure Your Benchmark

#### In the Sidebar:
1. **Benchmark Name**: Leave as "FireScale" (default)
2. **Credentials File**: Should auto-populate with the correct path
3. **Vendors**: Select which databases you want to benchmark (e.g., "firebolt", "redshift")
4. **Query Set Runs**: Number of times to run the full query set (default: 1)
5. **Concurrent Queries**: Number of parallel query executions (default: 1)
6. **Logging Level**: 
   - "Information" for normal operation
   - "Debug" for troubleshooting

#### Check Cluster Information:
- The app will automatically connect and display cluster information
- Verify you see "✅ Connected" for your selected vendors
- Check that cost estimates look reasonable

### 4. Run Your First Benchmark
1. Click "▶️ Run Benchmark" in the sidebar
2. Monitor progress in real-time
3. View results in charts and tables as they populate

## 🔍 Troubleshooting

### Common Issues

#### 1. Connection Errors
```
❌ Failed to get cluster info: connection failed
```
**Solutions:**
- Verify credentials in `credentials.json`
- Check network connectivity to database
- Ensure database/engine is running
- For Firebolt: Verify engine is started and accessible

#### 2. Permission Errors
```
❌ Error: permission denied for table
```
**Solutions:**
- Verify your user has SELECT permissions on required tables
- For Redshift: User needs access to system tables
- Run setup scripts to create required tables and data

#### 3. Missing Dependencies
```
ModuleNotFoundError: No module named 'streamlit'
```
**Solutions:**
- Ensure virtual environment is activated
- Re-run: `pip install -r requirements.txt`
- Check Python version: `python --version`

#### 4. Data Loading Issues
```
Query returned 0 rows
```
**Solutions:**
- Run the setup scripts for your database
- Verify test data was loaded correctly
- Check table permissions

### Debug Mode
Enable Debug mode in the sidebar for additional troubleshooting tools:
- **Test Firebolt Queries**: Test basic Firebolt connectivity
- **Check Table Row Counts**: Verify data is loaded
- **Test Redshift System Tables**: Check Redshift permissions

## 📊 Understanding Results

### Key Metrics
- **Max/Min/Avg Response Time**: Query performance statistics
- **Total Time**: Sum of all query durations per vendor
- **Cost Analysis**: Estimated costs based on actual compute time
- **Query Duration Chart**: Performance comparison across 25 queries

### Cost Calculations
- **Firebolt**: Based on FBU rate × actual query time
- **Redshift**: Based on node type/count × actual query time  
- **Snowflake**: Based on warehouse size × actual query time
- **BigQuery**: Based on slot usage × actual query time

## 🔧 Advanced Configuration

### Custom Benchmarks
To create custom benchmark suites:
1. Create a new folder under `benchmarks/`
2. Add SQL files for each vendor
3. Update the benchmark name in the UI

### Performance Tuning
- **Concurrent Queries**: Increase for higher throughput testing
- **Query Set Runs**: Run multiple iterations for statistical significance
- **Pool Size**: Control total workload volume

### Database-Specific Notes

#### Firebolt
- Requires engine to be started before benchmarking
- FBU rates are automatically detected
- Supports advanced aggregating indexes

#### Redshift  
- Cost calculation uses hardcoded cluster info (ra3.xlplus × 3 nodes)
- Disable result caching for accurate timing
- May require VPC access depending on cluster configuration

#### Snowflake
- Warehouse auto-suspend may affect first query timing
- Credit costs vary by region and edition
- Multi-cluster warehouses supported

## 🆘 Getting Help

### Log Files
- Streamlit logs appear in the terminal
- Database connection details logged with Debug mode
- Query execution times logged for analysis

### Support Channels
- Check GitHub Issues for common problems
- Review database vendor documentation for connection setup
- Verify firewall/network settings for database access

### Useful Commands
```bash
# Check Python environment
python --version
pip list

# Test database connectivity (outside the app)
python -c "import psycopg2; print('PostgreSQL driver OK')"  # For Redshift
python -c "import snowflake.connector; print('Snowflake driver OK')"

# Restart Streamlit with verbose logging
streamlit run main.py --logger.level=debug
```

## 🎯 Quick Start Checklist

- [ ] Python 3.8+ installed
- [ ] Repository cloned
- [ ] Virtual environment created and activated  
- [ ] Dependencies installed (`pip install -r requirements.txt`)
- [ ] Credentials configured in `credentials.json`
- [ ] Database setup scripts executed
- [ ] Test data loaded and verified
- [ ] Streamlit application started (`streamlit run main.py`)
- [ ] Cluster connections verified (✅ Connected)
- [ ] First benchmark run successfully

Once you complete this checklist, you'll be ready to run comprehensive database performance benchmarks!
