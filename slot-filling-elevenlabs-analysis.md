# Slot Filling on ElevenLabs — Architecture Analysis

## GCP CXAS SCRAPI Pattern (Summary)

The GCP pattern splits slot filling across two components:

| Component | Responsibility |
|-----------|---------------|
| **Python callback** (`before_model_callback`) | State, control flow, DAG evaluation, task firing, validation, retry logic |
| **LLM** | Language: parsing intent, calling setter tools, generating warm responses |

**Key mechanisms:**
1. `sm` state dict (`filled`, `pending`, `deferred`, `task_results`, `_system_message`, …) stored in `context.state` — deterministic, survives turns
2. `before_model_callback` evaluates the DAG every turn; either preempts the LLM (returns `LlmResponse.from_parts()`) or sets `_system_message` for the LLM to relay
3. Setter tools are thin — return `{"stored": True, "value": …}` or `{"error": True, "error_code": "…"}`
4. `_next_question()` walks ordered slot list, returns first unfilled slot whose deps are met
5. Tools can be hidden from LLM until their dependency slots are filled
6. Multi-slot batching: LLM instructed to call ALL setters in ONE response

## Critical Differences: GCP CXAS vs ElevenLabs

| Capability | GCP CXAS | ElevenLabs |
|-----------|----------|------------|
| Server-side state | `context.state` (built-in) | **None** — must use external state service |
| Pre/post LLM callbacks | `before_model_callback`, `after_model_callback` | **None** — webhook response is the only mechanism |
| LLM preemption | `LlmResponse.from_parts()` bypasses LLM entirely | **Not supported** — LLM always generates after tool calls |
| Dynamic prompt injection | `{{system_message}}` template variable | `dynamic_variables` on agent + `additional_prompt` in workflow nodes |
| Tool visibility control | Hide tools until deps met | `additional_tool_ids` on workflow nodes (scoped per step) |
| Step-by-step routing | Callback-driven DAG evaluation | **Workflows** — native node graph with expression/LLM edges |
| Multi-turn state in tools | Built-in (tools read/write `context.state`) | External — webhook receives `conversation_id`, must manage own store |
| Conversation history in tools | N/A (callback has full context) | `{{system__conversation_history}}` dynamic variable |

## Architecture Options for ElevenLabs

### Option A: State-Service-Driven (closest to GCP pattern)

**Single agent + external state service.** All setters and tasks are webhook tools hitting a state management backend. The state service evaluates the DAG and returns `_system_message` in every response. The system prompt instructs the LLM to relay `_system_message` faithfully.

```
User → ElevenLabs Agent → Webhook Setter → State Service (key-value store / DB)
                                ↓
                        State Service evaluates DAG
                                ↓
              Returns { result: { _system_message: "…", … } }
                                ↓
                        LLM relays _system_message
```

**State service API:**
```
POST /setter/party_size    → validate, store, return _system_message + next_question
POST /setter/date          → validate, store, return _system_message + next_question
POST /setter/time          → validate, store, return _system_message + next_question
POST /setter/guest_name    → validate, store, return _system_message + next_question
POST /task/find_times      → execute task, store result, return _system_message
POST /task/book            → execute task, mark complete, return confirmation
```

**State schema (per conversation_id):**
```json
{
  "filled": {},
  "pending": {},
  "task_results": {},
  "_retries": {},
  "_slot_errors": [],
  "_system_message": "",
  "status": "in_progress"
}
```

**System prompt (ElevenLabs agent prompt):**
```
# Slot Filling Protocol

You are operating in SLOT FILLING mode. Follow these rules strictly:

1. TOOL-DRIVEN CONVERSATION: After each user message, identify EVERY piece
   of information the user provided and call ALL corresponding setter tools
   in the SAME response.

2. PROGRESSIVE DISCLOSURE: Only ask ONE question at a time. Never preview
   future steps.

3. RELAY SYSTEM MESSAGES: Every tool response will include a "_system_message"
   field. You MUST relay this message verbatim as your response to the user.
   Do not paraphrase, summarize, or add to it. The _system_message is your
   exact script.

4. ALWAYS CALL TOOLS: Call the setter tool for every piece of information
   the user provides, even if the value seems out of range. The system
   validates all inputs and handles errors automatically.

5. NATURAL CONVERSATION: If the user asks questions unrelated to the flow,
   answer helpfully but return to the collection.
```

