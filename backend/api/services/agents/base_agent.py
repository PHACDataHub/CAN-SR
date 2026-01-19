"""
Base Agent class for all Science-GPT agents
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, AsyncGenerator
from pydantic import BaseModel
import logging
import time

logger = logging.getLogger(__name__)


class AgentMetrics(BaseModel):
    """Metrics for agent performance tracking"""

    start_time: float
    end_time: Optional[float] = None
    iterations_completed: int = 0
    sources_gathered: int = 0
    errors_encountered: int = 0

    @property
    def processing_time(self) -> float:
        if self.end_time:
            return self.end_time - self.start_time
        return time.time() - self.start_time


class BaseAgent(ABC):
    """
    Abstract base class for all Science-GPT agents

    Provides common functionality for:
    - Metrics tracking
    - Error handling
    - Logging
    - State management
    """

    def __init__(self, agent_name: str):
        self.agent_name = agent_name
        self.metrics = AgentMetrics(start_time=time.time())
        self.logger = logging.getLogger(f"agent.{agent_name}")

    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Execute the agent's main functionality
        Must be implemented by all concrete agents
        """
        pass

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Check agent health and dependency status
        Must be implemented by all concrete agents
        """
        pass

    async def execute_with_metrics(self, **kwargs) -> Dict[str, Any]:
        """
        Execute agent with automatic metrics tracking
        """
        try:
            self.logger.info(f"Starting {self.agent_name} execution")
            self.metrics.start_time = time.time()

            result = await self.execute(**kwargs)

            self.metrics.end_time = time.time()
            self.logger.info(
                f"{self.agent_name} completed in {self.metrics.processing_time:.2f}s"
            )

            # Add metrics to result
            result["_metrics"] = {
                "processing_time": self.metrics.processing_time,
                "iterations": self.metrics.iterations_completed,
                "sources_gathered": self.metrics.sources_gathered,
                "errors": self.metrics.errors_encountered,
            }

            return result

        except Exception as e:
            self.metrics.errors_encountered += 1
            self.logger.error(f"{self.agent_name} execution failed: {str(e)}")
            raise

    def log_iteration(self, iteration_num: int, details: str):
        """Log iteration progress"""
        self.metrics.iterations_completed = iteration_num
        self.logger.info(f"Iteration {iteration_num}: {details}")

    def log_sources_found(self, count: int):
        """Log sources found"""
        self.metrics.sources_gathered += count
        self.logger.info(
            f"Found {count} sources (total: {self.metrics.sources_gathered})"
        )

    def log_error(self, error: Exception, context: str = ""):
        """Log error with context"""
        self.metrics.errors_encountered += 1
        self.logger.error(f"Error in {context}: {str(error)}")


class StreamingAgent(BaseAgent):
    """
    Base class for agents that support streaming responses
    """

    @abstractmethod
    async def execute_stream(self, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute agent with streaming updates
        Must be implemented by streaming agents
        """
        pass

    async def emit_event(self, event_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Emit a streaming event
        """
        event = {
            "type": event_type,
            "data": data,
            "timestamp": str(time.time()),
            "agent": self.agent_name,
        }

        self.logger.debug(f"Emitting event: {event_type}")
        return event
