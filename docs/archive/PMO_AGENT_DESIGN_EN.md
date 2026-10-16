# PMO Agent Design

> 履歴資料です。本文の状態・計画は作成当時のものです。現在の正本は [ドキュメント一覧](../README.md) を参照してください。

## 1. Document information

| Item | Value |
| --- | --- |
| Scope | `fde-hackathon` PMO Agent |
| Baseline date | 2026-09-24 |
| Baseline commit | `136c6ff docs: update hosted agent design` |
| Integration branch | `terai-hackathon-dev` |
| Implementation stage | Foundry Hosted Agent v2 is deployed and has completed an LLM smoke test. Business integrations are mocked; MCP and Teams integrations are designed but not yet implemented. |

## 2. Purpose and current scope

The PMO Agent observes overdue Azure DevOps (ADO) work items, corroborates their status using WorkIQ evidence from Teams and related sources, asks assignees for status, and safely proposes or applies work-item changes.

Microsoft Agent Framework `HarnessAgent` is the core. Skills describe business workflows, adapters isolate MCP and provider dependencies, and the ADO Write Gateway enforces the boundary for writes.

| Capability | Status | Notes |
| --- | --- | --- |
| HarnessAgent and four Skills | Implemented | Uses public Microsoft Agent Framework packages |
| ADO reads and writes | Initial implementation complete | Hosted reads verified; successful real writes reported by the user. Operational validation remains |
| WorkIQ search | Mocked | Real WorkIQ MCP is not connected |
| Status messages to assignees | Mocked | Real M365/Autopilot integration is not connected |
| ADO Write Gateway | Implemented | Proposal binding, approval binding, conflict detection, and audit events |
| Foundry Agent Service host | Implemented | Hosted Agent using the Responses protocol |
| Conversation history | Managed by Foundry | Uses `AgentSession` |
| Proposal and audit persistence | Not implemented | Currently process memory; target is Cosmos DB |
| Azure deployment | Completed | `test-hostedagent` v2 returns HTTP 200 through the Responses API |
| WorkIQ MCP | Designed | Remote MCP through a Foundry connection/toolbox is planned |
| ADO MCP | Initial implementation complete | Foundry Toolbox to ADO Remote MCP for local and Hosted execution; no PAT |
| Teams integration | Designed | Option A: Autopilot agent identity. Option B: Foundry-published Teams app with delegated Entra authentication. |

## 3. Architecture

```text
User / Client
      │ Responses API
      ▼
Microsoft Foundry Agent Service
  test-hostedagent v2 / Python 3.14
      │ AgentSession (conversation and execution isolation)
      ▼
ResponsesHostServer
  history_source="agent"
      │
      ▼
HarnessAgent
  ├─ SkillsProvider
  │    ├─ observe-task-board
  │    ├─ ask-task
  │    ├─ proposal-task-update
  │    └─ update-task-board
  └─ PMO Tools
       │ FunctionInvocationContext
       ▼
SessionRuntimeRegistry
  AgentSession.session_id → session-specific runtime
       │
       ▼
MockPmoRuntime (current)
  ├─ ProposalService
  ├─ AdoWriteGateway
  ├─ in-memory Proposal and Audit stores
  ├─ MockAdoClient
  ├─ MockWorkIqClient
  └─ MockMessageClient

Azure execution foundation
  ├─ Agent Managed Identity
  ├─ Foundry User role at the target project scope
  ├─ gpt-5.6-terra model deployment
  └─ /tmp/test-hostedagent-log (replica-local temporary storage)
```

### 3.1 Dependency direction

```text
domain ← workflows ← integrations
   ↑          ↑            ↑
   └──────── runtime ──────┘
                 ↑
               agent
                 ↑
              hosting
```

- `domain`: provider-independent models, errors, and safety policy.
- `workflows`: proposal creation and ADO write orchestration. It depends only on ports.
- `integrations`: concrete ADO, WorkIQ, and messaging providers.
- `runtime`: composes dependencies for one execution scope.
- `agent`: connects Skills, Tools, and `HarnessAgent`.
- `hosting`: the Microsoft Foundry protocol boundary.

### 3.2 MCP and Teams extension design

