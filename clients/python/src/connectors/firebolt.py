from typing import Dict, Any, Optional, List
from firebolt.db import connect
from firebolt.client.auth import ClientCredentials

class FireboltConnector:
    def __init__(self, config: Dict[str, str]):
        """
        Initialize Firebolt connector with configuration parameters.
        
        Args:
            config (Dict[str, str]): Configuration dictionary containing:
                - engine_name: Firebolt engine name
                - database: Database name
                - account_name: Account name
                - client_id: OAuth client ID
                - client_secret: OAuth client secret
        """
        self.config = config
        self._validate_config()
        self._conn = None
        self.cursor = None

    def _validate_config(self) -> None:
        """Validate that required configuration parameters are present."""
        required_params = ['engine_name', 'database', 'account_name', 'auth']
        missing_params = [param for param in required_params if param not in self.config]
        if missing_params:
            raise ValueError(f"Missing required configuration parameters: {missing_params}")

    def connect(self) -> None:
        """Connect to Firebolt using stored configuration."""
        if not self._conn:
            self._conn = connect(
                engine_name=self.config['engine_name'],
                database=self.config['database'],
                account_name=self.config['account_name'],
                auth=ClientCredentials(
                    self.config['auth']['id'],
                    self.config['auth']['secret']
                )
            )
            self.cursor = self._conn.cursor()
            self.cursor.execute("SET enable_result_cache=false")

    def execute_query(self, query: str, parameters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Execute a query on Firebolt.
        
        Args:
            query (str): SQL query to execute
            parameters (Optional[Dict[str, Any]]): Query parameters
            
        Returns:
            List[Dict[str, Any]]: Query results
        """
        if not self._conn or not self.cursor:
            self.connect()

        try:
            if parameters:
                self.cursor.execute(query, parameters)
            else:
                self.cursor.execute(query)
            
            if self.cursor.description:  # If the query returns results
                results = self.cursor.fetchall()
                if results:
                    # Convert tuples to dictionaries using column names
                    column_names = [desc[0] for desc in self.cursor.description]
                    return [dict(zip(column_names, row)) if isinstance(row, (list, tuple)) else row for row in results]
                return []
            return []
            
        except Exception as e:
            raise Exception(f"Error executing query: {str(e)}")

    def get_cluster_info(self) -> Dict[str, Any]:
        """
        Get cluster information from Firebolt.
        
        Returns:
            Dict[str, Any]: Cluster information including size, nodes, etc.
        """
        if not self._conn or not self.cursor:
            self.connect()
        
        try:
            # First try to get engine information from information_schema
            try:
                self.cursor.execute("SELECT * FROM information_schema.engines WHERE engine_name = %s", (self.config['engine_name'],))
                engine_info = self.cursor.fetchone()
                
                if engine_info:
                    # Get column names from cursor description
                    column_names = [desc[0] for desc in self.cursor.description]
                    # Convert tuple/list to dictionary
                    engine_dict = dict(zip(column_names, engine_info)) if isinstance(engine_info, (list, tuple)) else engine_info
                    
                    return {
                        "engine_name": engine_dict.get('engine_name', self.config['engine_name']),
                        "type": engine_dict.get('type', 'Unknown'),
                        "family": engine_dict.get('family', 'Unknown'),
                        "nodes": engine_dict.get('nodes', 'Unknown'),
                        "clusters": engine_dict.get('clusters', 'Unknown'),
                        "status": engine_dict.get('status', 'Unknown'),
                        "version": engine_dict.get('version', 'Unknown'),
                        "fbu_rate": str(engine_dict.get('fbu_rate', 'Unknown')),
                        "auto_start": engine_dict.get('auto_start', 'Unknown'),
                        "auto_stop": engine_dict.get('auto_stop', 'Unknown')
                    }
            except Exception as schema_error:
                print(f"information_schema.engines query failed: {schema_error}")
                
            # Fallback: try alternative queries to get engine info
            try:
                # Try SHOW ENGINES command
                self.cursor.execute("SHOW ENGINES")
                engines = self.cursor.fetchall()
                
                if engines:
                    # Get column names from cursor description
                    column_names = [desc[0] for desc in self.cursor.description]
                    
                    for engine_row in engines:
                        # Convert tuple/list to dictionary
                        engine_dict = dict(zip(column_names, engine_row)) if isinstance(engine_row, (list, tuple)) else engine_row
                        
                        engine_name_field = engine_dict.get('engine_name') or engine_dict.get('name')
                        if engine_name_field == self.config['engine_name']:
                            return {
                                "engine_name": engine_name_field,
                                "type": engine_dict.get('type', 'Unknown'),
                                "family": engine_dict.get('family', 'Unknown'),
                                "nodes": engine_dict.get('nodes', 'Unknown'),
                                "clusters": engine_dict.get('clusters', 'Unknown'),
                                "status": engine_dict.get('status', 'Unknown'),
                                "version": engine_dict.get('version', 'Unknown'),
                                "fbu_rate": str(engine_dict.get('fbu_rate', 'Unknown')),
                                "auto_start": engine_dict.get('auto_start', 'Unknown'),
                                "auto_stop": engine_dict.get('auto_stop', 'Unknown')
                            }
                            
            except Exception as show_error:
                print(f"SHOW ENGINES query failed: {show_error}")
            
            # Final fallback - just return basic info
            return {
                "engine_name": self.config['engine_name'],
                "type": "Information not available",
                "family": "Information not available",
                "nodes": "Information not available",
                "clusters": "Information not available",
                "status": "Information not available",
                "version": "Information not available",
                "fbu_rate": "Information not available",
                "auto_start": "Information not available",
                "auto_stop": "Information not available"
            }
                
        except Exception as e:
            error_msg = f"Error getting cluster info: {str(e)}"
            print(error_msg)
            return {
                "engine_name": self.config['engine_name'],
                "type": f"Error: {str(e)}",
                "family": f"Error: {str(e)}",
                "nodes": f"Error: {str(e)}",
                "clusters": f"Error: {str(e)}",
                "status": f"Error: {str(e)}",
                "version": f"Error: {str(e)}",
                "fbu_rate": f"Error: {str(e)}",
                "auto_start": f"Error: {str(e)}",
                "auto_stop": f"Error: {str(e)}"
            }

    def close(self) -> None:
        """Close the Firebolt connection if it exists."""
        if self._conn:
            self._conn.close()
            self._conn = None
            self.cursor = None
