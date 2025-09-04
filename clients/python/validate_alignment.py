#!/usr/bin/env python3
"""
Comprehensive validation script to analyze query alignment across vendors
"""
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from runner import BenchmarkRunner

def validate_query_alignment():
    """Validate query alignment and show differences between vendors"""
    
    # Test parameters
    vendors = ["firebolt", "snowflake", "redshift"]
    benchmark_name = "FireScale"
    creds_file = str(Path(__file__).parent.parent.parent / "config" / "credentials" / "credentials.json")
    benchmark_path = str(Path(__file__).parent.parent.parent / "benchmarks" / benchmark_name)
    
    print("🔍 QUERY ALIGNMENT VALIDATION")
    print("=" * 80)
    print(f"Benchmark path: {benchmark_path}")
    print(f"Expected: 25 queries per vendor")
    print("=" * 80)
    
    # Store all queries by vendor
    all_vendor_queries = {}
    
    for vendor in vendors:
        print(f"\n📋 ANALYZING {vendor.upper()}")
        print("-" * 40)
        
        try:
            # Create a minimal runner just for query parsing
            runner = BenchmarkRunner(
                benchmark_name=benchmark_name,
                creds_file=creds_file,
                vendors=[vendor],
                pool_size=1,
                concurrency=1,
                benchmark_path=benchmark_path,
                logging_level="Information"  # Reduce noise
            )
            
            # Get the SQL file path
            sql_file = runner._get_sql_file(vendor, 'benchmark')
            print(f"SQL file: {sql_file}")
            
            # Parse queries
            queries = runner._load_queries(sql_file)
            all_vendor_queries[vendor] = queries
            
            print(f"✅ Queries found: {len(queries)}")
            if len(queries) != 25:
                print(f"⚠️  WARNING: Expected 25 queries but found {len(queries)}")
                
        except Exception as e:
            print(f"❌ Error analyzing {vendor}: {e}")
            all_vendor_queries[vendor] = []
    
    # Now compare queries across vendors
    print(f"\n🔍 CROSS-VENDOR COMPARISON")
    print("=" * 80)
    
    max_queries = 25
    for query_num in range(1, max_queries + 1):
        print(f"\n📌 QUERY {query_num}")
        print("-" * 30)
        
        query_samples = {}
        queries_identical = True
        base_query = None
        
        for vendor in vendors:
            if vendor in all_vendor_queries and len(all_vendor_queries[vendor]) >= query_num:
                query = all_vendor_queries[vendor][query_num - 1]  # 0-indexed
                query_samples[vendor] = query[:150] + ("..." if len(query) > 150 else "")
                
                if base_query is None:
                    base_query = query
                elif query != base_query:
                    queries_identical = False
            else:
                query_samples[vendor] = "❌ MISSING"
                queries_identical = False
        
        # Show status
        if queries_identical:
            print("✅ IDENTICAL across all vendors")
        else:
            print("⚠️  DIFFERENT (vendor-specific syntax - this is normal)")
        
        # Show samples
        for vendor, sample in query_samples.items():
            print(f"  {vendor:10}: {sample}")
    
    # Summary
    print(f"\n📊 SUMMARY")
    print("=" * 80)
    
    for vendor in vendors:
        count = len(all_vendor_queries.get(vendor, []))
        status = "✅" if count == 25 else "⚠️ "
        print(f"{vendor:10}: {status} {count:2d} queries")
    
    print("\n💡 EXPLANATION:")
    print("• Different queries between vendors is NORMAL and EXPECTED")
    print("• Each vendor uses database-specific SQL syntax (e.g., ARRAY_JOIN vs LISTAGG)")
    print("• The important thing is that each vendor has exactly 25 queries")
    print("• Query numbering should be consistent (Query 1 = Query 1, etc.)")
    print("• Only a few queries should be identical (like simple SELECT statements)")

if __name__ == "__main__":
    validate_query_alignment()