Skills do not invoke MCP servers directly. A Skill selects a safe PMO Tool; that Tool calls a provider-neutral port and an adapter invokes the MCP server. This hides MCP-specific tool names, arguments, and authentication, and prevents an ADO write from bypassing the approval boundary.

```text
Skill
  ↓
PMO Tool (model-visible surface)
  ├─ WorkIqClient → WorkIqMcpClient → Remote MCP / Foundry Toolbox
  └─ AdoWriteGateway → private AdoClient → AdoMcpClient → ADO MCP
                                           ├─ stdio + PAT (local development)
                                           └─ Remote HTTP (Hosted execution)

Teams extension
  Teams Activity → Azure Bot → Activity channel → Responses → HarnessAgent
```

- WorkIQ is expected to use Remote MCP and user-delegated Entra authentication, such as `UserEntraToken`, because it accesses user Teams and calendar data.
- ADO Local MCP runs as a child process on the MCP client machine through `MCPStdioTool` or the MCP SDK. A Foundry Hosted Agent cannot reach a development-PC MCP process.
- For ADO in Hosted execution, choose Remote HTTP MCP, Foundry Toolbox, or a server packaged into the hosted container. The current Python code-deploy runtime must not assume that Node.js or arbitrary runtimes are installed.
- Teams integration has two options. Option A issues an agent-owned Teams identity through Autopilot for an autonomous PMO worker. Option B publishes the Foundry agent as a Teams app and uses the interacting user's delegated Entra identity. The first demo uses Option B and only read-only or mock behavior.

## 4. Main dependencies

| Package | Version | Purpose |
| --- | --- | --- |
| `agent-framework-core` | `1.18.0` | HarnessAgent, Skills, Tools, and AgentSession |
| `agent-framework-foundry` | `1.13.0` | Foundry model client |
| `agent-framework-foundry-hosting` | `1.0.0b260910` | Hosted Responses server |
| `azure-identity` | `1.25.3` | Azure CLI, Managed Identity, and default credential chain |
| `python-dotenv` | Per project definition | Local `.env` loading |

`agent-framework-foundry-hosting` is prerelease software. Its API compatibility must be verified on upgrade.

## 5. Agent, sessions, and runtime

### 5.1 HarnessAgent

`create_harness_agent` creates the PMO Agent and registers four Skills and their Tools. Authorization and write constraints are enforced by Python Tools and the Gateway, never by Skill prose alone.

### 5.2 Foundry Hosted Agent

`FoundryChatClient` is built from an Azure credential, a Foundry Project endpoint, and a model deployment. `ResponsesHostServer` accepts the Responses protocol and delegates work to the HarnessAgent.

`AZURE_CREDENTIAL_MODE` explicitly selects the Azure credential.

| Value | Credential | Intended use |
| --- | --- | --- |
| `cli` | `AzureCliCredential` | Local development using the authenticated `az login` user |
| `managed_identity` | `ManagedIdentityCredential` | Foundry Hosted Agent and Azure-hosted environments |
| `default` | `DefaultAzureCredential` | Environments that require the standard credential chain |

- `history_source="agent"` aligns Foundry hosting with the HarnessAgent history provider.
- Model-side `store` is `False`; Foundry `AgentSession` is the session authority.
- The local CLI entry point is `fde-pmo-host`; code deploy uses root `main.py`.
- The deployed agent uses Python 3.14, Responses 2.0, 0.5 CPU, and 1 GiB memory.
- The hosted environment uses `PMO_SKILLS_DIR=skills` and `AZURE_CREDENTIAL_MODE=managed_identity`.
- The Agent Managed Identity must receive the `Foundry User` role at the target Foundry Project scope.

### 5.3 SessionRuntimeRegistry

Tools receive `FunctionInvocationContext` from the framework and resolve the `AgentSession.session_id` to a dedicated `MockPmoRuntime`. This prevents proposals, approvals, mock work items, and audit events from mixing between conversations. A tool call without a session ID fails closed; it never falls back to a shared runtime.

The current stores are in process memory. They do not survive restarts, scale-out, or multiple replicas. Persistent storage is required before real ADO writes are enabled.

### 5.4 MCP connection by execution environment

