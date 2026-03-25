from typing import Dict, Any, List, Optional
from ...core.security import get_current_active_user
from ...core.config import settings

import logging
import os
import pandas as pd
from io import StringIO, BytesIO
import azure.functions as func
from azure.core.exceptions import AzureError
from azure.storage.blob import BlobServiceClient
def azure_client(container_name: str):
    connection_string = settings.AZURE_STORAGE_CONNECTION_STRING
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    blob_client = blob_service_client.get_container_client(container_name)
    return blob_client
     

def read_blob_to_df(blob_name: str, container_name: str) -> pd.DataFrame:
    """Read a blob (Parquet or CSV) into a pandas DataFrame."""
    blob_client = azure_client(container_name).get_blob_client(blob_name)
    downloaded_blob = blob_client.download_blob().content_as_text()
    blob_df = pd.read_csv(StringIO(downloaded_blob), sep=",")
    return blob_df


def write_df_to_blob(df: pd.DataFrame, blob_name: str, container_name: str):
    """Write a pandas DataFrame to blob as Parquet."""
    buffer = BytesIO()
    df.to_csv(buffer, index=False, encoding='utf-8')
    buffer.seek(0)
    blob_client = azure_client(container_name).get_blob_client(blob_name)
    blob_client.upload_blob(buffer, overwrite=True)

def normalize_ids(df: pd.DataFrame):
    if "pmid" in df.columns:
        df["id"] = df["pmid"]
    elif "eid" in df.columns:
        df["id"] = df["eid"]
    elif "id" not in df.columns:
        df["id"] = None
    return df

def load_all_database_searches():
    base_path = "citation-data/bronze-data"

    databases = ["Pubmed", "EuropePMC", "Scopus"]
    dfs = []

    for database in databases:
        blob_name = f"{database}-all-citations.csv"
        container = f"{base_path}/{database}"

        try:
            df = read_blob_to_df(blob_name, container)
            df["source"] = database
            dfs.append(df)
        except Exception as e:
            logging.warning(f"{database} missing: {e}")

    if not dfs:
        return pd.DataFrame()

    return pd.concat(dfs, ignore_index=True)