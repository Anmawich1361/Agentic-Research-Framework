"""Tool wrappers for the Agentic Research Framework."""

from agentic_research.tools.web_search import (
    DuckDuckGoSearchProvider,
    SearchProvider,
    SearchResult,
    StaticSearchProvider,
    WebSearchClient,
    build_source_search_queries,
    create_web_search_tool,
)

__all__ = [
    "DuckDuckGoSearchProvider",
    "SearchProvider",
    "SearchResult",
    "StaticSearchProvider",
    "WebSearchClient",
    "build_source_search_queries",
    "create_web_search_tool",
]
