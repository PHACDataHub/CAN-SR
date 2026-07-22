from __future__ import annotations

import pytest
from api.screen.prompts import PROMPT_XML_TEMPLATE_FULLTEXT_CRITICAL
from api.screen.prompts import PROMPT_XML_TEMPLATE_TA_CRITICAL
from api.services.azure_openai_client import AzureOpenAIClient
from api.services.azure_openai_client import DeploymentRateLimiter


def _client() -> AzureOpenAIClient:
    client = AzureOpenAIClient.__new__(AzureOpenAIClient)
    client._endpoint = 'https://example.openai.azure.com'
    client._rate_limiters = {}
    client.model_configs = {}
    return client


def test_model_catalog_loads_per_model_rate_limits():
    client = _client()

    configs = client._load_model_configs({
        'models': {
            'Fast': {
                'deployment': 'fast',
                'api_version': '2025-04-01-preview',
                'requests_per_minute': 1000,
                'tokens_per_minute': 1_000_000,
            },
        },
    })

    assert configs['Fast']['requests_per_minute'] == 1000
    assert configs['Fast']['tokens_per_minute'] == 1_000_000


def test_limiters_are_isolated_by_deployment():
    client = _client()
    client.model_configs = {
        'A': {'deployment': 'a', 'requests_per_minute': 1, 'tokens_per_minute': 10},
        'B': {'deployment': 'b', 'requests_per_minute': 2, 'tokens_per_minute': 20},
    }

    a = client._get_rate_limiter('a')
    b = client._get_rate_limiter('b')

    assert isinstance(a, DeploymentRateLimiter)
    assert isinstance(b, DeploymentRateLimiter)
    assert a is not b
    assert a.requests_per_minute == 1
    assert b.tokens_per_minute == 20


def test_request_token_estimate_includes_maximum_output_and_images():
    estimate = AzureOpenAIClient._estimate_request_tokens({
        'messages': [{
            'content': [
                {'type': 'text', 'text': 'abcdefgh'},
                {
                    'type': 'image_url', 'image_url': {
                        'url': 'data:image/png;base64,...',
                    },
                },
            ],
        }],
        'max_completion_tokens': 100,
    })

    assert estimate == 1102


def test_retry_after_supports_azure_millisecond_header():
    error = RuntimeError('rate limit exceeded')
    error.status_code = 429
    error.headers = {'retry-after-ms': '250'}

    assert AzureOpenAIClient._retry_after_seconds(error) == 0.25


@pytest.mark.parametrize(
    'prompt',
    [PROMPT_XML_TEMPLATE_TA_CRITICAL, PROMPT_XML_TEMPLATE_FULLTEXT_CRITICAL],
)
def test_critical_prompt_defines_agreement_and_disagreement(prompt: str):
    assert 'AGREEMENT means the original answer is the best-supported answer' in prompt
    assert 'DISAGREEMENT means one of the listed alternatives is better supported' in prompt
    assert 'confidence in this agreement/disagreement judgment' in prompt
