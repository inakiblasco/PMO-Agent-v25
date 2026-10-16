"""Explicit, read-only connection checks; never run as part of unit tests."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging

from ...hosting.foundry import create_azure_credential
from ...settings import load_settings
from .ado import AdoMcpClient, AdoToolboxConfig, FoundryAdoSessionFactory


async def check(config: AdoToolboxConfig, credential, *, work_item_id: int | None, board: bool) -> None:
    sessions = FoundryAdoSessionFactory(config, credential)
    client = AdoMcpClient(config, sessions)
    if board:
        client.validate_board_config()
    async with sessions() as session:
        result = await session.list_tools()
        tools = {tool.name: tool for tool in result.tools}
        for suffix, required in {
            "wit_work_item": {"action", "project", "id", "ids", "fields"},
            "wit_query": {"action", "project", "id", "top"},
        }.items():
            name = f"{config.server_label}___{suffix}"
            if name not in tools or not required <= tools[name].inputSchema.get("properties", {}).keys():
                raise ValueError("Toolbox does not expose the expected ADO read contract.")
        print(json.dumps({"check": "tools", "status": "ok", "names": sorted(tools)}))
    if work_item_id is not None:
        item = await client.get_work_item(work_item_id)
        # Keep task titles, identities, descriptions and comments out of stdout.
        print(json.dumps({"check": "work_item", "status": "ok", "id": item.id, "revision": item.revision}))
    if board:
        items = await client.list_overdue_work_items()
        print(json.dumps({"check": "overdue_board", "status": "ok", "count": len(items)}))


def main() -> None:
    parser = argparse.ArgumentParser(description="Check an existing ADO Toolbox using read-only calls.")
    parser.add_argument("--work-item-id", type=int, help="Read and validate one known Work Item.")
    parser.add_argument("--board", action="store_true", help="Validate the configured overdue saved query.")
    args = parser.parse_args()
    if args.work_item_id is not None and args.work_item_id <= 0:
        parser.error("--work-item-id must be positive")
    logging.disable(logging.CRITICAL)
    credential = None
    try:
        settings = load_settings()
        credential = create_azure_credential(settings)
        asyncio.run(check(settings.ado_toolbox_config(), credential,
                          work_item_id=args.work_item_id, board=args.board))
    except Exception:
        print(json.dumps({"status": "failed", "message": "Check ADO settings, contract, credentials and consent."}))
        raise SystemExit(1) from None
    finally:
        if credential is not None:
            credential.close()


if __name__ == "__main__":
    main()
