"""Azure OpenAI client service for chat completions"""

import time
from typing import Dict, List, Any, Optional
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from openai import AzureOpenAI

from ..core.config import settings

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
        self.default_model = settings.DEFAULT_CHAT_MODEL

        # Create token provider for Azure OpenAI using DefaultAzureCredential
        # Wrapped with caching to avoid fetching a new token on every request
        self._credential = DefaultAzureCredential()
        self._token_provider = CachedTokenProvider(
            get_bearer_token_provider(
                self._credential, "https://cognitiveservices.azure.com/.default"
            )
        )

        self.model_configs = {
            "gpt-4.1-mini": {
                "endpoint": settings.AZURE_OPENAI_GPT41_MINI_ENDPOINT
                or settings.AZURE_OPENAI_ENDPOINT,
                "deployment": settings.AZURE_OPENAI_GPT41_MINI_DEPLOYMENT,
                "api_version": settings.AZURE_OPENAI_GPT41_MINI_API_VERSION,
            },
            "gpt-5-mini": {
                "endpoint": settings.AZURE_OPENAI_GPT5_MINI_ENDPOINT
                or settings.AZURE_OPENAI_ENDPOINT,
                "deployment": settings.AZURE_OPENAI_GPT5_MINI_DEPLOYMENT,
                "api_version": settings.AZURE_OPENAI_GPT5_MINI_API_VERSION,
            },
        }

        self._official_clients: Dict[str, AzureOpenAI] = {}

    def _get_model_config(self, model: str) -> Dict[str, str]:
        """Get configuration for a specific model"""
        if model in self.model_configs:
            return self.model_configs[model]
        return self.model_configs["gpt-5-mini"]

    def _get_official_client(self, model: str) -> AzureOpenAI:
        """Get official Azure OpenAI client instance"""
        if model not in self._official_clients:
            config = self._get_model_config(model)
            if not config.get("endpoint"):
                raise ValueError(
                    f"Azure OpenAI endpoint not configured for model {model}"
                )

            self._official_clients[model] = AzureOpenAI(
                azure_ad_token_provider=self._token_provider,
                azure_endpoint=config["endpoint"],
                api_version=config["api_version"],
            )

        return self._official_clients[model]

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
            
            if model != "gpt-5-mini":
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

            response = client.chat.completions.create(
                stream=True,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                frequency_penalty=0.0,
                presence_penalty=0.0,
                model=deployment,
            )

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
        return [
            model
            for model, config in self.model_configs.items()
            if config.get("endpoint")
        ]

    def is_configured(self) -> bool:
        """Check if Azure OpenAI is properly configured"""
        return len(self.get_available_models()) > 0


# Global Azure OpenAI client instance
azure_openai_client = AzureOpenAIClient()
