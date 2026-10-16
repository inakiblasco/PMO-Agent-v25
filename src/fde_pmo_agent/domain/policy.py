"""Allow-list policy applied before every ADO write."""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import WritePolicyError
from .models import ChangeOperation, PatchOperation, UpdateProposal


DEFAULT_CREATE_FIELDS = frozenset(
    {
        "System.Title",
        "System.Description",
        "System.AssignedTo",
        "System.IterationPath",
        "System.Tags",
        "Microsoft.VSTS.Scheduling.DueDate",
    }
)
DEFAULT_UPDATE_FIELDS = DEFAULT_CREATE_FIELDS | {"System.State"}


@dataclass(frozen=True, slots=True)
class AdoWritePolicy:
    """Restrict Work Item types, field names, operations, and comment size."""

    allowed_work_item_types: frozenset[str] = field(
        default_factory=lambda: frozenset({"Task", "Bug", "User Story", "Product Backlog Item"})
    )
    allowed_create_fields: frozenset[str] = field(default_factory=lambda: DEFAULT_CREATE_FIELDS)
    allowed_update_fields: frozenset[str] = field(default_factory=lambda: DEFAULT_UPDATE_FIELDS)
    max_comment_length: int = 4_000

    def validate(self, proposal: UpdateProposal) -> None:
        """Validate a proposal immediately before it is staged or applied."""
        if not proposal.reason.strip():
            raise WritePolicyError("An ADO change proposal must include a reason.")
        if proposal.operation is ChangeOperation.CREATE:
            self._validate_create(proposal)
        elif proposal.operation is ChangeOperation.UPDATE:
            self._validate_update(proposal)
        elif proposal.operation is ChangeOperation.COMMENT:
            self._validate_comment(proposal)
        else:  # pragma: no cover
            raise WritePolicyError(f"Unsupported operation: {proposal.operation}")

    def _validate_create(self, proposal: UpdateProposal) -> None:
        if proposal.work_item_type not in self.allowed_work_item_types:
            raise WritePolicyError(f"Work Item type is not allowed: {proposal.work_item_type!r}")
        if not str(proposal.fields.get("System.Title", "")).strip():
            raise WritePolicyError("System.Title is required when creating a Work Item.")
        unknown = set(proposal.fields) - self.allowed_create_fields
        if unknown:
            raise WritePolicyError(f"Create contains disallowed fields: {sorted(unknown)}")

    def _validate_update(self, proposal: UpdateProposal) -> None:
        self._require_existing_target(proposal)
        if not proposal.patch:
            raise WritePolicyError("An update proposal must contain at least one field change.")
        for item in proposal.patch:
            self._validate_patch(item)

    def _validate_comment(self, proposal: UpdateProposal) -> None:
        self._require_existing_target(proposal)
        comment = proposal.comment or ""
        if not comment.strip():
            raise WritePolicyError("A comment must not be empty.")
        if len(comment) > self.max_comment_length:
            raise WritePolicyError(f"A comment must be at most {self.max_comment_length} characters.")

    @staticmethod
    def _require_existing_target(proposal: UpdateProposal) -> None:
        if proposal.work_item_id is None or proposal.work_item_id <= 0:
            raise WritePolicyError("A positive Work Item ID is required.")
        if proposal.expected_revision is None or proposal.expected_revision <= 0:
            raise WritePolicyError("A positive expected revision is required.")

    def _validate_patch(self, item: PatchOperation) -> None:
        if item.op not in {"add", "replace"}:
            raise WritePolicyError(f"Patch operation is not allowed: {item.op!r}")
        prefix = "/fields/"
        if not item.path.startswith(prefix):
            raise WritePolicyError(f"Patch path must start with {prefix!r}: {item.path!r}")
        field_name = item.path.removeprefix(prefix)
        if field_name not in self.allowed_update_fields:
            raise WritePolicyError(f"Update contains a disallowed field: {field_name!r}")
        if field_name == "System.Title" and not str(item.value).strip():
            raise WritePolicyError("System.Title must not be empty.")
