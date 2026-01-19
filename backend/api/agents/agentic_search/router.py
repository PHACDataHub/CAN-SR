"""
Agentic Search API Router
"""

from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
import asyncio
import json
import time

from ...core.security import get_current_active_user
from ...services.agents.search.agentic_search_service import AgenticSearchService
from .models import (
    AgenticSearchRequest,
    AgenticSearchResponse,
    AgenticSearchStreamResponse,
)

router = APIRouter()


@router.post("/research", response_model=AgenticSearchResponse)
async def agentic_research(
    request: AgenticSearchRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Perform agentic research using Google's sample agent approach

    This endpoint follows Google's sample exactly:
    1. Generates optimized search queries using Gemini
    2. Searches Google with Gemini's native google_search tool
    3. Reflects on gathered information using Gemini
    4. Iteratively refines search until comprehensive answer is achieved

    Gemini approach with GEMINI_API_KEY.
    """
    try:
        service = AgenticSearchService()

        # Execute agentic search
        result = await service.execute_agentic_search(
            query=request.query,
            agent_type=request.agent_type,
            max_iterations=request.max_iterations,
            include_citations=request.include_citations,
            search_depth=request.search_depth,
            custom_instructions=request.custom_instructions,
            user_id=current_user.get("user_id"),
        )

        return result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Agentic search failed: {str(e)}",
        )


@router.post("/research/stream")
async def agentic_research_stream(
    request: AgenticSearchRequest,
    current_user: Dict[str, Any] = Depends(get_current_active_user),
):
    """
    Streaming agentic research with real-time updates (Google sample approach)

    Returns a streaming response with real-time updates on:
    - Google search iterations via Gemini
    - Sources found with grounding metadata
    - Reflection results and knowledge gap analysis
    - Final answer generation using Gemini

    Gemini approach with GEMINI_API_KEY.
    """

    async def generate_stream():
        try:
            service = AgenticSearchService()

            # Create async generator for streaming updates
            async for event in service.execute_agentic_search_stream(
                query=request.query,
                agent_type=request.agent_type,
                max_iterations=request.max_iterations,
                include_citations=request.include_citations,
                search_depth=request.search_depth,
                custom_instructions=request.custom_instructions,
                user_id=current_user.get("user_id"),
            ):
                # Format event as server-sent event
                event_data = AgenticSearchStreamResponse(
                    event_type=event["type"],
                    data=event["data"],
                    timestamp=event["timestamp"],
                )

                yield f"data: {event_data.model_dump_json()}\n\n"

        except Exception as e:
            error_event = AgenticSearchStreamResponse(
                event_type="error", data={"error": str(e)}, timestamp=str(time.time())
            )
            yield f"data: {error_event.model_dump_json()}\n\n"

    return StreamingResponse(
        generate_stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream",
        },
    )


@router.get("/capabilities")
async def get_agent_capabilities():
    """
    Get information about available search agent capabilities
    """
    return {
        "available_agents": [
            {
                "type": "google",
                "description": "Google's sample agent - Pure Gemini with native Google search",
                "strengths": [
                    "Real-time information",
                    "Automatic grounding metadata",
                    "Rich citation tracking",
                    "Current events",
                    "Breaking news",
                    "Elegant simplicity",
                ],
            },
        ],
        "note_important": "Following Google's sample exactly - ONLY Google search via Gemini native tool. No Wikipedia, no OpenAI.",
        "recommendations": {
            "google": "Google's sample agent with pure Gemini approach and native Google search"
        },
        "note": "Pure Google sample implementation - only Gemini with native Google search tool. Requires GEMINI_API_KEY only.",
        "search_depths": {
            "quick": "1-2 iterations, fast results",
            "standard": "2-3 iterations, balanced approach",
            "deep": "3-5 iterations, comprehensive research",
        },
        "features": [
            "Pure Gemini pipeline (following Google's sample exactly)",
            "Native Google search tool with automatic grounding",
            "Structured output with Pydantic models",
            "Iterative reflection and knowledge gap detection",
            "Rich citation tracking with grounding chunks",
            "Parallel query execution",
            "Real-time web information",
            "Elegant and simple architecture",
        ],
        "models": {
            "query_generation": "gemini-2.0-flash",
            "search": "gemini-2.0-flash (with native google_search tool)",
            "reflection": "gemini-2.5-flash",
            "answer_synthesis": "gemini-2.0-flash (streaming)",
        },
        "approach": "Google Sample - Pure Gemini (no OpenAI, no Wikipedia)",
    }


@router.get("/health")
async def agent_health_check():
    """
    Health check for agentic search services
    """
    try:
        service = AgenticSearchService()
        health_status = await service.health_check()

        return {
            "status": health_status.get("status", "unknown"),
            "gemini_configured": health_status.get("gemini_configured", False),
            "models": health_status.get("models", {}),
            "service": health_status.get("service", "agentic_search_service"),
            "timestamp": time.time(),
        }

    except Exception as e:
        return {"status": "unhealthy", "error": str(e), "timestamp": time.time()}