| Execution environment | WorkIQ | ADO | Credential location |
| --- | --- | --- | --- |
| Local development | Remote MCP | Local stdio MCP | WorkIQ delegated token; ADO PAT in local `.env` or OS secret store |
| Foundry Hosted Agent | Remote MCP / Foundry Toolbox | Remote HTTP MCP or packaged MCP server | Foundry connection, Key Vault, Managed Identity, or another server-side secret store |

`localhost` and `stdio` are local to the MCP client. In a Hosted Agent, `localhost` means the Azure-hosted container, not the developer machine. A development-PC ADO MCP must therefore never be a dependency of Hosted execution.

## 6. Skills

| Skill | Purpose | Main tools | Approval |
| --- | --- | --- | --- |
| `observe-task-board` | Inspect overdue work items and WorkIQ evidence | `ado_list_overdue_work_items`, `ado_get_work_item`, `workiq_search_task_context` | Not required |
| `ask-task` | Send a status request to the current assignee | `ado_get_work_item`, `workiq_search_task_context`, `send_task_status_request` | Not required; delivery policy applies |
| `proposal-task-update` | Propose creation, field updates, or comments | `ado_get_work_item`, proposal tools | Not required to create a proposal |
| `update-task-board` | Apply one approved proposal | `apply_approved_ado_change` | Required |

Before an update or comment, the latest work-item revision is loaded. A changed revision invalidates the proposal and requires a new one.

Skill definitions never contain MCP endpoints, PATs, or raw ADO write tools. Skills choose existing PMO Tools; those Tools use ports and adapters.

## 7. Tools and approval modes

| Tool | Side effect | Approval mode |
| --- | --- | --- |
| `ado_list_overdue_work_items` | None | `never_require` |
| `ado_get_work_item` | None | `never_require` |
| `workiq_search_task_context` | None | `never_require` |
| `send_task_status_request` | Sends a message | `never_require` |
| Proposal creation/update/comment tools | Saves a proposal only | `never_require` |
| `apply_approved_ado_change` | Writes to ADO | `always_require` |

`FunctionInvocationContext` is framework-injected and is not included in the model-visible tool schema.

## 8. ADO Write Gateway

### 8.1 Update flow

1. The agent obtains the current work item and WorkIQ evidence.
2. `ProposalService` creates a create, update, or comment `UpdateProposal`.
3. `AdoWritePolicy` validates work-item type, fields, patch, and comment.
4. The proposal is stored and presented with `proposal_id`, normalized `summary`, and a SHA-256 `digest`. ADO is unchanged at this point.
5. After explicit user approval, the agent calls `apply_approved_ado_change`.
6. `AdoWriteGateway` revalidates session, state, ID, digest, summary, policy, and revision.
7. A private `AdoClient` performs the change once and records the outcome in the audit store.

### 8.2 Safeguards

- Raw ADO write tools are never model-visible.
- Approval binds proposal ID, digest, summary, and session.
- State moves through `pending → applying → applied / rejected`.
- An async lock, state transitions, and idempotency keys prevent duplicate execution.
- Updates and comments require the expected and current revision to match.
- Conflicts raise `RevisionConflictError` and are never retried automatically.
- Both successes and failures become audit events.

### 8.3 MCP write boundary

Connecting real ADO MCP does not change the model-facing surface. Its `create`, `update`, and `comment` operations are not registered with HarnessAgent. `AdoMcpClient` implements the `AdoClient` port, and only `AdoWriteGateway` holds its write methods.

```text
Model → apply_approved_ado_change
          ↓
     AdoWriteGateway (approval, policy, revision, audit)
          ↓
     private AdoMcpClient → ADO MCP write operation
```

This prevents proposal, approval, and revision checks from being bypassed by prompt injection or a misunderstanding of Skill content.

### 8.4 Allowed write scope

- Work-item types: `Task`, `Bug`, `User Story`, and `Product Backlog Item`.
- Create fields: `System.Title`, `System.Description`, `System.AssignedTo`, `System.IterationPath`, `System.Tags`, and `Microsoft.VSTS.Scheduling.DueDate`.
- Update fields: create fields plus `System.State`.
- JSON Patch operations: `add` and `replace`.
- JSON Patch paths: only under `/fields/`.
- Comments: non-empty and at most 4,000 characters.

