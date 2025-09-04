from google.cloud import bigquery
from google.oauth2 import service_account
from typing import Optional, Dict, List, Any

class BigQueryConnector:
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize BigQuery connector with configuration parameters.
        """
        self.config = config
        self._validate_config()
        self._client = None
        self._init_client()

    def _validate_config(self) -> None:
        required_params = ['project_id', 'key']
        missing_params = [param for param in required_params if param not in self.config]
        if missing_params:
            raise ValueError(f"Missing required configuration parameters: {missing_params}")

    def _init_client(self) -> None:
        project_id = self.config['project_id']
        dataset_id = self.config.get('dataset')
        credentials = service_account.Credentials.from_service_account_info(self.config['key'])
        default_config = None
        if dataset_id:
            default_config = bigquery.QueryJobConfig(default_dataset=f"{project_id}.{dataset_id}")
        self._client = bigquery.Client(
            project=project_id,
            credentials=credentials,
            default_query_job_config=default_config,
            location=self.config.get('location')
        )
        print("[BigQueryConnector] Connected to BigQuery.", flush=True)

    def connect(self) -> None:
        """Establish a connection to BigQuery."""
        if not self._client:
            self._init_client()

    def execute_query(
        self, 
        query: str, 
        params: Optional[Dict[str, Any]] = None,
        dry_run: bool = False
    ) -> List[Dict]:
        """
        Execute a SQL query and return results as a list of dictionaries.
        """
        print(f"[BigQueryConnector] Executing query: {query[:200]}...", flush=True)
        job_config = bigquery.QueryJobConfig(
            use_query_cache=False,
            dry_run=dry_run
        )

        if params:
            job_config.query_parameters = [
                bigquery.ScalarQueryParameter(k, self._get_param_type(v), v)
                for k, v in params.items()
            ]

        query_job = self._client.query(query, job_config=job_config)
        
        if dry_run:
            print(f"[BigQueryConnector] Dry run: {query_job.total_bytes_processed} bytes processed.", flush=True)
            return [{'bytes_processed': query_job.total_bytes_processed}]

        results = [dict(row.items()) for row in query_job]
        print(f"[BigQueryConnector] Query returned {len(results)} rows.", flush=True)
        return results

    def _get_param_type(self, value: Any) -> str:
        type_map = {
            str: 'STRING',
            int: 'INT64',
            float: 'FLOAT64',
            bool: 'BOOL',
            dict: 'RECORD',
            list: 'ARRAY'
        }
        return type_map.get(type(value), 'STRING')
    
    def get_cluster_info(self) -> Dict[str, Any]:
        """
        Get project and dataset information from BigQuery.
        
        Returns:
            Dict[str, Any]: Project and dataset information
        """
        try:
            project_id = self.config['project_id']
            dataset_id = self.config.get('dataset', 'Unknown')
            location = self.config.get('location', 'Unknown')
            
            # Get project information 
            project = self._client.get_project(project_id)
            
            cluster_info = {
                "project_id": project_id,
                "project_name": project.friendly_name or project_id,
                "dataset": dataset_id,
                "location": location,
                "default_table_expiration": "Unknown"
            }
            
            # Try to get dataset information if dataset is specified
            if dataset_id and dataset_id != 'Unknown':
                try:
                    dataset_ref = self._client.dataset(dataset_id)
                    dataset = self._client.get_dataset(dataset_ref)
                    cluster_info["dataset_location"] = dataset.location
                    cluster_info["default_table_expiration"] = str(dataset.default_table_expiration_ms) if dataset.default_table_expiration_ms else "None"
                except Exception as e:
                    print(f"Could not get dataset info: {e}")
            
            return cluster_info
            
        except Exception as e:
            print(f"Error getting cluster info: {str(e)}")
            return {
                "project_id": self.config.get('project_id', 'Unknown'),
                "project_name": "Error retrieving info",
                "dataset": self.config.get('dataset', 'Unknown'),
                "location": self.config.get('location', 'Unknown'),
                "default_table_expiration": "Error retrieving info"
            }
    
    def close(self) -> None:
        """Close the BigQuery connection if it exists."""
        if self._client:
            print("[BigQueryConnector] Closing connection.", flush=True)
            self._client.close()
            self._client = None