import snowflake.connector
from typing import Optional, Dict, List, Any

class SnowflakeConnector:
    def __init__(self, config: Dict[str, str]):
        """
        Initialize Snowflake connector with configuration parameters.
        """
        self.config = config
        self._validate_config()
        self._conn = None
        self._cursor = None

    def _validate_config(self) -> None:
        required_params = ['account', 'user', 'password']
        missing_params = [param for param in required_params if param not in self.config]
        if missing_params:
            raise ValueError(f"Missing required configuration parameters: {missing_params}")

    def connect(self):
        """Establish a persistent connection to Snowflake (not a context manager)."""
        if not self._conn:
            try:
                print("[SnowflakeConnector] Attempting to connect to Snowflake...", flush=True)
                self._conn = snowflake.connector.connect(
                    account=self.config['account'],
                    user=self.config['user'],
                    password=self.config['password'],
                    warehouse=self.config.get('warehouse'),
                    database=self.config.get('database'),
                    schema=self.config.get('schema'),
                    telemetry=False
                )
                self._cursor = self._conn.cursor(snowflake.connector.DictCursor)
                try:
                    self._cursor.execute("ALTER SESSION SET USE_CACHED_RESULT = FALSE;")
                except Exception as e:
                    print(f"[SnowflakeConnector] Warning: Could not disable result cache: {e}", flush=True)
            except Exception as e:
                print(f"[SnowflakeConnector] Connection failed: {e}", flush=True)
                raise Exception(f"Snowflake connection failed: {str(e)}")

    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict]:
        """
        Execute a SQL query and return results as a list of dictionaries.
        """
        if not self._conn or not self._cursor:
            self.connect()
        try:
            print(f"[SnowflakeConnector] Executing query: {query[:200]}...", flush=True)
            if params:
                self._cursor.execute(query, params)
            else:
                self._cursor.execute(query)
            if self._cursor.description:
                results = self._cursor.fetchall()
                print(f"[SnowflakeConnector] Query returned {len(results)} rows.", flush=True)
                import sys; sys.stdout.flush()
                return results
            print("[SnowflakeConnector] Query returned no rows.", flush=True)
            import sys; sys.stdout.flush()
            return []
        except Exception as e:
            print(f"[SnowflakeConnector] Query failed: {query[:200]}...\nError: {e}", flush=True)
            import sys; sys.stdout.flush()
            raise Exception(f"Error executing snowflake query: {str(e)}")

    def get_cluster_info(self) -> Dict[str, Any]:
        """
        Get warehouse information from Snowflake.
        
        Returns:
            Dict[str, Any]: Warehouse information including size, status, etc.
        """
        if not self._conn or not self._cursor:
            self.connect()
        
        try:
            warehouse_name = self.config.get('warehouse', 'Unknown')
            
            # Get warehouse information
            self._cursor.execute("SHOW WAREHOUSES LIKE %s", (warehouse_name,))
            warehouse_info = self._cursor.fetchone()
            
            if warehouse_info:
                return {
                    "warehouse_name": warehouse_info.get('name', warehouse_name),
                    "size": warehouse_info.get('size', 'Unknown'),
                    "state": warehouse_info.get('state', 'Unknown'),
                    "type": warehouse_info.get('type', 'Unknown'),
                    "min_cluster_count": warehouse_info.get('min_cluster_count', 'Unknown'),
                    "max_cluster_count": warehouse_info.get('max_cluster_count', 'Unknown')
                }
            else:
                return {
                    "warehouse_name": warehouse_name,
                    "size": "Unknown",
                    "state": "Unknown",
                    "type": "Unknown",
                    "min_cluster_count": "Unknown", 
                    "max_cluster_count": "Unknown"
                }
        except Exception as e:
            print(f"Error getting warehouse info: {str(e)}")
            return {
                "warehouse_name": self.config.get('warehouse', 'Unknown'),
                "size": "Error retrieving info",
                "state": "Error retrieving info",
                "type": "Error retrieving info",
                "min_cluster_count": "Error retrieving info",
                "max_cluster_count": "Error retrieving info"
            }

    def close(self) -> None:
        """Close the Snowflake connection if it exists."""
        if self._conn:
            print("[SnowflakeConnector] Closing connection.", flush=True)
            self._conn.close()
            self._conn = None
            self._cursor = None