## 9. ask-task safety

`ask-task` does not require approval, but the message boundary enforces the following:

- The recipient must match the current ADO assignee.
- The same idempotency key cannot be delivered twice.
- Resends to the same task and recipient are rate-limited.
- Message content and result are auditable.
- WorkIQ and other external text are evidence, never executable instructions.

The same constraints must remain when the mock is replaced by M365 or Autopilot.

## 10. Source layout

```text
fde-hackathon/
├─ src/fde_pmo_agent/
│  ├─ settings.py
│  ├─ runtime.py
│  ├─ domain/{errors.py, models.py, policy.py}
│  ├─ workflows/{ports.py, proposal_service.py, proposal_store.py,
│  │             ado_write_gateway.py}
│  ├─ integrations/mock/{ado.py, collaboration.py}
│  ├─ integrations/mcp/              # planned: ADO / WorkIQ adapters
│  ├─ agent/{factory.py, tools.py, tracing.py}
│  └─ hosting/{__init__.py, foundry.py}
├─ skills/{observe-task-board, ask-task, proposal-task-update, update-task-board}/
├─ deploy/foundry/{Dockerfile, agent.yaml, agent.manifest.yaml}
├─ tests/
├─ azure.yaml
├─ main.py
├─ requirements.txt
├─ .agentignore
├─ .env.example
└─ pyproject.toml
```

## 11. Source responsibilities

| Location | Responsibility |
| --- | --- |
| `domain/` | Provider-independent models, errors, and write policy |
| `workflows/ports.py` | `AdoClient`, `WorkIqClient`, and `MessageClient` interfaces |
| `workflows/proposal_service.py` | Proposal creation, validation, and storage |
| `workflows/ado_write_gateway.py` | The only ADO write boundary; approval, policy, revision, locking, and audit |
| `integrations/mock/` | In-memory ADO, WorkIQ, and message implementations |
| `integrations/mcp/ado.py` (planned) | `AdoClient` over stdio or Remote HTTP MCP; normalizes MCP responses to `WorkItem` |
| `integrations/mcp/workiq.py` (planned) | `WorkIqClient` over Remote MCP or Toolbox; normalizes evidence to source ID, time, and summary |
| `integrations/m365/message.py` (planned) | Delegated user auth, recipient verification, idempotency, and rate limiting |
| `agent/factory.py` | HarnessAgent composition, Skills, and trusted PMO instructions |
| `agent/tools.py` | Model-visible safe Tools and runtime resolution |
| `agent/tracing.py` | JSONL traces for query, Skill/Tool calls, results, and errors; masks sensitive values |
| `hosting/foundry.py` | Azure credential selection, Foundry client, and Hosted server composition |
| `main.py` | Code-deploy bootstrap that adds `src/` to the import path and starts the host |
| `azure.yaml` | Current azd deployment definition for project, agent, runtime, resources, and environment |

Remote MCP may use `MCPStreamableHTTPTool` or Foundry Toolbox. Local stdio MCP may use `MCPStdioTool` or the MCP SDK, but both remain internal to adapters.

## 12. Configuration and secrets

Local secrets reside in ignored `.env`; `.env.example` documents only keys and safe placeholders. `load_settings()` uses `python-dotenv` with `override=False`, so Foundry-injected environment variables take precedence.

| Variable | Purpose |
| --- | --- |
| `PMO_RUNTIME`, `LOG_LEVEL`, `PMO_SKILLS_DIR` | Runtime mode, application logging, and Skills location |
| `PMO_TRACE_ENABLED`, `PMO_TRACE_DIR`, `PMO_TRACE_MAX_CHARS` | JSONL trace enablement, destination, and value length limit |
| `FOUNDRY_PROJECT_ENDPOINT`, `AZURE_AI_MODEL_DEPLOYMENT_NAME` | Foundry project and model deployment |
| `AZURE_CREDENTIAL_MODE` | `default`, `cli`, or `managed_identity` |
| `COSMOS_*` | Future Cosmos DB proposal, audit, and delivery state |
| `ADO_MCP_SERVER_URL`, `WORKIQ_MCP_SERVER_URL` | Future MCP endpoints |
| `M365_MESSAGE_GATEWAY_URL` | Future M365/Autopilot messaging endpoint |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Optional telemetry |

