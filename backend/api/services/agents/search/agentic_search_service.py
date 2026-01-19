"""
Agentic Search Service

Clean implementation for web search functionality.
Based on Google's sample agent pattern with Gemini.
"""

import os
import time
from typing import List, Dict, Any, Optional, AsyncGenerator
from datetime import datetime

from google.genai import Client
from langchain_google_genai import ChatGoogleGenerativeAI
from openai import OpenAI

from pydantic import BaseModel

from ..base_agent import StreamingAgent
from ....agents.agentic_search.models import (
    AgenticSearchResponse,
    SearchIteration,
    SourceCitation,
    SearchAgentType,
)

RESEARCH_COMPLETENESS_DIVISOR = 10
MAX_FALLBACK_SOURCES = 5


class AgenticSearchService(StreamingAgent):
    """
    Agentic search service using Gemini approach

    Features:
    1. Query Generation (Gemini with structured output)
    2. Google Search (Gemini's native google_search tool)
    3. Reflection (Gemini)
    4. Answer Synthesis (Gemini)
    """

    def __init__(self):
        super().__init__("agentic_search_service")

        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        self.query_generator_model = "gemini-2.0-flash"
        self.reflection_model = "gemini-2.5-flash"
        self.answer_model = "gemini-2.0-flash"

        self._initialize_gemini_client()

        self.depth_configs = {
            "quick": {"max_iterations": 1, "number_of_initial_queries": 2},
            "standard": {"max_iterations": 2, "number_of_initial_queries": 3},
            "deep": {"max_iterations": 3, "number_of_initial_queries": 5},
        }

    def _initialize_gemini_client(self) -> None:
        """Initialize Gemini client if API key is available"""
        if not self.gemini_api_key:
            self.logger.warning(
                "GEMINI_API_KEY not found - required for agentic search"
            )
            self.genai_client = None
            self.openai_client = None
        else:
            self.genai_client = Client(api_key=self.gemini_api_key)
            self.openai_client = OpenAI(
                api_key=self.gemini_api_key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            )

    def _validate_gemini_api_key(self) -> None:
        """Validate that Gemini API key is available"""
        if not self.gemini_api_key:
            raise ValueError("GEMINI_API_KEY required for agentic search")

    def _get_current_date(self) -> str:
        """Get formatted current date for prompts"""
        return datetime.now().strftime("%B %d, %Y")

    def _calculate_research_completeness(self, sources_gathered: List[Dict]) -> float:
        """Calculate research completeness based on sources found"""
        return min(1.0, len(sources_gathered) / RESEARCH_COMPLETENESS_DIVISOR)

    def _create_llm_instance(
        self, model: str, temperature: float = 0.0
    ) -> ChatGoogleGenerativeAI:
        """Create a ChatGoogleGenerativeAI instance with standard configuration"""
        return ChatGoogleGenerativeAI(
            model=model,
            temperature=temperature,
            max_retries=2,
            api_key=self.gemini_api_key,
        )

    def _build_query_generation_prompt(
        self, query: str, max_queries: int, custom_instructions: Optional[str] = None
    ) -> str:
        """Build prompt for query generation"""
        current_date = self._get_current_date()

        base_prompt = f"""Your goal is to generate sophisticated and diverse web search queries. These queries are intended for an advanced automated web research tool capable of analyzing complex results, following links, and synthesizing information.

Instructions:
- Always prefer a single search query, only add another query if the original question requests multiple aspects or elements and one query is not enough.
- Each query should focus on one specific aspect of the original question.
- Don't produce more than {max_queries} queries.
- Queries should be diverse, if the topic is broad, generate more than 1 query.
- Don't generate multiple similar queries, 1 is enough.
- Query should ensure that the most current information is gathered. The current date is {current_date}."""

        if custom_instructions:
            base_prompt += f"\n\nAdditional Instructions:\n{custom_instructions}"

        base_prompt += f"""

Format: 
- Format your response as a JSON object with these exact keys:
  - "rationale": Brief explanation of why these queries are relevant
  - "query": A list of search queries

Context: {query}"""

        return base_prompt

    def _build_web_research_prompt(self, search_query: str) -> str:
        """Build prompt for web research"""
        current_date = self._get_current_date()
        return f"""Conduct targeted Google Searches to gather the most recent, credible information on "{search_query}" and synthesize it into a verifiable text artifact.

Instructions:
- Query should ensure that the most current information is gathered. The current date is {current_date}.
- Conduct multiple, diverse searches to gather comprehensive information.
- Consolidate key findings while meticulously tracking the source(s) for each specific piece of information.
- The output should be a well-written summary or report based on your search findings. 
- Only include the information found in the search results, don't make up any information.

Research Topic:
{search_query}"""

    def _build_reflection_prompt(
        self, research_topic: str, summaries: List[str]
    ) -> str:
        """Build prompt for reflection analysis"""
        return f"""You are an expert research assistant analyzing summaries about "{research_topic}".

Instructions:
- Identify knowledge gaps or areas that need deeper exploration and generate a follow-up query. (1 or multiple).
- If provided summaries are sufficient to answer the user's question, don't generate a follow-up query.
- If there is a knowledge gap, generate a follow-up query that would help expand your understanding.
- Focus on technical details, implementation specifics, or emerging trends that weren't fully covered.

Requirements:
- Ensure the follow-up query is self-contained and includes necessary context for web search.

Output Format:
- Format your response as a JSON object with these exact keys:
  - "is_sufficient": true or false
  - "knowledge_gap": Describe what information is missing or needs clarification
  - "follow_up_queries": Write a specific question to address this gap

Reflect carefully on the Summaries to identify knowledge gaps and produce a follow-up query. Then, produce your output following this JSON format:

Summaries:
{chr(10).join(summaries)}"""

    def _build_answer_synthesis_prompt(
        self, research_topic: str, summaries: List[str]
    ) -> str:
        """Build prompt for final answer synthesis"""
        current_date = self._get_current_date()
        return f"""Generate a high-quality answer to the user's question based on the provided summaries.

Instructions:
- The current date is {current_date}.
- You are the final step of a multi-step research process, don't mention that you are the final step. 
- You have access to all the information gathered from the previous steps.
- You have access to the user's question.
- Generate a high-quality answer to the user's question based on the provided summaries and the user's question.
- Include the sources you used from the Summaries in the answer correctly, use markdown format (e.g. [source title](url)). THIS IS A MUST.

User Context:
- {research_topic}

Summaries:
{chr(10).join(summaries)}"""

    def _extract_sources_from_response(self, response) -> Dict[str, any]:
        """
        Extract sources, search queries, and grounding supports from Gemini response grounding metadata
        Following the official Google documentation pattern
        """
        sources_gathered = []
        search_queries = []
        grounding_supports = []
        response_text = ""

        if (
            hasattr(response, "candidates")
            and response.candidates
            and hasattr(response.candidates[0], "grounding_metadata")
            and response.candidates[0].grounding_metadata
        ):

            grounding_metadata = response.candidates[0].grounding_metadata

            if hasattr(response, "text") and response.text:
                response_text = response.text

            supports = (
                grounding_metadata.grounding_supports
                if hasattr(grounding_metadata, "grounding_supports")
                else []
            )
            chunks = (
                grounding_metadata.grounding_chunks
                if hasattr(grounding_metadata, "grounding_chunks")
                else []
            )

            for support in supports:
                if hasattr(support, "segment") and hasattr(
                    support, "grounding_chunk_indices"
                ):
                    segment_info = {
                        "text": (
                            support.segment.text
                            if hasattr(support.segment, "text")
                            else ""
                        ),
                        "start_index": (
                            support.segment.start_index
                            if hasattr(support.segment, "start_index")
                            else 0
                        ),
                        "end_index": (
                            support.segment.end_index
                            if hasattr(support.segment, "end_index")
                            else 0
                        ),
                        "source_indices": (
                            list(support.grounding_chunk_indices)
                            if support.grounding_chunk_indices
                            else []
                        ),
                    }
                    grounding_supports.append(segment_info)

            for i, chunk in enumerate(chunks):
                print(
                    f"DEBUG: Processing chunk {i}: hasattr(chunk, 'web')={hasattr(chunk, 'web')}"
                )
                if hasattr(chunk, "web") and chunk.web:
                    # Extract URL directly from chunk.web.uri - as per official docs
                    url = (
                        chunk.web.uri
                        if hasattr(chunk.web, "uri") and chunk.web.uri
                        else ""
                    )
                    title = (
                        chunk.web.title
                        if hasattr(chunk.web, "title") and chunk.web.title
                        else f"Source {i+1}"
                    )

                    print(f"DEBUG: Chunk {i} - URL: {url}, Title: {title}")

                    content = ""
                    if hasattr(chunk, "content") and chunk.content:
                        content = chunk.content
                    elif hasattr(chunk.web, "snippet") and chunk.web.snippet:
                        content = chunk.web.snippet

                    supported_segments = [
                        support
                        for support in grounding_supports
                        if i in support["source_indices"]
                    ]

                    sources_gathered.append(
                        {
                            "title": title,
                            "url": url,
                            "snippet": content or title,
                            "chunk_index": i,
                            "supported_segments_count": len(supported_segments),
                            "supported_segments": [
                                seg["text"] for seg in supported_segments[:3]
                            ],  # First 3 segments
                        }
                    )
                    print(f"DEBUG: Added source {i+1}: {title} -> {url}")
                else:
                    print(f"DEBUG: Chunk {i} skipped - no web attribute or web is None")

            if (
                hasattr(grounding_metadata, "web_search_queries")
                and grounding_metadata.web_search_queries
            ):
                search_queries = list(grounding_metadata.web_search_queries)
            elif (
                hasattr(grounding_metadata, "webSearchQueries")
                and grounding_metadata.webSearchQueries
            ):
                search_queries = list(grounding_metadata.webSearchQueries)

        print(
            f"DEBUG: Before adding citations - response_text length: {len(response_text)}"
        )
        print(f"DEBUG: Sources gathered: {len(sources_gathered)}")
        print(f"DEBUG: Grounding supports: {len(grounding_supports)}")
        for i, source in enumerate(sources_gathered):
            print(
                f"DEBUG: Source {i+1}: has_url={bool(source.get('url'))}, url='{source.get('url', '')[:50]}...'"
            )

        text_with_citations = self._add_inline_citations(
            response_text, grounding_supports, sources_gathered
        )

        print(
            f"DEBUG: After adding citations - text_with_citations length: {len(text_with_citations)}"
        )
        print(f"DEBUG: Citations added: {text_with_citations != response_text}")

        return {
            "sources": sources_gathered,
            "search_queries": search_queries,
            "grounding_supports": grounding_supports,
            "response_text": response_text,
            "text_with_citations": text_with_citations,
        }

    def _add_inline_citations(
        self, text: str, grounding_supports: list, sources: list
    ) -> str:
        """
        Add inline citations to text based on grounding supports
        Following Google's official documentation pattern exactly
        """
        if not text or not grounding_supports:
            return text

        # Sort supports by end_index in descending order to avoid shifting issues when inserting
        sorted_supports = sorted(
            grounding_supports, key=lambda s: s.get("end_index", 0), reverse=True
        )

        text_with_citations = text

        for support in sorted_supports:
            end_index = support.get("end_index", 0)
            source_indices = support.get("source_indices", [])

            if source_indices and end_index <= len(text_with_citations):
                # Create citation string like [1](link1), [2](link2) following official docs
                citation_links = []
                for i in source_indices:
                    if i < len(sources):
                        source = sources[i]
                        uri = source.get("url", "")
                        # Always use numbered format [1], [2], etc.
                        citation_number = i + 1
                        if uri and uri.startswith(("http://", "https://")):  # Valid URL
                            citation_links.append(f"[{citation_number}]({uri})")
                            print(
                                f"DEBUG: Created URL citation [{citation_number}]({uri[:50]}...)"
                            )
                        else:  # Fallback to numbered citation without URL
                            citation_links.append(f"[{citation_number}]")
                            print(
                                f"DEBUG: Created numbered citation [{citation_number}] (no valid URL: '{uri}')"
                            )

                if citation_links:
                    citation_string = ", ".join(citation_links)
                    text_with_citations = (
                        text_with_citations[:end_index]
                        + citation_string
                        + text_with_citations[end_index:]
                    )
                    print(
                        f"DEBUG: Inserted citation: '{citation_string}' at position {end_index}"
                    )
                else:
                    print(
                        f"DEBUG: No citation links created for source_indices: {source_indices}"
                    )

        return text_with_citations

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Implementation of abstract execute method from BaseAgent
        """
        return await self.execute_agentic_search(**kwargs)

    async def execute_stream(self, **kwargs) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Implementation of abstract execute_stream method from StreamingAgent
        """
        async for event in self.execute_agentic_search_stream(**kwargs):
            yield event

    async def execute_agentic_search(
        self,
        query: str,
        agent_type: SearchAgentType = SearchAgentType.GOOGLE,
        max_iterations: int = 3,
        include_citations: bool = True,
        search_depth: str = "standard",
        custom_instructions: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> AgenticSearchResponse:
        """
        Execute complete agentic search workflow
        """
        start_time = time.time()
        self._validate_gemini_api_key()

        try:
            # Use streaming implementation and get final result
            final_response = None
            async for event in self.execute_agentic_search_stream(**locals()):
                if (
                    event.get("type") == "finalize_answer"
                    and event.get("data", {}).get("status") == "completed"
                    and event.get("data", {}).get("response")
                ):
                    final_response = AgenticSearchResponse(**event["data"]["response"])
                    break

            if final_response:
                return final_response
            else:
                return self._create_fallback_response(
                    query=query,
                    agent_type=agent_type,
                    processing_time=time.time() - start_time,
                    include_citations=include_citations,
                )

        except Exception as e:
            self.log_error(e, "Agentic search execution")
            raise

    def _create_fallback_response(
        self,
        query: str,
        agent_type: SearchAgentType,
        processing_time: float,
        include_citations: bool = True,
    ) -> AgenticSearchResponse:
        """Create fallback response when normal processing fails"""
        return AgenticSearchResponse(
            query=query,
            final_answer=f"I searched for information about '{query}' but encountered an issue processing the results.",
            total_iterations=0,
            search_iterations=[],
            sources=[],
            source_count=0,
            research_completeness=0.0,
            agent_type_used=agent_type,
            processing_time_seconds=processing_time,
        )

    async def execute_agentic_search_stream(
        self, **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Execute agentic search with streaming updates
        """
        start_time = time.time()
        query = kwargs.get("query", "")
        agent_type = kwargs.get("agent_type", SearchAgentType.GOOGLE)
        max_iterations = kwargs.get("max_iterations", 3)
        search_depth = kwargs.get("search_depth", "standard")
        include_citations = kwargs.get("include_citations", True)
        custom_instructions = kwargs.get("custom_instructions", None)
        user_id = kwargs.get("user_id", None)

        web_research_results = []
        sources_gathered = []
        search_iterations = []
        all_search_queries = []
        all_grounding_supports = []
        texts_with_citations = []

        try:
            self._validate_gemini_api_key()
        except ValueError as e:
            yield await self.emit_event("error", {"error": str(e)})
            return

        number_of_initial_queries = self.depth_configs[search_depth][
            "number_of_initial_queries"
        ]

        try:
            iteration_count = 0

            # Step 1: Generate initial queries
            yield await self.emit_event(
                "generate_query",
                {
                    "status": "generating_queries",
                    "query_count": number_of_initial_queries,
                    "user_id": user_id,
                },
            )

            queries = await self._generate_queries(
                query, number_of_initial_queries, custom_instructions
            )

            yield await self.emit_event(
                "generate_query",
                {
                    "status": "queries_generated",
                    "search_query": queries,
                    "query_count": len(queries),
                },
            )

            while iteration_count < max_iterations:
                iteration_count += 1

                log_prefix = f"[User: {user_id}] " if user_id else ""
                self.log_iteration(
                    iteration_count, f"{log_prefix}Starting with {len(queries)} queries"
                )

                # Step 2: Web research for each query
                yield await self.emit_event(
                    "web_research",
                    {
                        "status": "starting_research",
                        "iteration": iteration_count,
                        "query_count": len(queries),
                    },
                )

                iteration_results = []
                iteration_sources = []

                for i, search_query in enumerate(queries):
                    try:
                        yield await self.emit_event(
                            "web_research",
                            {
                                "status": "researching_query",
                                "query": search_query,
                                "query_index": i + 1,
                                "total_queries": len(queries),
                            },
                        )

                        research_result = await self._web_research(search_query, i)

                        if research_result:
                            iteration_results.append(
                                research_result.get("summary", "Research completed")
                            )
                            iteration_sources.extend(research_result.get("sources", []))

                            iteration_queries = research_result.get(
                                "search_queries", []
                            )
                            if iteration_queries:
                                all_search_queries.extend(iteration_queries)

                            grounding_supports = research_result.get(
                                "grounding_supports", []
                            )
                            if grounding_supports:
                                all_grounding_supports.extend(grounding_supports)

                            text_with_citations = research_result.get(
                                "text_with_citations", ""
                            )
                            if text_with_citations:
                                texts_with_citations.append(text_with_citations)

                            sources_count = len(research_result.get("sources", []))
                            if sources_count > 0:
                                self.log_sources_found(sources_count)

                            yield await self.emit_event(
                                "web_research",
                                {
                                    "status": "query_completed",
                                    "sources_found": sources_count,
                                    "sources_gathered": iteration_sources,
                                },
                            )

                    except Exception as e:
                        self.log_error(e, f"Web research query {i+1}")
                        continue

                web_research_results.extend(iteration_results)
                sources_gathered.extend(iteration_sources)

                # Step 3: Reflection
                yield await self.emit_event(
                    "reflection",
                    {
                        "status": "analyzing_results",
                        "sources_gathered": len(sources_gathered),
                        "iteration": iteration_count,
                    },
                )

                reflection_result = await self._reflection(
                    query, iteration_results, iteration_count
                )

                yield await self.emit_event(
                    "reflection",
                    {
                        "status": "reflection_completed",
                        "is_sufficient": reflection_result["is_sufficient"],
                        "knowledge_gap": reflection_result["knowledge_gap"],
                        "follow_up_queries": reflection_result["follow_up_queries"],
                        "iteration": iteration_count,
                    },
                )

                search_iterations.append(
                    SearchIteration(
                        iteration_number=iteration_count,
                        queries_generated=queries,
                        sources_found=len(iteration_sources),
                        knowledge_gap_identified=reflection_result["knowledge_gap"],
                    )
                )

                if (
                    reflection_result["is_sufficient"]
                    or iteration_count >= max_iterations
                ):
                    break

                queries = reflection_result["follow_up_queries"][:3]

                if not queries:
                    break

            yield await self.emit_event(
                "finalize_answer",
                {
                    "status": "generating_final_answer",
                    "total_sources": len(sources_gathered),
                    "iterations_completed": iteration_count,
                },
            )

            if texts_with_citations and len(texts_with_citations) == 1:
                final_answer = texts_with_citations[0]
                for chunk in [final_answer]:
                    yield await self.emit_event(
                        "answer_chunk", {"chunk": chunk, "status": "streaming"}
                    )
            else:
                final_answer_parts = []
                async for chunk in self._finalize_answer_streaming(
                    query, web_research_results, sources_gathered
                ):
                    final_answer_parts.append(chunk)
                    yield await self.emit_event(
                        "answer_chunk", {"chunk": chunk, "status": "streaming"}
                    )

                final_answer = "".join(final_answer_parts)

            research_completeness = self._calculate_research_completeness(
                sources_gathered
            )
            processing_time = time.time() - start_time

            final_sources = (
                self._prepare_citations(sources_gathered) if include_citations else []
            )
            source_count = len(sources_gathered) if include_citations else 0

            response = AgenticSearchResponse(
                query=query,
                final_answer=final_answer,
                total_iterations=iteration_count,
                search_iterations=search_iterations,
                sources=final_sources,
                source_count=source_count,
                research_completeness=research_completeness,
                agent_type_used=SearchAgentType.GOOGLE,
                processing_time_seconds=processing_time,
                debug_info=(
                    {
                        "search_queries_used": list(set(all_search_queries)),
                        "grounding_supports": all_grounding_supports,
                        "total_grounded_segments": len(all_grounding_supports),
                    }
                    if all_search_queries or all_grounding_supports
                    else None
                ),
            )

            yield await self.emit_event(
                "finalize_answer",
                {
                    "status": "completed",
                    "final_answer": final_answer,
                    "total_sources": len(sources_gathered),
                    "processing_time": processing_time,
                    "research_completeness": research_completeness,
                    "iterations_completed": iteration_count,
                    "response": response.model_dump(),
                },
            )

        except Exception as e:
            self.log_error(e, "Streaming agentic search")
            yield await self.emit_event("error", {"error": str(e)})

    async def _generate_queries(
        self,
        query: str,
        max_queries: int = 3,
        custom_instructions: Optional[str] = None,
    ) -> List[str]:
        """
        Generate initial search queries using Gemini
        """
        try:
            if not self.gemini_api_key:
                return [query]

            llm = self._create_llm_instance(self.query_generator_model, temperature=1.0)

            prompt = self._build_query_generation_prompt(
                query, max_queries, custom_instructions
            )

            class QueryOutput(BaseModel):
                query: List[str]
                rationale: str

            structured_llm = llm.with_structured_output(QueryOutput)
            result = structured_llm.invoke(prompt)

            return result.query

        except Exception as e:
            self.log_error(e, "Gemini query generation")
            return [query]

    async def _web_research(
        self, search_query: str, query_id: int = 0
    ) -> Optional[Dict]:
        """
        Web research using Gemini's native google_search tool
        """
        try:
            formatted_prompt = self._build_web_research_prompt(search_query)

            response = self.genai_client.models.generate_content(
                model=self.query_generator_model,
                contents=formatted_prompt,
                config={
                    "tools": [{"google_search": {}}],
                    "temperature": 0,
                },
            )

            extraction_result = self._extract_sources_from_response(response)

            final_text = extraction_result["text_with_citations"] or (
                response.text if hasattr(response, "text") else ""
            )

            return {
                "summary": final_text,
                "sources": extraction_result["sources"],
                "search_queries": extraction_result["search_queries"],
                "grounding_supports": extraction_result["grounding_supports"],
                "response_text": extraction_result["response_text"],
                "text_with_citations": extraction_result["text_with_citations"],
            }

        except Exception as e:
            self.log_error(e, f"Web research error for: {search_query}")
            return None

    async def _reflection(
        self, research_topic: str, summaries: List[str], iteration_count: int
    ) -> Dict:
        """
        Reflection using Gemini
        """
        try:
            formatted_prompt = self._build_reflection_prompt(research_topic, summaries)

            llm = self._create_llm_instance(self.reflection_model, temperature=1.0)

            class ReflectionOutput(BaseModel):
                is_sufficient: bool
                knowledge_gap: str
                follow_up_queries: List[str]

            structured_llm = llm.with_structured_output(ReflectionOutput)
            result = structured_llm.invoke(formatted_prompt)

            return {
                "is_sufficient": result.is_sufficient,
                "knowledge_gap": result.knowledge_gap,
                "follow_up_queries": result.follow_up_queries,
            }

        except Exception as e:
            self.log_error(e, "Reflection analysis")
            return {
                "is_sufficient": iteration_count >= 2 or len(summaries) >= 3,
                "knowledge_gap": (
                    ""
                    if iteration_count >= 2
                    else "Need more comprehensive information"
                ),
                "follow_up_queries": (
                    []
                    if iteration_count >= 2
                    else [f"{research_topic} additional details"]
                ),
            }

    async def _finalize_answer_streaming(
        self, research_topic: str, summaries: List[str], sources: List[Dict]
    ) -> AsyncGenerator[str, None]:
        """
        Finalize answer using Gemini with streaming support
        """
        try:
            if not self.openai_client:
                fallback_answer = await self._finalize_answer(
                    research_topic, summaries, sources
                )
                yield fallback_answer
                return

            formatted_prompt = self._build_answer_synthesis_prompt(
                research_topic, summaries
            )

            response = self.openai_client.chat.completions.create(
                model=self.answer_model,
                messages=[{"role": "user", "content": formatted_prompt}],
                stream=True,
                temperature=0,
            )

            final_answer_parts = []
            for chunk in response:
                if (
                    chunk.choices
                    and chunk.choices[0].delta
                    and chunk.choices[0].delta.content
                ):
                    content = chunk.choices[0].delta.content
                    final_answer_parts.append(content)
                    yield content

            final_answer = "".join(final_answer_parts)
            for i, source in enumerate(sources):
                if source.get("url"):
                    final_answer = final_answer.replace(
                        f"[source title]({source.get('url')})",
                        f"[{source.get('title', f'Source {i+1}')}]({source.get('url')})",
                    )

        except Exception as e:
            self.log_error(e, "Streaming answer synthesis")
            if sources:
                fallback_answer = f"Based on my research about '{research_topic}', I found {len(sources)} relevant sources:\n\n"
                for i, source in enumerate(sources[:MAX_FALLBACK_SOURCES], 1):
                    fallback_answer += f"{i}. **{source.get('title', f'Source {i}')}**: {source.get('snippet', 'Information found')}\n"
                    if source.get("url"):
                        fallback_answer += f"   Source: {source['url']}\n"
                yield fallback_answer
            else:
                yield f"I searched for information about '{research_topic}' but couldn't find sufficient results to provide a comprehensive answer."

    async def _finalize_answer(
        self, research_topic: str, summaries: List[str], sources: List[Dict]
    ) -> str:
        """
        Finalize answer using Gemini
        """
        try:
            formatted_prompt = self._build_answer_synthesis_prompt(
                research_topic, summaries
            )

            llm = self._create_llm_instance(self.answer_model, temperature=0)

            result = llm.invoke(formatted_prompt)

            final_answer = result.content
            for i, source in enumerate(sources):
                if source.get("url"):
                    final_answer = final_answer.replace(
                        f"[source title]({source.get('url')})",
                        f"[{source.get('title', f'Source {i+1}')}]({source.get('url')})",
                    )

            return final_answer

        except Exception as e:
            self.log_error(e, "Answer synthesis")
            if sources:
                answer = f"Based on my research about '{research_topic}', I found {len(sources)} relevant sources:\n\n"
                for i, source in enumerate(sources[:MAX_FALLBACK_SOURCES], 1):
                    answer += f"{i}. **{source.get('title', f'Source {i}')}**: {source.get('snippet', 'Information found')}\n"
                    if source.get("url"):
                        answer += f"   Source: {source['url']}\n"
                return answer
            else:
                return f"I searched for information about '{research_topic}' but couldn't find sufficient results to provide a comprehensive answer."

    def _prepare_citations(self, sources: List[Dict]) -> List[SourceCitation]:
        """
        Prepare citation objects from search results
        """
        citations = []
        for source in sources:
            citations.append(
                SourceCitation(
                    title=source.get("title", "Unknown Source"),
                    url=source.get("url", ""),
                    snippet=source.get("snippet", ""),
                    source_type="google",
                )
            )
        return citations

    async def health_check(self) -> Dict[str, Any]:
        """
        Check health of the agentic search service
        """
        try:
            return {
                "status": "healthy" if self.gemini_api_key else "unavailable",
                "gemini_configured": bool(self.gemini_api_key),
                "models": {
                    "query_generator": self.query_generator_model,
                    "reflection": self.reflection_model,
                    "answer": self.answer_model,
                },
                "service": "agentic_search_service",
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "service": "agentic_search_service",
            }
