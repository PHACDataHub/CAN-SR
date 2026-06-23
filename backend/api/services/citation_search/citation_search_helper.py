from __future__ import annotations

import logging
import os
from io import BytesIO
from io import StringIO
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import azure.functions as func
import pandas as pd
from azure.core.exceptions import AzureError
from azure.storage.blob import BlobServiceClient

from ...core.config import settings
from ...core.security import get_current_active_user
from ..storage import storage_service


def normalize_ids(df: pd.DataFrame):
    if 'pmid' in df.columns:
        df['id'] = df['pmid']
    elif 'eid' in df.columns:
        df['id'] = df['eid']
    elif 'id' not in df.columns:
        df['id'] = None
    return df


async def load_all_database_searches():
    base_path = 'citation-data/bronze-data'

    databases = ['Pubmed', 'EuropePMC', 'Scopus']
    dfs = []

    for database in databases:
        all_path = (
            f"{settings.STORAGE_CONTAINER_NAME}/"
            f"{base_path}/{database}/{database}-all-citations.csv"
        )

        try:
            bytes_data, _ = await storage_service.get_bytes_by_path(all_path)
            df = pd.read_csv(BytesIO(bytes_data))
            df['source'] = database
            dfs.append(df)
        except Exception as e:
            logging.warning(f"{database} missing: {e}")

    if not dfs:
        return pd.DataFrame()

    return pd.concat(dfs, ignore_index=True)


async def save_df(path: str, df: pd.DataFrame):
    buffer = BytesIO()
    df.to_csv(buffer, index=False, encoding='utf-8')
    buffer.seek(0)
    await storage_service.put_bytes_by_path(path, buffer.getvalue(), 'text/csv')
