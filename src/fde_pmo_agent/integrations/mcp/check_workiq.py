"""Explicit WorkIQ connection check; normal unit tests never invoke this."""

import argparse
import asyncio
import json
import logging

from ...hosting.foundry import create_azure_credential
from ...settings import load_settings
from .ado import AdoMcpClient
from .transport import FoundryToolboxSessionFactory
from .workiq import WorkIqToolboxClient, WorkIqError


async def check(settings, credential, work_item_id=None):
    config = settings.workiq_toolbox_config()
    ado_config = settings.ado_toolbox_config()
    ado = AdoMcpClient(ado_config, FoundryToolboxSessionFactory(ado_config, credential))
    sessions = FoundryToolboxSessionFactory(config, credential)
    client = WorkIqToolboxClient(config, sessions, ado)
    async with sessions() as session:
        await client.check_contract(session)
    print(json.dumps({"check": "workiq_contract", "status": "ok"}), flush=True)
    if work_item_id is not None:
        result = await client.search_task_context(work_item_id, "")
        print(json.dumps({"check": "workiq_retrieval", "status": "ok", "work_item_id": work_item_id,
                          "answer_chars": len(result[0]["summary"]),
                          "grounding_status": result[0]["grounding_status"]}), flush=True)


def main():
    parser = argparse.ArgumentParser(description="Check WorkIQ schema; optionally retrieve context for one ADO task.")
    parser.add_argument("--work-item-id", type=int)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    credential = None
    try:
        settings = load_settings()
        credential = create_azure_credential(settings)
        asyncio.run(check(settings, credential, args.work_item_id))
    except WorkIqError as exc:
        print(json.dumps({"status": "failed", "message": str(exc)}))
        raise SystemExit(1) from None
    except Exception:
        print(json.dumps({"status": "failed", "message": "Check WorkIQ settings, credentials and consent."}))
        raise SystemExit(1) from None
    finally:
        if credential is not None:
            credential.close()


if __name__ == "__main__":
    main()
