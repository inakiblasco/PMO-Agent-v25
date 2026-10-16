---
name: ask-task
description: Ask the current Azure DevOps assignee for a task status through the configured Autopilot or Microsoft 365 message gateway. Use when evidence is missing or stale.
license: MIT
compatibility: Requires ADO read, WorkIQ, and task-status messaging tools exposed by FdePmoAgent.
allowed-tools: ado_get_work_item workiq_search_task_context send_task_status_request
metadata:
  version: "0.1.0"
---

# Ask Task

1. Call `ado_get_work_item` immediately before sending to obtain the current assignee and task state.
2. Do not send if the Work Item is completed, removed, or has no assignee.
3. Use `workiq_search_task_context` to avoid asking for information already available in recent evidence.
4. Address only the current `System.AssignedTo` identity returned by ADO.
5. Include the Work Item ID, title, due date, and a concise request for current status and expected completion.
6. Call `send_task_status_request`. User approval is not required for this tool.
7. Report the returned message ID and delivery status. Do not claim delivery if the tool fails.

The messaging gateway enforces recipient matching, rate limits, idempotency, and audit logging. Do not attempt to bypass it.
