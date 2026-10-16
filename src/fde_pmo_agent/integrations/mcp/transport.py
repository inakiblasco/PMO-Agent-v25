"""Request-scoped Foundry MCP transport shared by provider adapters."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any


class FoundryToolboxSessionFactory:
    """Open a fresh session in the current request context; never publish tools.

    FoundryToolbox owns bearer-token injection and hosted call-id forwarding.
    Each operation connects in its own task/context to avoid retaining an earlier
    user's context in the HTTP transport's background tasks. No shared MCP session.
    """

    def __init__(self, config: Any, credential: Any) -> None:
        self.config = config
        self.credential = credential

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[Any]:
        from agent_framework_foundry_hosting import FoundryToolbox
        from mcp import ClientSession

        toolbox = FoundryToolbox(
            self.credential, url=self.config.endpoint,
            load_tools=False, load_prompts=False, timeout=self.config.timeout_seconds,
        )
        try:
            # Use the SDK's authenticated transport without generated model tools,
            # result logging, sampling, or implicit tool-call retries.
            async with toolbox.get_mcp_client() as (reader, writer, _):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    yield session
        finally:
            await toolbox.close()

