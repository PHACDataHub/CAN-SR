"""backend.api.services.azure_openai_client

Azure OpenAI client service for chat completions.

Supports:
* API key auth (AZURE_OPENAI_MODE=key)
* Entra/managed identity auth (AZURE_OPENAI_MODE=entra)

Model catalog:
Loaded from YAML at runtime:
  /app/configs/models.yaml

The YAML is a mapping of UI/display keys to {deployment, api_version}, e.g.:

GPT-5-Mini:
  deployment: gpt-5-mini
  api_version: 2025-04-01-preview

DEFAULT_CHAT_MODEL must be one of those keys.
"""
from __future__ import annotations

import asyncio
import base64
from collections import deque
import json
import logging
import re
import time
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import yaml
from azure.identity import DefaultAzureCredential
from azure.identity import get_bearer_token_provider
from openai import AzureOpenAI

# Async client exists in modern openai SDKs (v1+ / v2+). If unavailable, we
# will safely offload sync calls to a threadpool to avoid blocking the event loop.
try:  # pragma: no cover
    from openai import AsyncAzureOpenAI  # type: ignore
except Exception:  # pragma: no cover
    AsyncAzureOpenAI = None  # type: ignore

from fastapi.concurrency import run_in_threadpool

from ..core.config import settings

logger = logging.getLogger(__name__)

# Token cache TTL in seconds (9 minutes)
TOKEN_CACHE_TTL = 9 * 60


class DeploymentRateLimiter:
    """In-process rolling-window limiter for one Azure deployment."""

    def __init__(self, requests_per_minute: int, tokens_per_minute: int):
        self.requests_per_minute = max(0, int(requests_per_minute))
        self.tokens_per_minute = max(0, int(tokens_per_minute))
        self._requests: deque[float] = deque()
        self._tokens: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, estimated_tokens: int) -> None:
        """Wait until both configured budgets have room, then reserve them."""
        estimated_tokens = max(1, int(estimated_tokens))
        while True:
            async with self._lock:
                now = time.monotonic()
                cutoff = now - 60.0
                while self._requests and self._requests[0] <= cutoff:
                    self._requests.popleft()
                while self._tokens and self._tokens[0][0] <= cutoff:
                    self._tokens.popleft()

                request_ok = (
                    self.requests_per_minute <= 0
                    or len(self._requests) < self.requests_per_minute
                )
                used_tokens = sum(tokens for _, tokens in self._tokens)
                token_ok = (
                    self.tokens_per_minute <= 0
                    or used_tokens + estimated_tokens <= self.tokens_per_minute
                )
                # A single oversized request must be allowed eventually rather than
                # waiting forever. It consumes the whole token window by itself.
                if (
                    self.tokens_per_minute > 0
                    and estimated_tokens > self.tokens_per_minute
                ):
                    token_ok = not self._tokens

                if request_ok and token_ok:
                    self._requests.append(now)
                    self._tokens.append((now, estimated_tokens))
                    return

                waits: list[float] = []
                if not request_ok and self._requests:
                    waits.append(self._requests[0] + 60.0 - now)
                if not token_ok and self._tokens:
                    waits.append(self._tokens[0][0] + 60.0 - now)
                delay = max(0.01, min(waits) if waits else 0.1)
            await asyncio.sleep(delay)


class CachedTokenProvider:
    """Simple in-memory token cache wrapper"""

    def __init__(self, token_provider):
        self._token_provider = token_provider
        self._cached_token: str | None = None
        self._token_expiry: float = 0

    def __call__(self) -> str:
        """Return cached token or fetch a new one if expired"""
        current_time = time.time()
        if self._cached_token is None or current_time >= self._token_expiry:
            self._cached_token = self._token_provider()
            self._token_expiry = current_time + TOKEN_CACHE_TTL
        return self._cached_token


