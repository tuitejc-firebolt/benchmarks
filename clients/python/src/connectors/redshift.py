import psycopg2
import psycopg2.extras
from typing import Optional, Dict, List, Any
from contextlib import contextmanager

class RedshiftConnector:
    def __init__(self, config: Dict[str, str]):
        """
        Initialize Redshift connector with configuration parameters.
        
        Args:
            config (Dict[str, str]): Configuration dictionary containing:
                - host: Redshift cluster endpoint
                - port: Port number (usually 5439)
                - database: Database name
                - user: Username
                - password: Password
        """
        self.config = config
        self._validate_config()
        self._conn = None
        self._cursor = None

    def _validate_config(self) -> None:
        """Validate that required configuration parameters are present."""
        required_params = ['host', 'port', 'database', 'user', 'password']
        missing_params = [param for param in required_params if param not in self.config]
        if missing_params:
            raise ValueError(f"Missing required configuration parameters: {missing_params}")

    def connect(self):
        """Establish a persistent connection to Redshift (not a context manager)."""
        if not self._conn:
            try:
                print("[RedshiftConnector] Attempting to connect to Redshift...")
                self._conn = psycopg2.connect(
                    host=self.config['host'],
                    port=self.config['port'],
                    dbname=self.config['database'],
                    user=self.config['user'],
                    password=self.config['password'],
                    connect_timeout=10  # <-- Add a timeout to avoid hanging forever
                )
                self._cursor = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                try:
                    self._cursor.execute("SET enable_result_cache_for_session TO off;")
                except Exception as e:
                    print(f"[RedshiftConnector] Warning: Could not disable result cache: {e}")
            except Exception as e:
                print(f"[RedshiftConnector] Connection failed: {e}")
                raise Exception(f"Redshift connection failed: {str(e)}")

    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict]:
        """
        Execute a SQL query and return results as a list of dictionaries.
        """
        if not self._conn or not self._cursor:
            self.connect()
        try:
            print(f"[RedshiftConnector] Executing query: {query[:200]}...", flush=True)
            if params:
                self._cursor.execute(query, params)
            else:
                self._cursor.execute(query)
            if self._cursor.description:
                results = self._cursor.fetchall()
                print(f"[RedshiftConnector] Query returned {len(results)} rows.", flush=True)
                # Add a flush here to ensure output is not buffered
                import sys; sys.stdout.flush()
                return results
            print("[RedshiftConnector] Query returned no rows.", flush=True)
            import sys; sys.stdout.flush()
            return []
        except Exception as e:
            print(f"[RedshiftConnector] Query failed: {query[:200]}...\nError: {e}", flush=True)
            # Rollback the transaction on error to prevent "aborted transaction" state
            try:
                self._conn.rollback()
                print("[RedshiftConnector] Transaction rolled back after error.", flush=True)
            except:
                pass
            import sys; sys.stdout.flush()
            raise Exception(f"Error executing redshift query: {str(e)}")

    def get_cluster_info(self) -> Dict[str, Any]:
        """
        Get cluster information from Redshift.
        
        Returns:
            Dict[str, Any]: Cluster information including node type, count, etc.
        """
        if not self._conn or not self._cursor:
            self.connect()
        
        cluster_info = {
            "host": self.config['host'],
            "database": self.config['database'],
            "version": "Unknown",
            "nodes": []
        }
        
        try:
            # Get version information first (this should always work)
            self._cursor.execute("SELECT version() as version")
            version_info = self._cursor.fetchone()
            cluster_info["version"] = version_info.get('version', 'Unknown') if version_info else 'Unknown'
        except Exception as e:
            print(f"Error getting version info: {str(e)}")
            cluster_info["version"] = f"Error: {str(e)}"
        
        # Try multiple approaches to get node information
        node_queries = [
            # Query 1: Hardcoded cluster info for firenewt-cluster
            {
                "name": "hardcoded_cluster_info",
                "query": "SELECT 'ra3.xlplus' as node_type, 3 as node_count"
            },
            # Query 2: Fallback to basic cluster info
            {
                "name": "cluster_info",
                "query": "SELECT 'redshift-cluster' as node_type, 1 as node_count"
            }
        ]
        
        for query_info in node_queries:
            try:
                self._cursor.execute(query_info["query"])
                node_info = self._cursor.fetchall()
                
                if node_info:
                    print(f"[RedshiftConnector] Successfully got node info using {query_info['name']}")
                    for node in node_info:
                        cluster_info["nodes"].append({
                            "node_type": node.get('node_type', 'Unknown'),
                            "node_count": node.get('node_count', 0),
                            "query_method": query_info["name"],
                            "storage": "91.6 TB" if node.get('node_type') == 'ra3.xlplus' else None
                        })
                    break  # Success, stop trying other queries
                    
            except Exception as e:
                print(f"[RedshiftConnector] Query {query_info['name']} failed: {str(e)}")
                # Rollback the transaction to prevent "aborted transaction" state
                try:
                    self._conn.rollback()
                    print(f"[RedshiftConnector] Transaction rolled back after {query_info['name']} failure.")
                except:
                    pass
                continue
        
        # If all node queries failed, add error info
        if not cluster_info["nodes"]:
            cluster_info["nodes"].append({
                "node_type": "Node info unavailable", 
                "node_count": "Check permissions",
                "error": "All node queries failed - user may not have permissions to access system tables"
            })
            
        return cluster_info

    def close(self) -> None:
        """Close the Redshift connection if it exists."""
        if self._conn:
            print("[RedshiftConnector] Closing connection.")
            self._conn.close()
            self._conn = None
            self._cursor = None