**Pros:**
- Closest to GCP pattern — DAG evaluation happens server-side
- Handles multi-slot batching naturally (LLM calls multiple setters → state service processes all)
- Dynamic DAG evaluation (add/remove slots at runtime)

**Cons:**
- **No preemption** — LLM always generates after tool calls. If the LLM ignores `_system_message`, it can go off-script.
- **Relies on LLM instruction following** — the "relay _system_message verbatim" rule must be followed
- State service is a separate deployable
- Webhook latency per tool call adds up with batching

### Option B: Workflow-Driven (ElvenLabs-native DAG)

**Workflow as the DAG engine.** Each slot is an `override_agent` node. Tasks are `dispatch_tool` nodes. Expression edges evaluate state and route between nodes. State is managed by simple webhook tools.

```
[start_node]
    ↓
[greeting]  (override_agent, first_message)
    ↓ expression: true
[collect_party_size]  (override_agent, additional_prompt="How many guests?")
    ↓ expression: sm.filled.party_size != null
[collect_date]  (override_agent, additional_prompt="What date?")
    ↓ expression: sm.filled.preferred_date != null
[find_times_task]  (dispatch_tool → state service /find_times)
    ↓ success
[collect_time]  (override_agent, additional_prompt="Which time?")
    ↓ expression: sm.filled.selected_time != null
[collect_name]  (override_agent)
    ↓
[collect_requests]  (override_agent)
    ↓
[book_task]  (dispatch_tool → state service /book)
    ↓ success
[confirmation]  (override_agent, speaks confirmation)
    ↓
[end_node]
```

**Expression edge example** (evaluates state from previous webhook response):
```json
{
  "type": "expression",
  "condition": "last_tool_response.result.status == 'stored'"
}
```

