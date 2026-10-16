---
name: update-task-board
description: Apply an already staged ADO change proposal after one-time user approval. Use for Work Item creation, allowed field updates, and comments.
license: MIT
compatibility: Requires the approval-bound ADO write gateway exposed by FdePmoAgent.
allowed-tools: apply_approved_ado_change
metadata:
  version: "0.1.0"
---

# Update Task Board

1. Accept only the proposal ID, digest, and summary returned by a proposal tool in the current Agent session.
2. Show the exact summary to the user before requesting execution.
3. Call `apply_approved_ado_change` with those exact three values. The host will pause for one-time approval.
4. Never request or record a standing approval for future ADO writes.
5. If approval is denied, report that no ADO change was made.
6. If a revision conflict is returned, do not retry. Reload `proposal-task-update` and create a new proposal from the latest Work Item.
7. Report success only from the tool result, including Work Item ID and resulting revision.

The raw ADO write MCP tools are intentionally unavailable to this skill.