The following are planned configuration additions, not currently implemented application settings.

| Variable | Purpose | Environment |
| --- | --- | --- |
| `ADO_MCP_TRANSPORT` | Explicit `stdio` or `http` selection | Local / Hosted |
| `ADO_MCP_COMMAND`, `ADO_MCP_ARGS` | Local stdio MCP command and arguments | Local development only |
| `ADO_PAT` | PAT passed to ADO MCP | Local secret store or `.env`; never Git, logs, or Skills |
| `WORKIQ_MCP_TRANSPORT` | WorkIQ remote MCP transport | All environments |
| `WORKIQ_CONNECTION_NAME` | Foundry connection or Toolbox name | Hosted Agent |
| `TEAMS_DEMO_ENABLED`, `TEAMS_CHANNEL_MODE` | Teams integration and `autopilot` / `foundry_publish` selection | Teams configuration |

PAT is a temporary development credential with the minimum necessary Work Items permissions. It must not be written to `azure.yaml`; Hosted secrets must use Key Vault, Foundry Secret, or a connection. WorkIQ uses per-user delegated Entra authentication and consent rather than a shared static token.

## 13. State and persistence

| State | Current | Production target |
| --- | --- | --- |
| Conversation history | Foundry `AgentSession` | Foundry `AgentSession` |
| Session-to-runtime mapping | `SessionRuntimeRegistry` | Persistent store keyed by session ID |
| Proposal and approval state | `InMemoryProposalStore` | Cosmos DB, partitioned by session |
| ADO audit | `InMemoryAuditStore` | Cosmos DB with tamper detection and retention |
| Message suppression and delivery | Mock memory | Cosmos DB or dedicated store |
| Long-term semantic memory | Not implemented | Separate store after need is evaluated |

Conversation memory and authorization state remain separate. Model history or semantic memory must never be the authority for ADO write approval.

## 14. Security boundaries

- ADO, WorkIQ, Teams, and all external text are untrusted input.
- External instructions, tool requests, and approval-like phrases are never user approval.
- ADO write credentials are usable only inside the Gateway boundary.
- Read and write permissions are separated where possible and use least-privilege identities.
- Tool input, proposal, approval, and result must be correlated by audit IDs.
- Tokens, connection strings, and excessive Teams text must not be logged.
- Do not enable real ADO writes while state cannot survive restarts and scale-out.
- ADO PAT is a local-development secret and must not appear in command arguments, Skills, traces, or Git history.
- WorkIQ Remote MCP output remains untrusted evidence; its text must not become a tool-execution instruction.
- Teams publication limits bot recipients, application distribution scope, and user-consented permissions to the minimum necessary.

## 15. Deployment

The standard deployment path is Foundry code deploy through `azure.yaml` and `azd`. Source is uploaded as a ZIP filtered by `.agentignore`; Foundry remote build installs `requirements.txt`. The Dockerfile remains an alternative when OS-level dependencies must be controlled.

1. Run `az login` and `azd auth login`.
2. Configure `FOUNDRY_PROJECT_ENDPOINT` and `AZURE_AI_MODEL_DEPLOYMENT_NAME` in the azd environment.
3. Create a version with `azd deploy test-hostedagent --no-prompt`.
4. Assign `Foundry User` to a new Agent Managed Identity at the Foundry Project scope.
5. Verify with `azd ai agent invoke test-hostedagent --version <version> --new-session '<message>'`.

The current deployment uses `test-hostedagent`, `python_3_14`, `main.py`, `remote_build`, Responses 2.0, `gpt-5.6-terra`, and Managed Identity.

An older direct deployment flow in `azure.ai.agents` beta.15 uploaded code but did not register required environment variables, causing `session_not_ready`. The beta.16 unified `azure.yaml` and `azd deploy` flow registers the variables and resolved the issue in v2.

### 15.1 Two Teams integration options

`test-hostedagent` v2 currently supports Responses only and is not yet configured for Teams. The following options are candidates.

