from api.core.config import settings
from azure.identity import DefaultAzureCredential
from azure.monitor.opentelemetry import configure_azure_monitor
import logging

def configure_azure_app_insights():
    if settings.USE_APP_INSIGHTS and not settings.APP_INSIGHTS_CONNECTION_STRING:
        raise ValueError("APP_INSIGHTS_CONNECTION_STRING must be set if USE_APP_INSIGHTS is true")
    
    if settings.USE_APP_INSIGHTS and settings.APP_INSIGHTS_CONNECTION_STRING:
        credential = DefaultAzureCredential()
        configure_azure_monitor(connection_string=settings.APP_INSIGHTS_CONNECTION_STRING, credential=credential)
        # Suppress noisy Azure SDK internal logs from terminal and App Insights traces
        for noisy_logger in [
            "azure.core.pipeline.policies.http_logging_policy",
            "azure.monitor.opentelemetry.exporter",
        ]:
            logging.getLogger(noisy_logger).setLevel(logging.WARNING)
        print("📈 Application Insights enabled", flush=True)


def log_action(s, user=None):
    logger = logging.getLogger("actions_of_interest")
    logger.setLevel(logging.INFO)
    if user:
        extra = {"custom_dimensions": {"user": user.name}}
        logger.info(s, extra=extra)
    else:
        logger.info(s)