**Pros:**
- **Deterministic** — the workflow graph enforces progression; LLM can't skip steps
- **Tool scoping** — `additional_tool_ids` per node prevents wrong setters from firing
- **Platform-native** — no external DAG engine needed
- **Testable** — workflow paths are explicit
- No reliance on LLM faithfully relaying `_system_message` (the workflow node's `additional_prompt` controls what the agent says)

**Cons:**
- **No multi-slot batching** — each `override_agent` node expects one piece of info. User saying "table for 2 on June 20th" in the `collect_party_size` node would capture the party size but the date would need a second pass (or complex expression/LLM edge routing)
- **Rigid** — adding/removing slots requires workflow edits
- **State evaluation in expressions** — expression syntax may be limiting for complex DAG conditions

### Option C: Hybrid (Recommended)

**Workflow backbone + state-service-driven collection phases.** Use workflows for major phase transitions (greeting → collect → execute → confirm). Within the `collect` phase, use the state-service-driven pattern (Option A) for flexible multi-slot batching.

```
[start_node]
    ↓
[greeting]
    ↓ expression: true
[collect_phase]  ← ONE override_agent node with all setter tools
    │             ← System prompt includes slot-filling protocol
    │             ← State service evaluates DAG, returns _system_message
    │             ← LLM calls setters, relays _system_message
    │             ← Expression edge watches sm.status
    ↓ expression: sm.status == 'ready_for_task'
[find_times_task]  (dispatch_tool)
    ↓ success
[collect_phase_2]  ← Another collection phase for post-task slots (select time, etc.)
    ↓ expression: sm.status == 'ready_for_booking'
[book_task]  (dispatch_tool)
    ↓ success
[confirmation]
    ↓
[end_node]
```

The `collect_phase` node includes ALL setter tools and the full slot-filling prompt. The state service handles:
- Validation
- DAG evaluation (which task inputs are ready?)
- Computing `_system_message` (next question or task result)
- Setting `sm.status` to trigger expression edge transitions

When `sm.status` changes to `'ready_for_task'`, the expression edge fires and transitions out of the collection phase into the task node.

**Pros:**
- Multi-slot batching works within collection phases
- Workflow enforces high-level structure (can't skip phases)
- Dynamic DAG evaluation within phases
- Clean separation: workflow = phase transitions, state service = slot management
- Fail-safes: even if LLM goes off-script, the workflow edge gates progression

**Cons:**
- Two systems to maintain (workflow + state service)
- Expression edge conditions limited to what the platform supports

## Implementation Detail: State Service

The state service is an HTTP server with persistent storage backing (any stack — Node, Python, Go — with your choice of key-value store or relational DB).

### Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/init` | Initialize `sm` for a conversation |
| POST | `/setter/party_size` | Validate + store party size |
| POST | `/setter/preferred_date` | Validate + store date |
| POST | `/setter/selected_time` | Validate + store time |
| POST | `/setter/guest_name` | Validate + store name |
| POST | `/setter/special_requests` | Validate + store requests |
| POST | `/task/find_times` | Execute availability lookup |
| POST | `/task/book` | Execute booking |

### Key Design Decisions

1. **Setters return `_system_message`** — always. Every webhook response includes `_system_message` (the next question, error message, or task result). The system prompt instructs the LLM to relay it.

2. **DAG evaluation happens in setters** — after storing a value, the setter checks whether any task's inputs are now satisfied. If so, it fires the task inline and returns the task result as `_system_message`.

3. **`sm.status` drives workflow transitions** — the state service sets `status` to signal phase changes. Workflow expression edges watch `last_tool_response.result.status`.

4. **No `before_model_callback` needed** — the state service IS the callback. Every tool call triggers evaluation.

5. **Retry limit enforcement** — `_retries` dict tracks failures per slot/task. After `max_retries`, the state service returns an escalation message and sets `status: "escalated"`.

### Webhook Response Format

**Success (slot stored, more needed):**
```json
{
  "result": {
    "stored": true,
    "value": 4,
    "slot": "party_size",
    "status": "collecting",
    "_system_message": "What date were you thinking?",
    "filled": ["party_size"],
    "remaining": ["preferred_date", "selected_time", "guest_name", "special_requests"]
  }
}
```

**Task fired (all inputs ready):**
```json
{
  "result": {
    "task_fired": "FindAvailableTimes",
    "status": "task_complete",
    "_system_message": "Great news! I found availability at 6 PM and 7:30 PM. Which time works for you?",
    "task_result": {
      "times": ["6:00 PM", "7:30 PM"]
    }
  }
}
```

**Validation error:**
```json
{
  "result": {
    "error": true,
    "error_code": "out_of_range",
    "slot": "party_size",
    "status": "collecting",
    "_system_message": "We accept parties of 1 to 8 guests. How many will be joining you?",
    "retries_remaining": 2
  }
}
```

**Terminal (booking complete):**
```json
{
  "result": {
    "status": "complete",
    "_system_message": "You're all set! Your confirmation number is BR-48291. We'll see you on June 20th at 7 PM for a party of 4 under Garcia."
  }
}
```

## System Prompt Design for ElevenLabs

```
# Personality
You are a warm, efficient restaurant host. Friendly but professional.

# Slot Filling Protocol — CRITICAL

These rules govern your behavior. Follow them strictly:

## Tool Calling
1. After EVERY user message, identify ALL pieces of information provided and
   call ALL corresponding setter tools in the SAME response.
2. Call setters even if the value seems wrong — the system validates everything.
3. Example: "table for 2 on June 20th under Johnson" → call set_party_size,
   set_preferred_date, AND set_guest_name — all in one turn.

## Response Rules
4. After tool calls complete, relay the "_system_message" from the LAST tool
   response EXACTLY as your message to the user. Do not add, paraphrase, or
   preview future steps.
5. If no tool was called (the user is making conversation), respond naturally
   but gently return to collecting information.

## Progressive Disclosure
6. Ask ONE question at a time. Never say "after that I'll need..." or list
   remaining steps.

## Validation
7. The system returns error messages in _system_message. Relay them exactly.
   Never generate your own error message.
```

## Evaluation Strategy (mapped to ElevenLabs testing)

| GCP Eval Category | ElevenLabs Equivalent |
|-------------------|----------------------|
| Golden evals (turn-by-turn) | `tool` test type — checks exact tool calls and parameters |
| Scenario evals (end-to-end) | `simulation` test type — multi-turn with success conditions |
| Happy path | Simulation with exact task description |
| Multi-slot batching | Tool test: single user message → N tool calls expected |
| Error recovery | Simulation with invalid input, verify agent re-asks |
| NLP parsing | Tool test: "next Friday" → verify setter receives YYYY-MM-DD |

**Example tool test for multi-slot batching:**
```json
{
  "name": "Multi-slot batching: party + date + name",
  "type": "tool",
  "chat_history": [
    {"role": "user", "message": "Table for 2 on June 20th under Johnson", "time_in_call_secs": 5}
  ],
  "tool_call_parameters": [
    {
      "referenced_tool": {"id": "set_party_size", "type": "webhook"},
      "parameters": [{"path": "party_size", "eval": {"type": "exact", "value": 2}}]
    },
    {
      "referenced_tool": {"id": "set_preferred_date", "type": "webhook"},
      "parameters": [{"path": "date", "eval": {"type": "regex", "pattern": "2026-06-20"}}]
    },
    {
      "referenced_tool": {"id": "set_guest_name", "type": "webhook"},
      "parameters": [{"path": "name", "eval": {"type": "exact", "value": "Johnson"}}]
    }
  ]
}
```

## Stabilization Gotchas (ElevenLabs-specific)

### 1. LLM ignores `_system_message` and improvises

**Risk:** Without preemption, the LLM can always ignore the relay instruction.
**Mitigation:**
- Add a custom guardrail: "The agent must relay the _system_message field from the last tool response verbatim. If the agent deviates, retry with feedback."
- Use workflow `override_agent` nodes for critical transitions (confirmation, error messages) so the prompt directly controls the output.
- Test with simulation evals that verify exact phrasing.

### 2. Webhook latency stacking with batching

**Risk:** User says 4 pieces of info → 4 sequential webhook calls → cumulative latency.
**Mitigation:**
- Use a **multi-slot setter** (one webhook that accepts all fields) for related slots.
- Configure `execution_mode: "async"` for non-critical tools.
- Deploy the state service close to your users to minimize round-trip latency.
- Use a fast key-value store or relational DB for session state.

### 3. Tool docstrings break batching

**Risk:** Verbose docstrings cause LLM to focus on individual tools rather than batching. (Same as GCP gotcha #2.)
**Mitigation:** Keep webhook tool descriptions to 1-2 sentences. No validation rules, no prerequisite caveats.

### 4. Workflow expression edges can't evaluate complex state

**Risk:** Expression edges have limited syntax. Complex conditions ("are all 5 slots filled?") may not be expressible.
**Mitigation:** Have the state service compute a simple boolean/string `status` field. The expression edge checks `last_tool_response.result.status == "ready_for_task"` — a single equality check.

### 5. Conversation history context not available in state service

**Risk:** The state service only sees the current tool call parameters, not full conversation context.
**Mitigation:** Use `{{system__conversation_history}}` dynamic variable in webhook parameters when context is needed. Pass `conversation_id` in every call for state lookup.

### 6. Guardrail interference with slot filling

**Risk:** Content guardrails might block legitimate slot values (e.g., a name that triggers profanity filter).
**Mitigation:** Use custom guardrails with `execution_mode: "blocking"` and `trigger_action: "retry"` rather than ending the call. Set content thresholds conservatively.

## Reference Implementation Outline

A minimal slot-filling agent on ElevenLabs would consist of:

```
eleven_agents/
├── agents.json                    # Agent definition with workflow
├── tools.json                     # Webhook tool definitions
├── tests.json                     # Tool + simulation tests
├── state-service/
│   ├── server.js / main.py         # HTTP server config
│   ├── src/
│   │   ├── index.ts               # Request router
│   │   ├── state.ts               # sm read/write/init (DB-backed)
│   │   ├── setters.ts             # Validation logic per slot
│   │   ├── dag.ts                 # DAG evaluation, _next_question
│   │   └── tasks.ts               # Backend task implementations
│   └── schema.sql                 # DB table definitions
```

**Session table schema:**
```sql
CREATE TABLE IF NOT EXISTS sessions (
  conversation_id TEXT PRIMARY KEY,
  sm TEXT NOT NULL DEFAULT '{}',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
```

## Bottom Line

The GCP Slot Filling Pattern can be implemented on ElevenLabs with a **hybrid architecture**: ElevenLabs Workflows for phase-level structure + an external state service for slot management and DAG evaluation. The key tradeoff is losing LLM preemption — the system must rely on prompt engineering and guardrails to ensure the LLM faithfully relays system messages. Workflow expression edges provide a deterministic safety net for major transitions.