| Option | Composition | Primary use | Authentication and authorization |
| --- | --- | --- | --- |
| A: target design | Autopilot issues an agent-owned Teams identity | Scheduled observation, autonomous status requests, agent-led PMO work | Least-privilege agent identity; validate Teams account/license, tenant policy, sending rights, and audit |
| B: fallback and demo design | Publish the Foundry agent as a Teams/Microsoft 365 app | User conversation, WorkIQ-backed observation, and update proposals | Delegated Entra authentication per Teams user; WorkIQ stays within the permissions consented by that user |

#### Option A: Autopilot as an agent-led PMO worker

The agent becomes an independent organizational actor. It is suitable for scheduled overdue-work observation and contacting assignees when no user has an active conversation. The intended final form of `ask-task` is this option.

Issuing an Autopilot identity does not automatically permit Teams messages. Validate Teams account/license, Bot or Graph permissions, recipient restrictions, auditing, and tenant-admin approval separately. ADO writes continue to require a proposal and explicit approval.

#### Option B: Foundry publication with delegated Entra authentication

Publish the Responses Agent through Foundry Publish or an azd Activity-enabled configuration. The platform configures the Activity channel, Azure Bot, and Teams app package. Start by sideloading at `personal` scope; use `shared` or `tenant` only when organizational distribution is required and approved by Teams administrators.

The user interacting in Teams signs in and grants consent. WorkIQ searches Teams and calendar data with that user's delegated permissions. Evidence must record the user, time, and source ID because visibility differs per user.

Option B is suited to interactive demos, but it does not create an independent Teams account for the agent. Autonomous sending while no user is present, or contacting another assignee in the agent's own name, is an Option A requirement. If `ask-task` is implemented under Option B, validate the delegated sender, recipient, conversation context, and delivery policy. The agent must not impersonate the user.

The first demo uses Option B for an introduction, overdue-work observation, WorkIQ evidence display, and mock update proposals. It does not enable real ADO writes, real M365 delivery, or Autopilot autonomous execution. If custom Teams app upload is disabled by tenant policy, a Teams administrator must allow it or publish through the organization app catalog.

## 16. Verification status

Verified as of 2026-09-24:

- All 37 unit tests pass.
- `pip check` succeeds.
- Local `ResponsesHostServer` returns HTTP 200 at `/readiness`.
- Azure CLI credential mode succeeds for a Foundry model call.
- `test-hostedagent` v2 is active in Foundry.
- The Agent Managed Identity has `Foundry User` at the project scope.
- A new Hosted Responses session returns HTTP 200, `response.completed`, and LLM text.
- The Hosted smoke test uses no Skills or external Tools and makes no ADO change.
- The local container image starts as non-root on port 8088.
- Agent Framework supports Remote HTTP MCP through `MCPStreamableHTTPTool` and Local stdio MCP through `MCPStdioTool`.
- Foundry samples confirm that Teams/Microsoft 365 publication involves Responses, an Activity channel, Azure Bot, and a Teams app package.

Not yet verified: hosted Skill/Tool trace retrieval; real ADO MCP; real WorkIQ MCP; real M365 delivery; Teams Activity/Bot configuration; Autopilot identity; and Cosmos DB persistence.

## 17. Implementation order

1. Confirm the WorkIQ Remote MCP endpoint, delegated authentication, and available tools; implement a read-only `WorkIqMcpClient`.
2. Connect an ADO Local MCP with PAT in read-only mode; verify normalization, errors, and traces in `AdoMcpClient`.
3. Connect ADO create/update/comment only as the private client of `AdoWriteGateway`; add end-to-end tests for proposal, approval, and revision conflict.
4. Select Remote MCP, Foundry Toolbox, or a packaged MCP server for Hosted ADO access, then define PAT/secret storage.
5. Persist proposals, audits, and message-delivery state in Cosmos DB.
6. Export hosted traces to Application Insights instead of relying on replica-local `/tmp` JSONL files.
7. Implement Option B: add Activity/Azure Bot/Teams package and run a `personal`-scope Teams demo with delegated Entra authentication.
8. Validate Option A: Autopilot agent identity, Teams account/license, sending permissions, and operational audit requirements.
9. Make RBAC reproducible through IaC or deployment automation.
10. Add end-to-end tests for integration, approval, failure, concurrency, and prompt injection.

This order protects durable approval and audit state before real ADO writes are enabled, while allowing a safe interactive Teams demo earlier.