class AzureOpenAIClient:
    """Client for Azure OpenAI chat completions"""

    def __init__(self):
        self._config_error: str | None = None
        self.default_model = settings.DEFAULT_CHAT_MODEL

        self._auth_type = self._resolve_auth_type()
        self._endpoint = self._resolve_endpoint()
        self._api_key = settings.AZURE_OPENAI_API_KEY

        self._token_provider: CachedTokenProvider | None = None
        if self._auth_type == 'entra':
            if not DefaultAzureCredential or not get_bearer_token_provider:
                self._config_error = (
                    'AZURE_OPENAI_MODE=entra requires azure-identity to be installed'
                )
            else:
                # Create token provider for Azure OpenAI using DefaultAzureCredential
                # Wrapped with caching to avoid fetching a new token on every request
                credential = DefaultAzureCredential()
                self._token_provider = CachedTokenProvider(
                    get_bearer_token_provider(
                        credential, 'https://cognitiveservices.azure.com/.default',
                    ),
                )

        self._disabled_deployments: set[str] = set()

        self._models_yaml = self._load_models_yaml()
        self._catalog_default_model = self._load_catalog_default_model(
            self._models_yaml,
        )
        self.model_configs = self._load_model_configs(self._models_yaml)
        self.default_model = self._resolve_default_model(self.default_model)
        self._rate_limiters: dict[str, DeploymentRateLimiter] = {}

        # Cache official clients by (endpoint, api_version, auth_type)
        self._official_clients: dict[tuple[str, str, str], AzureOpenAI] = {}
        self._official_async_clients: dict[tuple[str, str, str], Any] = {}

    # ---------------------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------------------

    @staticmethod
    def _resolve_auth_type() -> str:
        """Return key|entra.

        New config: AZURE_OPENAI_MODE
        Legacy config: USE_ENTRA_AUTH
        """
        t = (getattr(settings, 'AZURE_OPENAI_MODE', None) or '').lower().strip()
        if t in {'key', 'entra'}:
            return t
        # Legacy fallback
        if getattr(settings, 'USE_ENTRA_AUTH', False):
            return 'entra'
        return 'key'

    @staticmethod
    def _resolve_endpoint() -> str | None:
        return settings.AZURE_OPENAI_ENDPOINT

    def _strip_outer_quotes(self, s: str) -> str:
        s = s.strip()
        if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
            return s[1:-1]
        return s

    def _load_models_yaml(self) -> dict[str, Any]:
        """Load model catalog from /app/configs/models.yaml.

        This file is expected to be mounted in docker-compose so changes can be
        applied without rebuilding the image.
        """
        path = Path('configs/models.yaml')
        if not path.exists():
            logger.warning('Azure OpenAI model catalog not found at %s', path)
            return {}
        try:
            data = yaml.safe_load(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                logger.warning(
                    'Invalid models.yaml format (expected mapping): %s', type(
                        data,
                    ),
                )
                return {}
            return data
        except Exception as e:
            logger.exception(
                'Failed to load Azure OpenAI model catalog from %s: %s', path, e,
            )
            return {}

    def _load_catalog_default_model(self, data: dict[str, Any]) -> str | None:
        """Return the configured default model key from models.yaml if present."""
        value = data.get('default_model') if isinstance(data, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _extract_models_mapping(self, data: dict[str, Any]) -> dict[str, Any]:
        """Support both legacy flat YAML and structured YAML with `models:`."""
        if not isinstance(data, dict):
            return {}
        models = data.get('models')
        if isinstance(models, dict):
            return models
        return data

    def _load_model_configs(
        self,
        data: dict[str, Any] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Build model configs keyed by UI/display name."""
        models = self._extract_models_mapping(data or {})
        cfg: dict[str, dict[str, Any]] = {}
        for display_name, meta in models.items():
            if not isinstance(meta, dict):
                continue
            deployment = meta.get('deployment')
            api_version = meta.get('api_version')
            if not deployment or not api_version:
                continue
            try:
                requests_per_minute = max(
                    0, int(meta.get('requests_per_minute', 0) or 0),
                )
                tokens_per_minute = max(
                    0, int(meta.get('tokens_per_minute', 0) or 0),
                )
            except (TypeError, ValueError):
                logger.warning(
                    'Ignoring invalid rate limits for model %s', display_name,
                )
                requests_per_minute = 0
                tokens_per_minute = 0
            cfg[str(display_name)] = {
                'endpoint': self._endpoint or '',
                'deployment': str(deployment),
                'api_version': str(api_version),
                'requests_per_minute': requests_per_minute,
                'tokens_per_minute': tokens_per_minute,
            }

        if cfg:
            return cfg

        return {}

    def _resolve_default_model(self, desired: str) -> str:
        yaml_default = (self._catalog_default_model or '').strip()
        desired = (yaml_default or desired or '').strip()
        desired_l = desired.lower()

        if (
            desired in self.model_configs
            and self._is_model_config_available(self.model_configs[desired])
        ):
            return desired

        for key, cfg in self._iter_available_model_configs():
            if str(key).lower() == desired_l and desired_l:
                return str(key)
            if str(cfg.get('deployment') or '').lower() == desired_l and desired_l:
                return str(key)

        # If configured default doesn't exist, fall back to first configured model
        for k, _cfg in self._iter_available_model_configs():
            return k
        return desired

    def _is_model_config_available(self, config: dict[str, str] | None) -> bool:
        if not config:
            return False
        endpoint = str(config.get('endpoint') or '').strip()
        deployment = str(config.get('deployment') or '').strip()
        api_version = str(config.get('api_version') or '').strip()
        if not endpoint or not deployment or not api_version:
            return False
        if deployment in self._disabled_deployments:
            return False
        return True

    def _iter_available_model_configs(self):
        for model, config in self.model_configs.items():
            if not self._is_model_config_available(config):
                continue
            yield model, config

    def _get_model_config(self, model: str) -> dict[str, str]:
        """Get configuration for a specific model.

        IMPORTANT:
        - `model` is the *UI/display key* in models.yaml (e.g. "GPT-5-Mini").
        - Some callers historically pass the *deployment* name (e.g. "gpt-5-mini").
        - We normalize to support both without silently falling back.
        """

        # Exact match on display key
        if model in self.model_configs and self._is_model_config_available(self.model_configs[model]):
            return self.model_configs[model]

        desired = (model or '').strip()
        desired_l = desired.lower()

        # Case-insensitive match on display key
        for k, cfg in self.model_configs.items():
            if not self._is_model_config_available(cfg):
                continue
            if str(k).lower() == desired_l and desired_l:
                return cfg

        # Match by deployment name (common when UI stores deployment id)
        for _k, cfg in self.model_configs.items():
            if not self._is_model_config_available(cfg):
                continue
            if str(cfg.get('deployment') or '').lower() == desired_l and desired_l:
                return cfg

        # fallback to first configured model
        for _, cfg in self._iter_available_model_configs():
            return cfg
        raise ValueError('No Azure OpenAI models are configured')

    def normalize_model_key(self, model: str | None) -> str | None:
        """Return the canonical models.yaml display key for a given input.

        Accepts either:
        - display key (e.g. "GPT-5-Mini")
        - deployment id (e.g. "gpt-5-mini")
        """
        if not model:
            return None
        desired = str(model).strip()
        desired_l = desired.lower()

        if desired in self.model_configs:
            return desired

        for k in self.model_configs.keys():
            if str(k).lower() == desired_l:
                return str(k)

        for k, cfg in self.model_configs.items():
            if str(cfg.get('deployment') or '').lower() == desired_l:
                return str(k)

        return desired

    def _get_official_client(self, model: str) -> AzureOpenAI:
        """Get official Azure OpenAI client instance"""
        config = self._get_model_config(model)
        endpoint = config.get('endpoint')
        api_version = config.get('api_version')
        if not endpoint or not api_version:
            raise ValueError(
                f"Azure OpenAI endpoint/api_version not configured for model {model}",
            )

        cache_key = (endpoint, api_version, self._auth_type)
        if cache_key not in self._official_clients:
            azure_openai_kwargs: dict[str, Any] = {
                'azure_endpoint': endpoint,
                'api_version': api_version,
            }

            if self._auth_type == 'entra':
                if not self._token_provider:
                    raise ValueError(
                        self._config_error or 'Azure AD token provider not configured',
                    )
                azure_openai_kwargs['azure_ad_token_provider'] = self._token_provider
            else:
                # key auth
                if not self._api_key:
                    raise ValueError(
                        'AZURE_OPENAI_MODE=key requires AZURE_OPENAI_API_KEY',
                    )
                azure_openai_kwargs['api_key'] = self._api_key

            self._official_clients[cache_key] = AzureOpenAI(
                **azure_openai_kwargs,
            )

        return self._official_clients[cache_key]

    def _get_official_async_client(self, model: str):
        """Get official *async* Azure OpenAI client instance.

        Falls back to raising if the installed openai SDK doesn't provide
        AsyncAzureOpenAI.
        """

        if AsyncAzureOpenAI is None:
            raise RuntimeError(
                'AsyncAzureOpenAI is not available in this environment. '
                "Upgrade the 'openai' package or use threadpool fallback.",
            )

        config = self._get_model_config(model)
        endpoint = config.get('endpoint')
        api_version = config.get('api_version')
        if not endpoint or not api_version:
            raise ValueError(
                f"Azure OpenAI endpoint/api_version not configured for model {model}",
            )

        cache_key = (endpoint, api_version, self._auth_type)
        if cache_key not in self._official_async_clients:
            azure_openai_kwargs: dict[str, Any] = {
                'azure_endpoint': endpoint,
                'api_version': api_version,
            }

            if self._auth_type == 'entra':
                if not self._token_provider:
                    raise ValueError(
                        self._config_error or 'Azure AD token provider not configured',
                    )
                azure_openai_kwargs['azure_ad_token_provider'] = self._token_provider
            else:
                if not self._api_key:
                    raise ValueError(
                        'AZURE_OPENAI_MODE=key requires AZURE_OPENAI_API_KEY',
                    )
                azure_openai_kwargs['api_key'] = self._api_key

            self._official_async_clients[cache_key] = AsyncAzureOpenAI(
                **azure_openai_kwargs,
            )  # type: ignore

        return self._official_async_clients[cache_key]

    def _build_messages(
        self, user_message: str, system_prompt: str | None = None,
    ) -> list[dict[str, Any]]:
        """Build message list for chat completion"""
        messages = []
        if system_prompt:
            messages.append({'role': 'system', 'content': system_prompt})
        messages.append({'role': 'user', 'content': user_message})
        return messages

    @staticmethod
    def _is_gpt5_family(deployment: str | None) -> bool:
        dep = str(deployment or '').strip().lower()
        return dep.startswith('gpt-5')

    def _build_chat_request_kwargs(
        self,
        *,
        deployment: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
        top_p: float,
        frequency_penalty: float,
        presence_penalty: float,
        stream: bool,
    ) -> dict[str, Any]:
        """Build Azure OpenAI request kwargs with GPT-family compatibility.

        GPT-5 family deployments use `max_completion_tokens` instead of the
        legacy `max_tokens` parameter. Some previews are also stricter about
        sampling parameters, so we avoid forcing temperature there unless a
        future deployment explicitly requires it.
        """
        request_kwargs: dict[str, Any] = {
            'model': deployment,
            'messages': messages,
            'top_p': top_p,
            'frequency_penalty': frequency_penalty,
            'presence_penalty': presence_penalty,
            'stream': stream,
        }

        if self._is_gpt5_family(deployment):
            request_kwargs['max_completion_tokens'] = max_tokens
        else:
            request_kwargs['max_tokens'] = max_tokens
            request_kwargs['temperature'] = temperature

        return request_kwargs

    @staticmethod
    def _extract_unsupported_parameter_name(error: Exception) -> str | None:
        text = str(error)
        patterns = [
            r"Unsupported parameter:\s*'([^']+)'",
            r'"param":\s*"([^"]+)"',
            r"'param':\s*'([^']+)'",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return str(match.group(1)).strip()
        return None

    @staticmethod
    def _is_deployment_not_found_error(error: Exception) -> bool:
        text = str(error)
        return 'DeploymentNotFound' in text or 'deployment for this resource does not exist' in text.lower()

    def _disable_deployment(self, deployment: str, reason: Exception | str) -> None:
        dep = str(deployment or '').strip()
        if not dep or dep in self._disabled_deployments:
            return
        self._disabled_deployments.add(dep)
        logger.warning('Disabling Azure OpenAI deployment %s after failure: %s', dep, reason)

    def _get_retry_model_key(self, current_deployment: str) -> str | None:
        preferred_keys: list[str] = []
        if self.default_model:
            preferred_keys.append(self.default_model)
        preferred_keys.extend([str(k) for k in self.model_configs.keys()])

        seen: set[str] = set()
        for key in preferred_keys:
            if key in seen:
                continue
            seen.add(key)
            cfg = self.model_configs.get(key)
            if not self._is_model_config_available(cfg):
                continue
            dep = str((cfg or {}).get('deployment') or '').strip()
            if not dep or dep == current_deployment:
                continue
            return key

        return None

    @staticmethod
    def _estimate_request_tokens(request_kwargs: dict[str, Any]) -> int:
        """Conservatively estimate input plus maximum output tokens."""
        chars = 0
        image_count = 0
        for message in request_kwargs.get('messages') or []:
            content = message.get('content', '') if isinstance(message, dict) else ''
            if isinstance(content, str):
                chars += len(content)
            elif isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get('type') == 'text':
                        chars += len(str(part.get('text') or ''))
                    elif part.get('type') == 'image_url':
                        image_count += 1
        output_tokens = int(
            request_kwargs.get('max_completion_tokens')
            or request_kwargs.get('max_tokens')
            or 0
        )
        return max(1, (chars + 3) // 4 + image_count * 1000 + output_tokens)

    def _get_rate_limiter(self, deployment: str) -> DeploymentRateLimiter | None:
        config = next(
            (
                cfg for cfg in self.model_configs.values()
                if str(cfg.get('deployment') or '') == deployment
            ),
            None,
        )
        if not config:
            return None
        rpm = int(config.get('requests_per_minute') or 0)
        tpm = int(config.get('tokens_per_minute') or 0)
        if rpm <= 0 and tpm <= 0:
            return None
        limiter = self._rate_limiters.get(deployment)
        if limiter is None:
            limiter = DeploymentRateLimiter(rpm, tpm)
            self._rate_limiters[deployment] = limiter
        return limiter

    @staticmethod
    def _retry_after_seconds(error: Exception) -> float | None:
        error_text = str(error).lower()
        if (
            getattr(error, 'status_code', None) != 429
            and 'rate limit' not in error_text
            and 'rate_limit' not in error_text
        ):
            return None
        headers = getattr(error, 'headers', None) or {}
        try:
            if headers.get('retry-after-ms') is not None:
                return max(0.0, float(headers['retry-after-ms']) / 1000.0)
            if headers.get('retry-after') is not None:
                return max(0.0, float(headers['retry-after']))
        except (TypeError, ValueError):
            pass
        return 1.0

    async def _create_chat_completion_request(
        self,
        *,
        model: str,
        request_kwargs: dict[str, Any],
    ):
        current_model = model
        current_request = dict(request_kwargs)
        attempted_deployments: set[str] = set()
        rate_limit_retries = 0

        while True:
            deployment = str(current_request.get('model') or '').strip()
            attempted_deployments.add(deployment)
            try:
                limiter = self._get_rate_limiter(deployment)
                if limiter is not None:
                    await limiter.acquire(self._estimate_request_tokens(current_request))
                if AsyncAzureOpenAI is not None:
                    client = self._get_official_async_client(current_model)
                    return await client.chat.completions.create(**current_request)

                client = self._get_official_client(current_model)

                def _call_sync():
                    return client.chat.completions.create(**current_request)

                return await run_in_threadpool(_call_sync)
            except Exception as e:
                retry_after = self._retry_after_seconds(e)
                if retry_after is not None and rate_limit_retries < 3:
                    rate_limit_retries += 1
                    logger.warning(
                        'Azure OpenAI rate limit for deployment %s; retrying in %.2fs (%s/3)',
                        deployment, retry_after, rate_limit_retries,
                    )
                    await asyncio.sleep(retry_after)
                    continue
                unsupported_param = self._extract_unsupported_parameter_name(e)
                if unsupported_param and unsupported_param in current_request:
                    logger.warning(
                        'Retrying Azure OpenAI request for deployment %s without unsupported parameter %s',
                        deployment,
                        unsupported_param,
                    )
                    current_request.pop(unsupported_param, None)
                    continue

                if self._is_deployment_not_found_error(e):
                    self._disable_deployment(deployment, e)
                    retry_model = self._get_retry_model_key(deployment)
                    if retry_model:
                        retry_config = self.model_configs.get(retry_model) or {}
                        retry_deployment = str(retry_config.get('deployment') or '').strip()
                        if retry_deployment and retry_deployment not in attempted_deployments:
                            logger.warning(
                                'Retrying Azure OpenAI request with fallback deployment %s after %s was not found',
                                retry_deployment,
                                deployment,
                            )
                            current_model = retry_model
                            current_request = {**current_request, 'model': retry_deployment}
                            continue

                raise

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        top_p: float = 1.0,
        frequency_penalty: float = 0.0,
        presence_penalty: float = 0.0,
        stream: bool = False,
    ) -> dict[str, Any]:
        """
        Create a chat completion using Azure OpenAI official client

        Args:
            messages: List of message dictionaries with 'role' and 'content'
            model: Model to use (defaults to configured default)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            top_p: Nucleus sampling parameter
            frequency_penalty: Frequency penalty
            presence_penalty: Presence penalty
            stream: Whether to stream the response

        Returns:
            Chat completion response
        """
        model = model or self.default_model
        config = self._get_model_config(model)
        deployment = config['deployment']

        try:
            # Prefer true async client when available; otherwise offload the sync
            # network call to a threadpool to avoid blocking the event loop.
            request_kwargs = self._build_chat_request_kwargs(
                deployment=deployment,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                frequency_penalty=frequency_penalty,
                presence_penalty=presence_penalty,
                stream=stream,
            )
            response = await self._create_chat_completion_request(
                model=model,
                request_kwargs=request_kwargs,
            )

            if stream:
                return response
            else:
                usage = response.usage
                completion_tokens = usage.completion_tokens if usage else 0
                prompt_tokens = usage.prompt_tokens if usage else 0
                total_tokens = usage.total_tokens if usage else 0

                logger.info(
                    'Azure OpenAI usage model=%s deployment=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s',
                    model,
                    deployment,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                )
                return {
                    'choices': [
                        {
                            'message': {
                                'content': response.choices[0].message.content,
                                'role': response.choices[0].message.role,
                            },
                            'finish_reason': response.choices[0].finish_reason,
                        },
                    ],
                    'usage': {
                        'completion_tokens': completion_tokens,
                        'prompt_tokens': prompt_tokens,
                        'total_tokens': total_tokens,
                    },
                }

        except Exception as e:
            print(f"Error calling Azure OpenAI: {e}")
            raise Exception(
                f"Failed to get response from Azure OpenAI: {str(e)}",
            )

    async def simple_chat(
        self,
        user_message: str,
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> str:
        """Simple chat interface that returns just the response text"""
        try:
            messages = self._build_messages(user_message, system_prompt)
            response = await self.chat_completion(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response['choices'][0]['message']['content']
        except Exception as e:
            print(f"Error in simple chat: {e}")
            return f"I apologize, but I encountered an error while processing your request. Please try again later. (Error: {str(e)})"

    async def multimodal_chat(
        self,
        user_text: str,
        images: list[tuple[bytes, str]],
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.0,
    ) -> str:
        """Send a single user message with multiple attached images.

        `images` items are (bytes, mime_type) where mime_type is e.g. "image/png".
        """
        try:
            parts: list[dict[str, Any]] = [{'type': 'text', 'text': user_text}]
            for b, mime in images or []:
                if not b:
                    continue
                b64 = base64.b64encode(b).decode('utf-8')
                parts.append(
                    {
                        'type': 'image_url',
                        'image_url': {'url': f"data:{mime};base64,{b64}"},
                    },
                )

            messages: list[dict[str, Any]] = []
            if system_prompt:
                messages.append({'role': 'system', 'content': system_prompt})
            messages.append({'role': 'user', 'content': parts})

            response = await self.chat_completion(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response['choices'][0]['message']['content']
        except Exception as e:
            print(f"Error in multimodal_chat: {e}")
            return (
                'I apologize, but I encountered an error while processing your request. '
                f"Please try again later. (Error: {str(e)})"
            )

    async def streaming_chat(
        self,
        user_message: str,
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        top_p: float = 1.0,
    ):
        """Streaming chat interface - yields response text chunks as they arrive"""
        try:
            messages = self._build_messages(user_message, system_prompt)
            model = model or self.default_model
            deployment = self._get_model_config(model)['deployment']

            request_kwargs = self._build_chat_request_kwargs(
                deployment=deployment,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                stream=True,
            )

            # Use async streaming when available. Otherwise, move the entire
            # blocking streaming loop into a worker thread and forward chunks.
            if AsyncAzureOpenAI is not None:
                response = await self._create_chat_completion_request(
                    model=model,
                    request_kwargs=request_kwargs,
                )
                async for update in response:
                    if update.choices:
                        content = update.choices[0].delta.content or ''
                        if content:
                            yield content
            else:
                client = self._get_official_client(model)
                loop = asyncio.get_running_loop()
                q: asyncio.Queue[object] = asyncio.Queue()
                _DONE = object()

                def _worker() -> None:
                    try:
                        resp = client.chat.completions.create(**request_kwargs)
                        for update in resp:
                            if not getattr(update, 'choices', None):
                                continue
                            content = update.choices[0].delta.content or ''
                            if content:
                                asyncio.run_coroutine_threadsafe(
                                    q.put(content), loop,
                                ).result()
                    except Exception as e:
                        asyncio.run_coroutine_threadsafe(
                            q.put(e), loop,
                        ).result()
                    finally:
                        asyncio.run_coroutine_threadsafe(
                            q.put(_DONE), loop,
                        ).result()

                limiter = self._get_rate_limiter(deployment)
                if limiter is not None:
                    await limiter.acquire(self._estimate_request_tokens(request_kwargs))
                await run_in_threadpool(_worker)

                while True:
                    item = await q.get()
                    if item is _DONE:
                        break
                    if isinstance(item, Exception):
                        raise item
                    yield str(item)

        except Exception as e:
            print(f"Error in streaming chat: {e}")
            yield f"I apologize, but I encountered an error while processing your request. Please try again later. (Error: {str(e)})"

    async def chat_with_context(
        self,
        user_message: str,
        context_documents: list[str],
        system_prompt: str | None = None,
        model: str | None = None,
        max_tokens: int = 1500,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """
        Chat with document context for RAG applications

        Args:
            user_message: The user's message
            context_documents: List of relevant document chunks
            system_prompt: Optional custom system prompt
            model: Model to use
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature

        Returns:
            Dictionary with response and metadata
        """
        if not system_prompt:
            system_prompt = """You are an AI assistant for Health Canada. Your role is to help users answer scientific questions based on official scientific documents, research studies, and regulatory assessments.

Answer the question using the following context between XML tags <context></context>:
<context>{context}</context>
Always include the chunk number for each chunk you use in the response.
Use square brackets to reference the source, for example [52].
Don't combine citations, list each product separately, for example [27][51]

Guidelines:
- Use only the provided context documents to answer questions
- Focus on scientific accuracy and evidence-based responses
- If information is not in the provided documents, clearly state that you don't have that information
- Maintain a professional, helpful tone appropriate for scientific communications
- If asked about sensitive or classified information, remind users to follow proper security protocols"""

        # Add context documents to system prompt
        if context_documents:
            context_text = '\n\n---\n\n'.join(
                [
                    (
                        f"Context Source: {i+1}\nDocument: Document {i+1}\nContent: {doc[:2000]}..."
                        if len(doc) > 2000
                        else f"Context Source: {i+1}\nDocument: Document {i+1}\nContent: {doc}"
                    )
                    for i, doc in enumerate(context_documents)
                ],
            )
            full_system_prompt = system_prompt.format(context=context_text)
        else:
            full_system_prompt = f"{system_prompt.replace('<context>{context}</context>', 'No specific context documents found.')}\n\nPlease provide a general helpful response while noting the lack of specific documentation."

        messages = [
            {'role': 'system', 'content': full_system_prompt},
            {'role': 'user', 'content': user_message},
        ]

        try:
            response = await self.chat_completion(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            if 'choices' in response and len(response['choices']) > 0:
                return {
                    'response': response['choices'][0]['message']['content'],
                    'model': model or self.default_model,
                    'usage': response.get('usage', {}),
                    'context_documents_count': len(context_documents),
                    'finish_reason': response['choices'][0].get(
                        'finish_reason', 'unknown',
                    ),
                }
            else:
                raise Exception('No response generated')

        except Exception as e:
            print(f"Error in context chat: {e}")
            return {
                'response': 'I apologize, but I encountered an error while processing your request with the provided context. Please try again later.',
                'model': model or self.default_model,
                'usage': {},
                'context_documents_count': len(context_documents),
                'finish_reason': 'error',
                'error': str(e),
            }

    def get_available_models(self) -> list[str]:
        """Get list of available models that are properly configured"""
        out: list[str] = []
        for model, _config in self._iter_available_model_configs():
            out.append(model)
        return out

    def get_available_deployments(self) -> list[str]:
        """Return the available *deployment ids* (e.g. gpt-5-mini).

        This is convenient for UIs that store the deployment id instead of the
        models.yaml display key.
        """
        out: list[str] = []
        seen: set[str] = set()
        for _model, config in self._iter_available_model_configs():
            dep = str(config.get('deployment') or '').strip()
            if not dep:
                continue
            if dep in seen:
                continue
            seen.add(dep)
            out.append(dep)
        return out

    def get_available_model_catalog(self) -> list[dict[str, str]]:
        """Return UI-safe model metadata derived from models.yaml.

        Each item includes the models.yaml display key and deployment id so
        frontend selectors can render labels from backend config without
        hardcoding GPT options.
        """
        out: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        for model, config in self._iter_available_model_configs():
            display_name = str(model).strip()
            deployment = str(config.get('deployment') or '').strip()
            api_version = str(config.get('api_version') or '').strip()
            if not display_name or not deployment or not api_version:
                continue

            key = (display_name, deployment)
            if key in seen:
                continue
            seen.add(key)

            out.append({
                'display_name': display_name,
                'deployment': deployment,
                'api_version': api_version,
            })

        return out

    def get_default_model_key(self) -> str:
        """Return the resolved default models.yaml display key."""
        return self._resolve_default_model(self.default_model)

    def get_default_deployment(self) -> str | None:
        """Return the resolved default deployment id for the active catalog."""
        try:
            config = self._get_model_config(self.get_default_model_key())
            deployment = str(config.get('deployment') or '').strip()
            return deployment or None
        except Exception:
            return None

    def is_configured(self) -> bool:
        """Check if Azure OpenAI is properly configured"""
        if self._config_error:
            return False
        if not self.get_available_models():
            return False

        if self._auth_type == 'key':
            return bool(self._endpoint and self._api_key)
        if self._auth_type == 'entra':
            return bool(self._endpoint and self._token_provider)
        return False


# Global Azure OpenAI client instance
# NOTE: This is used by routers. We intentionally avoid raising during import
# so the API can start up and report configuration issues as 503s.
try:
    azure_openai_client = AzureOpenAIClient()
except Exception as e:  # pragma: no cover
    logger.exception('Failed to initialize AzureOpenAIClient: %s', e)
    # Provide a stub that reports not-configured.

    class _DisabledAzureOpenAIClient:  # type: ignore
        def is_configured(self) -> bool:
            return False

        def get_available_models(self) -> list[str]:
            return []

        def get_default_model_key(self) -> str:
            return ''

        def get_default_deployment(self) -> str | None:
            return None

        def get_available_deployments(self) -> list[str]:
            return []

        def get_available_model_catalog(self) -> list[dict[str, str]]:
            return []

    azure_openai_client = _DisabledAzureOpenAIClient()  # type: ignore
