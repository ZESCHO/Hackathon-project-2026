# Secure Agentic-AI Platform

A campus service platform where an AI agent understands a request,
plans the steps, retrieves verified institutional information, and
routes anything consequential to a human before it happens.

Built for the 2026 hackathon.

---

## What it does

Students describe what they need in plain English. The agent:

1. **Understands** the request and collects the details it needs,
   asking only for what is genuinely missing.
2. **Answers questions** using only the verified knowledge base in
   `Src/knowledge_base/`, with citations. If the answer is not in
   there, it says so instead of guessing.
3. **Plans** the steps before doing anything, and stores the plan so a
   reviewer can see the whole sequence before approving it.
4. **Checks policy** against the knowledge base, citing the rule it
   applied — restricted labs, notice periods, priority and escalation.
5. **Waits for a human.** Nothing consequential happens until a
   reviewer approves it.
6. **Executes** the approved workflow, creating the real record: a
   maintenance ticket, a laboratory booking, a certificate, or a routed
   grievance.
7. **Audits** every step, including the ones that were blocked.

Four services are supported: certificates, maintenance tickets,
laboratory bookings and grievance escalation.

---

## Running it

Requires [Ollama](https://ollama.com) with `qwen3:8b` pulled, and
Python 3.13+.

```bash
cd Src
python -m venv venv
venv/bin/pip install -r requirements.txt
ollama pull qwen3:8b
venv/bin/python app.py
```

Then open http://127.0.0.1:5000

An administrator account is created on first run. Its credentials are
printed to the terminal — they are deliberately not written down here.
**Change the password before showing this to anyone.**

### Configuration

`Src/.env` holds local settings. None of them are secrets you need to
obtain; they only point at your own machine.

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | dev value | Flask session signing |
| `OLLAMA_HOST` | `http://localhost:11434` | Where the model is served |
| `OLLAMA_MODEL` | `qwen3:8b` | Which model to use |
| `OLLAMA_TIMEOUT` | `120` | Seconds before a model call gives up |
| `DATABASE_URI` | `sqlite:///database.db` | Database location |

---

## Testing

```bash
cd Src
venv/bin/python smoke_test.py
```

Runs 40+ end-to-end checks against a temporary database, so it never
touches your development data. It needs Ollama running, and takes a
couple of minutes because it makes real model calls.

---

## Layout

```
Src/
  app.py                  routes and the request lifecycle
  smoke_test.py           end-to-end checks
  knowledge_base/         verified institutional policy (the only
                          source the agent may answer from)
  app/
    ai_agent.py           understanding, field collection, grounded answers
    ollama_client.py      local model client
    rag/retriever.py      BM25 search over the knowledge base
    workflows/planner.py  builds the plan and applies policy rules
    workflows/executor.py runs an approved plan, audits each step
    tools/actions.py      the only code that changes institutional state
    models/               database models
    db_migrate.py         adds new model columns to an existing database
  templates/  static/     interface
```

---

## Design rules

These are the constraints the code is built around. They are worth
knowing before changing anything.

- **The agent never states policy from memory.** Every institutional
  answer comes from a retrieved snippet and cites it. No snippet, no
  answer.
- **A citation must be real.** The agent can only cite an id that
  retrieval actually returned, so it cannot make an answer look
  verified by inventing a source.
- **Approval is checked twice.** The route checks it, and every tool in
  `app/tools/actions.py` checks it again rather than trusting its
  caller.
- **Ask rather than invent.** If a required detail is missing, the
  agent asks for it. Extracted values that merely echo the user's
  message back are rejected.
- **A failed step undoes the run.** Partial execution is rolled back
  and reported as undone.
- **English only.** Messages in other languages are declined, not
  half-understood — a misread service request becomes a real action.

---

## Status

The core loop works end to end: understand, plan, check policy, wait
for approval, execute, audit.

Known gaps, in rough priority order:

- No CSRF protection on any form, including approve and execute.
- `SECRET_KEY` falls back to a hardcoded development value.
- The default admin password is reset on every startup.
- `app/routes/`, `app/security/`, `app/agent/agent.py` and `config.py`
  are not wired into the running application and need either
  integrating or deleting.
- The audit trail is not tamper-evident.
