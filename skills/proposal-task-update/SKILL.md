---
name: proposal-task-update
description: Prepare a reviewable proposal to create an ADO Work Item, update allowed fields, or add a comment without changing ADO. Use before every board write.
license: MIT
compatibility: Requires ADO read and proposal tools exposed by FdePmoAgent.
allowed-tools: ado_get_work_item propose_work_item_create propose_work_item_update propose_work_item_comment
metadata:
  version: "0.1.0"
---

# Proposal Task Update

1. For an update or comment, call `ado_get_work_item` immediately before preparing the proposal.
2. Use the returned revision as `expected_revision`; never guess or reuse an older revision.
3. Choose exactly one proposal tool:
   - `propose_work_item_create` for a new Work Item;
   - `propose_work_item_update` for field changes;
   - `propose_work_item_comment` for a new comment.
4. Include a concise reason and only source IDs as evidence. Do not copy raw Teams or mail bodies into ADO.
5. Present the returned summary, reason, and evidence to the user.
6. If the user requested only a proposal, stop without calling `apply_approved_ado_change`.
7. Never fabricate or modify the returned proposal ID, digest, or summary.

Creating a proposal has no ADO side effect and requires no approval.
