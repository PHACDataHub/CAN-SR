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

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

from ..core.config import settings

logger = logging.getLogger(__name__)

# Token cache TTL in seconds (9 minutes)
TOKEN_CACHE_TTL = 9 * 60


class CachedTokenProvider:
    """Simple in-memory token cache wrapper"""

    def __init__(self, token_provider):
        self._token_provider = token_provider
        self._cached_token: Optional[str] = None
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
        self._config_error: Optional[str] = None
        self.default_model = settings.DEFAULT_CHAT_MODEL

        self._auth_type = self._resolve_auth_type()
        self._endpoint = self._resolve_endpoint()
        self._api_key = settings.AZURE_OPENAI_API_KEY

        self._token_provider: Optional[CachedTokenProvider] = None
        if self._auth_type == "entra":
            if not DefaultAzureCredential or not get_bearer_token_provider:
                self._config_error = (
                    "AZURE_OPENAI_MODE=entra requires azure-identity to be installed"
                )
            else:
                # Create token provider for Azure OpenAI using DefaultAzureCredential
                # Wrapped with caching to avoid fetching a new token on every request
                credential = DefaultAzureCredential()
                self._token_provider = CachedTokenProvider(
                    get_bearer_token_provider(
                        credential, "https://cognitiveservices.azure.com/.default"
                    )
                )

        self.model_configs = self._load_model_configs()
        self.default_model = self._resolve_default_model(self.default_model)

        # Cache official clients by (endpoint, api_version, auth_type)
        self._official_clients: Dict[Tuple[str, str, str], AzureOpenAI] = {}


    # ---------------------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------------------


    @staticmethod
    def _resolve_auth_type() -> str:
        """Return key|entra.

        New config: AZURE_OPENAI_MODE
        Legacy config: USE_ENTRA_AUTH
        """
        t = (getattr(settings, "AZURE_OPENAI_MODE", None) or "").lower().strip()
        if t in {"key", "entra"}:
            return t
        # Legacy fallback
        if getattr(settings, "USE_ENTRA_AUTH", False):
            return "entra"
        return "key"

    @staticmethod
    def _resolve_endpoint() -> Optional[str]:
        return settings.AZURE_OPENAI_ENDPOINT

    def _strip_outer_quotes(self, s: str) -> str:
        s = s.strip()
        if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
            return s[1:-1]
        return s

    def _load_models_yaml(self) -> Dict[str, Any]:
        """Load model catalog from /app/configs/models.yaml.

        This file is expected to be mounted in docker-compose so changes can be
        applied without rebuilding the image.
        """
        path = Path("configs/models.yaml")
        if not path.exists():
            logger.warning("Azure OpenAI model catalog not found at %s", path)
            return {}
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                logger.warning("Invalid models.yaml format (expected mapping): %s", type(data))
                return {}
            return data
        except Exception as e:
            logger.exception("Failed to load Azure OpenAI model catalog from %s: %s", path, e)
            return {}

    def _load_model_configs(self) -> Dict[str, Dict[str, str]]:
        """Build model configs keyed by UI/display name."""
        models = self._load_models_yaml()
        cfg: Dict[str, Dict[str, str]] = {}
        for display_name, meta in models.items():
            if not isinstance(meta, dict):
                continue
            deployment = meta.get("deployment")
            api_version = meta.get("api_version")
            if not deployment or not api_version:
                continue
            cfg[str(display_name)] = {
                "endpoint": self._endpoint or "",
                "deployment": str(deployment),
                "api_version": str(api_version),
            }

        if cfg:
            return cfg

        return {}

    def _resolve_default_model(self, desired: str) -> str:
        if desired in self.model_configs:
            return desired
        # If configured default doesn't exist, fall back to first configured model
        for k in self.model_configs.keys():
            return k
        return desired

    def _get_model_config(self, model: str) -> Dict[str, str]:
        """Get configuration for a specific model"""
        if model in self.model_configs:
            return self.model_configs[model]
        # fallback to first configured model
        for _, cfg in self.model_configs.items():
            return cfg
        raise ValueError("No Azure OpenAI models are configured")

    def _get_official_client(self, model: str) -> AzureOpenAI:
        """Get official Azure OpenAI client instance"""
        config = self._get_model_config(model)
        endpoint = config.get("endpoint")
        api_version = config.get("api_version")
        if not endpoint or not api_version:
            raise ValueError(f"Azure OpenAI endpoint/api_version not configured for model {model}")

        cache_key = (endpoint, api_version, self._auth_type)
        if cache_key not in self._official_clients:
            azure_openai_kwargs: Dict[str, Any] = {
                "azure_endpoint": endpoint,
                "api_version": api_version,
            }

            if self._auth_type == "entra":
                if not self._token_provider:
                    raise ValueError(self._config_error or "Azure AD token provider not configured")
                azure_openai_kwargs["entra_token_provider"] = self._token_provider
            else:
                # key auth
                if not self._api_key:
                    raise ValueError("AZURE_OPENAI_MODE=key requires AZURE_OPENAI_API_KEY")
                azure_openai_kwargs["api_key"] = self._api_key

            self._official_clients[cache_key] = AzureOpenAI(**azure_openai_kwargs)

        return self._official_clients[cache_key]

    def _build_messages(
        self, user_message: str, system_prompt: Optional[str] = None
    ) -> List[Dict[str, str]]:
        """Build message list for chat completion"""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})
        return messages

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        top_p: float = 1.0,
        frequency_penalty: float = 0.0,
        presence_penalty: float = 0.0,
        stream: bool = False,
    ) -> Dict[str, Any]:
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
        deployment = config["deployment"]

        try:
            client = self._get_official_client(model)
            request_kwargs = {
                "model": deployment,
                "messages": messages,
                "top_p": top_p,
                "frequency_penalty": frequency_penalty,
                "presence_penalty": presence_penalty,
                "stream": stream,
            }
            
            # gpt-5 deployments may reject temperature/max_tokens in some previews.
            # We gate this by the *deployment* name because the UI key can differ.
            if deployment != "gpt-5-mini":
                request_kwargs["max_tokens"] = max_tokens
                request_kwargs["temperature"] = temperature

            response = client.chat.completions.create(**request_kwargs)

            if stream:
                return response
            else:
                return {
                    "choices": [
                        {
                            "message": {
                                "content": response.choices[0].message.content,
                                "role": response.choices[0].message.role,
                            },
                            "finish_reason": response.choices[0].finish_reason,
                        }
                    ],
                    "usage": {
                        "completion_tokens": (
                            response.usage.completion_tokens if response.usage else 0
                        ),
                        "prompt_tokens": (
                            response.usage.prompt_tokens if response.usage else 0
                        ),
                        "total_tokens": (
                            response.usage.total_tokens if response.usage else 0
                        ),
                    },
                }

        except Exception as e:
            print(f"Error calling Azure OpenAI: {e}")
            raise Exception(f"Failed to get response from Azure OpenAI: {str(e)}")

    async def simple_chat(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
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
            return response["choices"][0]["message"]["content"]
        except Exception as e:
            print(f"Error in simple chat: {e}")
            return f"I apologize, but I encountered an error while processing your request. Please try again later. (Error: {str(e)})"

    async def streaming_chat(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
        top_p: float = 1.0,
    ):
        """Streaming chat interface - yields response text chunks as they arrive"""
        try:
            messages = self._build_messages(user_message, system_prompt)
            model = model or self.default_model
            deployment = self._get_model_config(model)["deployment"]
            client = self._get_official_client(model)

            request_kwargs: Dict[str, Any] = {
                "stream": True,
                "messages": messages,
                "top_p": top_p,
                "frequency_penalty": 0.0,
                "presence_penalty": 0.0,
                "model": deployment,
            }
            if deployment != "gpt-5-mini":
                request_kwargs["max_tokens"] = max_tokens
                request_kwargs["temperature"] = temperature

            response = client.chat.completions.create(**request_kwargs)

            for update in response:
                if update.choices:
                    content = update.choices[0].delta.content or ""
                    if content:
                        yield content

        except Exception as e:
            print(f"Error in streaming chat: {e}")
            yield f"I apologize, but I encountered an error while processing your request. Please try again later. (Error: {str(e)})"

    async def chat_with_context(
        self,
        user_message: str,
        context_documents: List[str],
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: int = 1500,
        temperature: float = 0.7,
    ) -> Dict[str, Any]:
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
            context_text = "\n\n---\n\n".join(
                [
                    (
                        f"Context Source: {i+1}\nDocument: Document {i+1}\nContent: {doc[:2000]}..."
                        if len(doc) > 2000
                        else f"Context Source: {i+1}\nDocument: Document {i+1}\nContent: {doc}"
                    )
                    for i, doc in enumerate(context_documents)
                ]
            )
            full_system_prompt = system_prompt.format(context=context_text)
        else:
            full_system_prompt = f"{system_prompt.replace('<context>{context}</context>', 'No specific context documents found.')}\n\nPlease provide a general helpful response while noting the lack of specific documentation."

        messages = [
            {"role": "system", "content": full_system_prompt},
            {"role": "user", "content": user_message},
        ]

        try:
            response = await self.chat_completion(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )

            if "choices" in response and len(response["choices"]) > 0:
                return {
                    "response": response["choices"][0]["message"]["content"],
                    "model": model or self.default_model,
                    "usage": response.get("usage", {}),
                    "context_documents_count": len(context_documents),
                    "finish_reason": response["choices"][0].get(
                        "finish_reason", "unknown"
                    ),
                }
            else:
                raise Exception("No response generated")

        except Exception as e:
            print(f"Error in context chat: {e}")
            return {
                "response": f"I apologize, but I encountered an error while processing your request with the provided context. Please try again later.",
                "model": model or self.default_model,
                "usage": {},
                "context_documents_count": len(context_documents),
                "finish_reason": "error",
                "error": str(e),
            }

    def get_available_models(self) -> List[str]:
        """Get list of available models that are properly configured"""
        out: List[str] = []
        for model, config in self.model_configs.items():
            if not config.get("endpoint") or not config.get("deployment") or not config.get("api_version"):
                continue
            out.append(model)
        return out

    def is_configured(self) -> bool:
        """Check if Azure OpenAI is properly configured"""
        if self._config_error:
            return False
        if not self.get_available_models():
            return False

        if self._auth_type == "key":
            return bool(self._endpoint and self._api_key)
        if self._auth_type == "entra":
            return bool(self._endpoint and self._token_provider)
        return False


# Global Azure OpenAI client instance
# NOTE: This is used by routers. We intentionally avoid raising during import
# so the API can start up and report configuration issues as 503s.
try:
    azure_openai_client = AzureOpenAIClient()
except Exception as e:  # pragma: no cover
    logger.exception("Failed to initialize AzureOpenAIClient: %s", e)
    # Provide a stub that reports not-configured.
    class _DisabledAzureOpenAIClient:  # type: ignore
        def is_configured(self) -> bool:
            return False

        def get_available_models(self) -> List[str]:
            return []

    azure_openai_client = _DisabledAzureOpenAIClient()  # type: ignore
