"""
Agentic Search API Models
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


class SearchAgentType(str, Enum):
    """Available search agent types - Google Search only"""

    GOOGLE = "google"


class AgenticSearchRequest(BaseModel):
    """Request model for agentic search"""

    query: str = Field(
        ..., min_length=1, max_length=2000, description="The research question or query"
    )

    agent_type: SearchAgentType = Field(
        SearchAgentType.GOOGLE,
        description="Type of search agent to use (Google Search only)",
    )

    max_iterations: int = Field(
        3, ge=1, le=5, description="Maximum number of research iterations"
    )

    include_citations: bool = Field(
        True, description="Include source citations in the response"
    )

    search_depth: str = Field(
        "standard",
        pattern="^(quick|standard|deep)$",
        description="Search depth: quick (1 iteration, 2 queries), standard (2 iterations, 3 queries), deep (3 iterations, 5 queries)",
    )

    custom_instructions: Optional[str] = Field(
        None,
        max_length=500,
        description="Additional instructions for the search agent (e.g., 'Focus on peer-reviewed sources', 'Include recent developments only')",
    )


class SearchIteration(BaseModel):
    """Single search iteration result"""

    iteration_number: int
    queries_generated: List[str]
    sources_found: int
    knowledge_gap_identified: Optional[str] = None


class SourceCitation(BaseModel):
    """Source citation information"""

    title: str
    url: str
    snippet: str
    source_type: str


class AgenticSearchResponse(BaseModel):
    """Response model for agentic search"""

    query: str
    final_answer: str

    total_iterations: int
    search_iterations: List[SearchIteration]

    sources: List[SourceCitation]
    source_count: int

    research_completeness: float = Field(ge=0.0, le=1.0)

    agent_type_used: SearchAgentType
    processing_time_seconds: float

    debug_info: Optional[Dict[str, Any]] = None


class AgenticSearchStreamResponse(BaseModel):
    """Streaming response for real-time updates"""

    event_type: str
    data: Dict[str, Any]
    timestamp: str
