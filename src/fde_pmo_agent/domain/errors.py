"""Expected failures at the PMO Agent write boundary."""


class PmoAgentError(Exception):
    """Base class for domain failures safe to report to the caller."""


class ProposalNotFoundError(PmoAgentError):
    """A proposal identifier does not exist."""


class ProposalStateError(PmoAgentError):
    """A proposal is not eligible for execution."""


class ProposalIntegrityError(PmoAgentError):
    """Approval arguments do not match the stored proposal."""


class RevisionConflictError(PmoAgentError):
    """An ADO Work Item changed after a proposal was staged."""


class WritePolicyError(PmoAgentError):
    """A proposed ADO write exceeds the configured policy."""


class WriteOutcomeUnknownError(PmoAgentError):
    """A dispatched write cannot safely be retried without reconciliation."""


class MessagePolicyError(PmoAgentError):
    """An automatic task-status message violates delivery policy."""
