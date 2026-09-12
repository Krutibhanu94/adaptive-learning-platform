# Adaptive Tutor Agent

A Socratic-questioning AI tutor for undergraduate CS students. The agent's one
non-negotiable rule: **it never discloses a direct answer.** Every point of uncertainty —
whether a student is stuck, bypassing, or ready to move on — is resolved by asking the
student, not by telling them. It adapts problem difficulty per student based on how much
help they actually needed to solve something, not on raw correctness alone.

## Contents

- [Architecture](#architecture)
- [Setup](#setup)
- [Usage](#usage)
- [Project structure](#project-structure)
- [Known limitations](#known-limitations)

## Architecture

```
┌─────────────────────┐        HTTP/JSON        ┌──────────────────────────────────┐
│   React frontend     │ ───────────────────────▶ │        FastAPI backend          │
│  (Vite, Tailwind,    │ ◀─────────────────────── │           (api.py)              │
│   shadcn, Monaco)    │                          └───────────────┬──────────────────┘
└──────────────────────┘                                          │
                                                                   ▼
                                                     ┌──────────────────────────┐
                                                     │   LangGraph agent        │
                                                     │      (agent.py)          │
                                                     │  conditionally-routed,   │
                                                     │  ReAct-style graph       │
                                                     └──────┬─────────┬─────────┘
                                                            │         │
                                        ┌───────────────────┘         └────────────────────┐
                                        ▼                                                   ▼
                          ┌──────────────────────────┐                     ┌──────────────────────────┐
                          │   Anthropic Claude        │                     │  Postgres                │
                          │ (probes, evaluation,      │                     │  - checkpointer (graph    │
                          │  hints, tool calls)        │                     │    state, pause/resume)  │
                          └──────────────────────────┘                     │  - students, topics,     │
                                                                            │    problems, attempts,    │
                                                                            │    skill state, logs     │
                                                                            └──────────────────────────┘
                                        │
                                        ▼
                          ┌──────────────────────────┐
                          │  Correctness checker      │
                          │  (checker.py) -- runs      │
                          │  student code in an        │
                          │  isolated Docker sandbox   │
                          └──────────────────────────┘
```

### Backend

- **`agent.py`** — the tutoring logic, as a [LangGraph](https://langchain-ai.github.io/langgraph/)
  `StateGraph`. Every student action (a chat message, a code edit, Run Test, Submit, an idle
  heartbeat) is one graph invocation. Deterministic Python routing (`route_turn`,
  `route_after_check`) decides which node handles it — never the model itself. Key nodes:
  - `probe` — asks a Socratic question (grounded in the student's message, their code, or a
    failed test run).
  - `evaluate_reasoning` — classifies a reply as genuine engagement or a bypass attempt.
  - `intervene_checkin` / `intervene_hint` / `escalate` — the idle/struggle escalation
    ladder (check-in → hint → human escalation).
  - `run_check` — runs the correctness checker via a real, model-issued tool call
    (`check_correctness`), but only ever reachable from a confirmed Run Test/Submit event.
  - `update` → `decide` → `serve` — on Submit, updates mastery/dependency scores, makes the
    tier advance/step-down decision (see `backend/CLAUDE.md`'s "Hint-cap tapering" section
    for the exact rule), and serves the next problem via another real, model-issued tool
    call (`retrieve_next_problem`) — reachable only after that decision, never freely.
  - Two tools (`check_correctness`, `retrieve_next_problem`) are real, `@tool`-registered
    LangChain tools the model genuinely calls — but each is bound to the model only inside
    the one node meant to use it, so the model can never call either outside the exact
    moment the design already permits.
  - State persists across invocations via a Postgres-backed checkpointer, keyed by
    `attempt_id` — a caller only ever needs to supply what's new about *this* turn.
- **`api.py`** — the FastAPI router. Key endpoints: `POST /students/{id}/topics/{id}/start`
  (begin or resume an attempt), `GET /attempts/{id}` (rehydrate state), and
  `POST /attempts/{id}/turn` (every other student action, keyed by `event_type`:
  `message`, `code_update`, `heartbeat`, `resume`, `run_test`, `submit`).
- **`checker.py`** — runs student code against a problem's own correctness test in an
  isolated, resource-capped Docker container (no network, memory/CPU limits, non-root,
  read-only root filesystem, auto-removed after each run). Only `check(candidate)`'s first
  failing case is ever reported (by design — a probe should ground itself in one concrete
  case, not enumerate everything at once); on a full pass, it also re-runs the candidate
  against the problem's example cases to show real output alongside them.
- **`db.py`** — all persistence: `students`, `topics`, `problems`, `problem_attempts`,
  `student_skill_state`, `interaction_log`.

### Frontend

React (Vite) + Tailwind + shadcn/ui, with Monaco as the code editor. Key pages:
`Dashboard`/`Topics` (topic list) → `TopicProblems` (per-topic problem list, with
resumability for whatever's currently in progress) → `Workspace` (the actual coding session:
problem description, code editor, Run Test/Submit, and the tutor chat, all driven by
`useTutorSession`, which owns the turn-taking, debouncing, and heartbeat logic against
`/turn`).

## Setup

### Prerequisites

- Python 3.12+
- Node.js (for the frontend)
- PostgreSQL, running locally
- Docker Desktop, running (required for the correctness checker)
- An [Anthropic API key](https://console.anthropic.com/)

### Backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Create `backend/.env`:

```
ANTHROPIC_API_KEY=your-key-here
DB_NAME=adaptive_learning
DB_HOST=localhost
DB_PORT=5432
DB_USER=your-postgres-user
DB_PASSWORD=your-postgres-password
```

Create the database and load the schema:

```bash
createdb adaptive_learning
psql adaptive_learning < db/schema.sql
```

Seed topics and a test student, then load problems from the
[LeetCodeDataset](https://huggingface.co/datasets/newfacade/LeetCodeDataset) (this
downloads the dataset on first run):

```bash
cd backend
python scripts/load_students_and_topics.py
python scripts/load_problems.py
```

Build the sandbox image used by the correctness checker (it also builds itself
automatically on first use if you skip this):

```bash
docker build -t adaptive-tutor-sandbox:latest sandbox/
```

Start the backend:

```bash
cd backend/src
uvicorn main:app --reload
```

The API is now at `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The app is now at `http://localhost:5173`.

## Usage

1. Open `http://localhost:5173`. The app currently runs as a single hardcoded test
   student (see [Known limitations](#known-limitations)).
2. Pick a topic, then a problem — **Start Problem** opens a fresh attempt in the
   Workspace, or resumes one already in progress.
3. Talk through your approach with the tutor before writing code — it won't let you
   Submit until you've genuinely engaged with at least one probe. It will proactively
   check in if you go quiet, and offer hints (capped per attempt) if you seem stuck.
4. **Run Test** checks your code against the problem's test suite without concluding the
   attempt. **Submit** concludes it — pass or fail, it always records the result, updates
   your mastery/dependency scores, decides whether you advance a tier, and serves the next
   problem.
5. To exercise the correctness checker directly, outside the full conversation flow:
   ```bash
   cd backend
   python scripts/try_checker.py "Two Sum" path/to/solution.py
   ```

## Project structure

```
backend/
  src/
    agent.py       # LangGraph tutoring logic
    api.py         # FastAPI routes
    checker.py     # sandboxed correctness checker
    db.py          # persistence
    config.py      # env/model/DB config
    main.py        # FastAPI app entrypoint
  db/schema.sql     # Postgres schema
  sandbox/          # Docker image for the correctness checker
  scripts/          # seeding/loading/manual-test utilities
  CLAUDE.md         # living design doc -- the source of truth for backend behavior,
                     # including every design decision and bug fix's rationale
frontend/
  src/
    pages/          # Dashboard, Topics, TopicProblems, Workspace, CodeEditor, Tutor, ...
    hooks/          # useTutorSession -- owns all /turn traffic
    context/        # student context (currently a hardcoded stand-in for auth)
    components/ui/  # shadcn components
```

## Known limitations

- **No concept-note retriever.** A planned RAG tool (Chroma + Voyage AI over OpenDSA
  chapters) for grounding hints in course material isn't built yet.
- **No real authentication.** The frontend and backend both currently hardcode a single
  test student (`student_id = 1`).
- **No curriculum-driven topic unlocking.** All topics are open regardless of a course
  schedule; a performance-based unlock scheme was considered and explicitly rejected.

See `backend/CLAUDE.md` for the full design history, every real bug found and fixed along
the way, and the reasoning behind each non-obvious decision.
