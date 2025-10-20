## Architecture and Refactor Recommendations

This document outlines concrete improvements to evolve the current RAG-based SSS Tutor into a robust, maintainable, and production-ready system. It is tailored to the existing codebase (`rag.py`, `dataLoading.py`, `main.py`) and your runtime setup.

### Guiding Principles
- Keep core concerns separate: ingestion, retrieval, generation, API, configuration.
- Prefer clear, explicit code over clever abstractions.
- Make failures observable and recoverable; add health, metrics, and structured logs.
- Design for incremental scalability: local dev -> single-node -> containerized -> cloud.

---

## 1) File/Module Structure (Proposed)

Current files are tightly coupled. The following layout improves cohesion and separation of concerns while staying close to your current code:

```
learning_Platform/
├── app/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── dependencies.py              # shared deps (LLM, vectorstores, settings)
│   │   ├── routers/
│   │   │   ├── health.py                # /health, /status endpoints
│   │   │   ├── lessons.py               # /lesson endpoints
│   │   │   └── topics.py                # /topics
│   │   └── server.py                    # FastAPI app factory + lifespan
│   ├── core/
│   │   ├── config.py                    # Settings via pydantic-settings
│   │   ├── logging.py                   # structlog/loguru setup
│   │   └── errors.py                    # domain error types, exception handlers
│   ├── rag/
│   │   ├── __init__.py
│   │   ├── llm.py                       # initialize_hf_llm, model wrappers
│   │   ├── prompts.py                   # prompt templates & builders
│   │   ├── retrieval.py                 # retriever abstraction
│   │   ├── pipeline.py                  # generate_lesson orchestration
│   │   └── components.py                # create_rag_components
│   ├── data/
│   │   ├── ingestion.py                 # PDF loaders, chunkers
│   │   ├── vectorstore.py               # build/load/init logic, metadata mgmt
│   │   └── subjects.py                  # get_available_subjects
│   └── cli/
│       └── build.py                     # CLI to rebuild index per subject/all
├── curriculum_data/
├── vectorstores/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── scripts/
│   ├── start_dev.sh
│   └── start_prod.sh
├── main.py                              # thin entrypoint to app.api.server
├── README.md
├── RECOMMENDATIONS.md
├── requirements.txt
└── .env.example
```

Key outcomes:
- Testability improves with smaller modules and explicit boundaries.
- API can evolve independently from RAG internals.
- Easier to swap LLM provider or embeddings.

---

## 2) Code-Level Refactors

### 2.1 Configuration management
- Use `pydantic-settings` (part of pydantic v2) to centralize settings:
  - `HUGGINGFACEHUB_API_TOKEN`, model id, temperature, max_new_tokens, chunk sizes, k, paths.
  - Support env overrides with defaults for local dev.
- Provide `.env.example` with all required/optional keys.

### 2.2 Logging and observability
- Replace print statements with a structured logger (e.g., `structlog` or `loguru`).
- Add request/response logging middleware (sanitize secrets). Correlate logs with request IDs.
- Emit timing metrics and counters (Prometheus FastAPI middleware) for: vectorstore build time, retrieval time, LLM latency, token counts, cache hits/misses.

### 2.3 Error handling
- Define domain errors (e.g., `VectorstoreMissing`, `ModelInitializationError`, `InvalidSubjectError`) and register global exception handlers in FastAPI.
- Make `/status` reflect partial readiness (e.g., LLM ready, subjects discovered, per-subject components loaded).

### 2.4 RAG pipeline clarity
- Split responsibilities:
  - `retrieval.py`: retrieve contexts given a query; configurable `k`, filters, mmr.
  - `prompts.py`: prompt templates and builders; make WAEC-specific knobs explicit.
  - `pipeline.py`: orchestrates retrieval + generation; returns structured `Lesson` object.
- Return rich data: `lesson_text`, `citations` (source doc ids, page ranges), `usage` (tokens, latency).

### 2.5 Type safety and models
- Add explicit Pydantic models for internal exchanges: `LessonRequest`, `Lesson`, `SourceChunk`, `UsageStats`.
- Use `Literal` types sparingly; prefer enums for `SSSLevel` and `LearningPace`.

### 2.6 Async boundaries
- Keep CPU/IO heavy ops off the event loop: vectorstore I/O, PDF parsing, and LLM calls should run in thread/process pools via `run_in_executor` or `async-to-sync` wrappers.
- Consider a background job queue (RQ/Celery) for long builds or batch lesson generation.

### 2.7 Prompt engineering hygiene
- Parameterize WAEC fidelity requirements (number of solved examples, MCQs, format) in config.
- Keep prompts versioned and tested (unit tests on template rendering with sample inputs).

### 2.8 Data layer improvements
- Make chunking params configurable per subject if desired (science/math may differ).
- Persist per-chunk metadata: subject, pdf_name, page, hash; include in citations.
- Store a manifest of processed files to detect partial changes quickly.

---

## 3) Performance and Reliability

### 3.1 Caching and warmup
- Cache `HuggingFaceEmbeddings` per process. Avoid re-instantiation on hot path.
- Warm critical subjects on startup (configurable) to reduce first-request latency.

### 3.2 Vectorstore rebuild strategy
- Expose a CLI to rebuild one/all subjects with progress and dry-run mode.
- Support `force_rebuild` per subject via API and admin token.

### 3.3 Retrieval quality
- Experiment with MMR, hybrid search (sparse + dense, e.g., BM25 + FAISS), and higher `k` with re-ranking (e.g., `bge-reranker-base`).
- Add guardrails: if retrieval returns empty, fallback to broader query or subject-level summary.

### 3.4 LLM robustness
- Add timeouts and retries with backoff for HF endpoint calls.
- Surface partial results and a friendly error if token limits are hit; split generation into sections when needed.

---

## 4) API and Product Features

### 4.1 API enhancements
- Pagination and streaming: offer a streaming endpoint for section-by-section lesson generation.
- Idempotency keys on `/lesson` to dedupe client retries.
- Include `citations` in the response with source metadata.
- Add `/subjects` and `/subjects/{subject}/rebuild` (admin-protected) endpoints.

### 4.2 Content safety and quality
- Add a lightweight content filter/pass (e.g., regex checks) for profanity or irrelevant output.
- Add deterministic evaluation prompts to self-check lesson correctness and alignment with syllabus.

### 4.3 Frontend (future)
- Simple React/Next.js UI with:
  - Subject/level/pace selectors, topic input with suggestions.
  - Markdown viewer with copy/export to PDF.
  - Source citations panel with page thumbnails.

---

## 5) Security and Compliance
- Use API keys or OAuth for admin operations (rebuilds, config changes).
- Never log secrets. Mask tokens in logs and `/status`.
- Add CORS allowlist per environment; avoid `*` in production.
- Validate inputs rigorously with Pydantic (lengths, enums) and rate-limit `/lesson`.

---

## 6) Testing Strategy

### 6.1 Unit tests
- Prompt builders: render with fixtures and snapshot-test outputs.
- Retrieval: mock FAISS to test query->doc selection logic.
- Config: load precedence (env, .env, defaults).

### 6.2 Integration tests
- Spin up an ephemeral vectorstore with small sample PDFs.
- Test `/lesson` happy path and edge cases (no docs, empty retrieval).

### 6.3 E2E tests
- Run FastAPI with test client, assert schema and non-empty lesson sections.

Add `pytest`, `pytest-asyncio`, `httpx` to dev requirements and create a GitHub Actions workflow to run tests on PRs.

---

## 7) Deployment & DevEx

### 7.1 Containerization
- Dockerfile with multi-stage build (poetry or pip). Add healthcheck.
- Use environment-based config; mount `curriculum_data` and `vectorstores` volumes.

### 7.2 CI/CD
- Lint (ruff/flake8), format (black), type-check (mypy), test.
- Build and push Docker image on `main`; deploy to your target environment.

### 7.3 Runtime
- `uvicorn` with `--workers` > 1, behind `nginx`/`traefik`.
- Add `PROMETHEUS_MULTIPROC_DIR` if using multi-process metrics.

---

## 8) Concrete Edits You Can Make Now

1) Replace prints with structured logs in `rag.py` and `main.py`.
2) Introduce `Settings` class:
   - model id, temperature, max tokens, retrieval k, chunk sizes, paths.
3) Add `/subjects` and include `citations` array in `/lesson` response.
4) Add retries/timeouts around HF calls and vectorstore I/O.
5) Add simple Prometheus metrics middleware and `/metrics` endpoint.
6) Provide `.env.example` and document all config in `README.md`.

---

## 9) Example Settings Skeleton (pydantic)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    huggingface_token: str
    hf_repo_id: str = "mistralai/Mistral-7B-Instruct-v0.3"
    temperature: float = 0.3
    max_new_tokens: int = 800
    curriculum_root: str = "curriculum_data"
    vectorstore_root: str = "vectorstores"
    retrieval_k: int = 3
    cors_allow_origins: list[str] = ["*"]

    class Config:
        env_file = ".env"
```

---

## 10) Roadmap

- Short-term (1–2 weeks)
  - Refactor into `app/` modules, add `Settings`, structured logging, and tests.
  - Add citations in lessons and `/subjects` endpoints.
  - Containerize and add CI (lint+test) on PRs.

- Mid-term (3–6 weeks)
  - Hybrid retrieval (BM25 + FAISS) and reranking.
  - Streaming generations; UI with export-to-PDF; admin rebuild endpoints.
  - Metrics dashboards and error monitoring.

- Long-term (6–12 weeks)
  - Multi-tenant subjects and roles; authN/Z.
  - Offline batch generation and lesson libraries with versioning.
  - Evaluate swap to local inference or other hosted LLMs; cost controls.

---

By implementing the structure and practices above, the system will be more maintainable, observable, and scalable, positioning it strongly for hackathon and production use.

---

## 11) Feature Additions (High-Impact Ideas)

- Student experience
  - Personalized study plans: auto-generate weekly learning plans per subject, level, and pace.
  - Lesson bookmarking and history: save, tag, and revisit generated lessons; resume where left off.
  - Interactive practice: auto-graded MCQs with explanations; timed quizzes; difficulty scaling.
  - Spaced repetition: convert key concepts into flashcards; schedule via SM-2.
  - Explanations at multiple depths: toggle brief/standard/deep dive modes.
  - Multimedia enrichment: diagrams (ASCII/SVG), formula rendering, optional short audio summaries.

- Teacher/Admin tools
  - Class sets: generate lesson variants for different cohorts; bulk assign practice sets.
  - Rubrics and marking schemes: auto-generate marking guides for WAEC-style questions.
  - Progress dashboards: per-student mastery by topic; exportable CSV/PDF reports.
  - Curriculum coverage map: track which syllabus topics are covered/remaining.
  - Review and approve workflow: teachers can edit/tweak lessons before publishing to students.

- Pedagogy and alignment
  - Outcome-based objectives: tie each lesson to explicit learning outcomes and prerequisites.
  - Misconception handling: library of common misconceptions per topic; targeted clarifications.
  - Adaptive remediation: if quiz scores are low, recommend remedial mini-lessons.
  - Alignment checker: auto-validate generated content against syllabus keywords and outcomes.

- Retrieval and content quality
  - Citations and page previews: show source PDF name, page, quote snippets; link to page.
  - Hybrid retrieval: BM25 + FAISS + reranking to improve factual grounding.
  - Sectional generation: generate Intro, Theory, Examples, Practice independently with guardrails.
  - Hallucination checks: post-generation consistency prompts; fact cross-check prompts.

- Collaboration
  - Shared lesson libraries: departments can curate canonical lessons; versioning and approvals.
  - Comments and suggestions: inline comments on lesson sections; change history.

- Accessibility and localization
  - Low-bandwidth mode: text-only, compressed assets, minimal requests.
  - Offline packs: pre-generate lesson bundles and practice sets for offline schools.
  - Localization: English + local languages; configurable terminology and examples.
  - Accessibility: screen-reader friendly structure, dyslexia-friendly fonts in UI, ARIA landmarks.

- Analytics and insights
  - Learning analytics: time-on-task, item analysis for MCQs, distractor effectiveness.
  - Content analytics: which topics lead to most confusion; improve prompts and materials.

- Platform and integrations
  - LMS integration: Google Classroom, Moodle; roster sync and assignment return.
  - Authentication and roles: students, teachers, admins; SSO where possible.
  - Export options: PDF, DOCX, HTML, Markdown; shareable links with access control.

- Cost and performance
  - Token budgeting: section-wise generation, summaries for long outputs, truncation policies.
  - Model fallback: switch to cheaper models off-peak; upgrade for exam seasons.
  - Background jobs: async rebuilds, batch lesson generation, nightly refresh.

- Monetization and sustainability (optional)
  - Freemium tiers: limited generations per day; premium includes analytics and advanced retrieval.
  - Institutional licensing: per-school dashboards and support SLAs.

- Future R&D ideas
  - Student modeling: estimate mastery per skill; Bayesian knowledge tracing.
  - Generative diagrams/equations: integrate with tools for math rendering and figure generation.
  - Speech interface: voice-based tutoring; TTS for accessibility and mobile use.

### 11.1 Curriculum Expansion (More Subjects and JSS Levels)

- New subjects: add PDFs under `curriculum_data/<NewSubject>/` and rebuild vectorstores; the discovery mechanism (`get_available_subjects`) will pick them up automatically.
- Additional classes/levels: extend level enums and UI to include `JSS 1`, `JSS 2`, `JSS 3` alongside `SSS 1–3`. Ensure prompts accept `{level}` generically and retrieval queries include the appropriate level token (e.g., “JSS 2 English ...”).
- Per-level tuning: allow per-level chunking parameters and retrieval `k`; maintain separate evaluation sets for JSS vs SSS.
- Roadmap tie-in: expose `/subjects` and support per-subject/level rebuilds; include JSS topics in diagnostics and learning paths.

---

## 12) Product Flow Aligned to Onboarding and Daily Sessions (No Chatbot)

This section translates your intended user journey into concrete system design: endpoints, data models, adaptive logic, and UI behavior. It strictly avoids chatbot interactions and instead uses guided hints, worked examples, and adaptive content regeneration.

### 12.1 Onboarding & Assessment

Step 1: Registration
- Inputs: name, grade (7–12), subjects
- System: create student profile; schedule diagnostic per chosen subjects
- Endpoint: `POST /users` → returns `user_id`

Step 1b: Initial Diagnostic (adaptive)
- Maths: 10 questions (difficulty ramps easy → hard)
- English: reading comprehension + grammar assessment
- Science: concept understanding questions
- Endpoints:
  - `POST /diagnostics/start` { user_id, subject }
  - `POST /diagnostics/answer` { diagnostic_session_id, question_id, answer }
  - `POST /diagnostics/finish` → computes baseline proficiency and knowledge gaps
- Output: baseline per subject, e.g. mastery 0–100%, skill tags, detected pace

Step 2: Profile Creation
- Determine learning pace: slow/moderate/fast
- Identify topic-level gaps (from diagnostic)
- Generate personalized learning path (ordered topics with initial mastery and review dates)
- Endpoint: `POST /profiles/{user_id}/learning-path/generate` → returns `learning_path_id`

Data models (sketch)
- User: id, name, grade, subjects[], pace, created_at
- DiagnosticSession: id, user_id, subject, items[], started_at, finished_at
- DiagnosticItem: id, subject, skill_tag, difficulty, correct_answer
- DiagnosticResult: session_id, score, mastery_by_skill{}, pace_suggestion
- LearningPath: id, user_id, subject, items[] (topic_id, planned_date, mastery)

### 12.2 Daily Learning Session

Student Dashboard
- Shows today’s lessons and mastery per subject
- Endpoint: `GET /dashboard/{user_id}` → aggregates from learning path and mastery store

Start Lesson Flow (example: English → Active vs Passive Voice)
1) Retrieval
   - RAG fetches definitions, rules, examples from curriculum PDFs
   - Internal call: `retrieval.get_context(subject, topic, k)`
2) Generation
   - Generate lesson notes simplified to the student’s reading level
   - Include 3 worked examples using local context (e.g., Freetown, Leones)
   - Prepare 5 practice exercises at the student’s current difficulty band
   - Endpoint: `POST /lessons/generate` { user_id, subject, topic, level=SSS 1/2/3, pace }
   - Response: { lesson_id, lesson_notes_md, examples[], exercises[] }
3) Presentation
   - UI renders markdown lesson with [Got it!] [Get Hint] [Next] controls
   - No chatbot: hints come from precomputed explanations and worked examples
4) Practice & Hints
   - Endpoint: `POST /exercises/attempt` { lesson_id, exercise_id, answer }
   - If incorrect: return step-by-step hint or simpler sub-problem; allow one more attempt
   - If struggling (multiple incorrect): regenerate simpler content and surface a worked example
5) Adaptive Response
   - Correct 3 in a row: increase difficulty of remaining items for this topic
   - Incorrect ≥2: show guided breakdown and easier follow-up item
   - Incorrect ≥3: auto-trigger remediation mini-lesson; flag teacher notification
   - Endpoints:
     - `POST /lessons/remediate` { user_id, subject, topic, reason }
     - `POST /notifications/teacher` { user_id, subject, topic, status }
6) Mastery Update & Scheduling
   - Update mastery and schedule next review based on performance (spaced repetition)
   - Endpoint: `POST /mastery/update` { user_id, subject, topic, delta }
   - Endpoint: `POST /learning-path/reflow` { user_id } → reorders upcoming items

Data models (sketch)
- Lesson: id, user_id, subject, topic, level, pace, content_md, examples[], exercises[]
- Exercise: id, stem, options?, answer_schema, difficulty, skill_tags[]
- Attempt: id, user_id, lesson_id, exercise_id, answer, correct, hints_used, latency
- Mastery: user_id, subject, topic, score (0–100), last_seen, next_review_at

### 12.3 Adaptive Algorithm (Simplified)

- Initialization
  - Set starting difficulty band from diagnostic (e.g., band 2 of 5)
- Per attempt
  - If 3 consecutive correct: band = min(band+1, max)
  - If 2 consecutive incorrect: band = max(band-1, min); inject worked example
  - If 3+ incorrect total on topic: trigger remediation mini-lesson; notify teacher
- Mastery update
  - mastery = clamp(mastery + f(correctness, difficulty, hints_used, latency), 0..100)
  - schedule next review using spaced repetition based on mastery and stability

### 12.4 RAG Adjustments to Support Flow

- Retrieval
  - Allow per-topic query templates (e.g., “SSS {level} {subject} syllabus: {topic} rules + examples”)
  - Return citations (pdf_name, page, snippet) for transparency
- Generation
  - Parameterize reading level and local context variables (names, places, currency)
  - Produce: Introduction, Rules, Worked Examples (3), Practice (5) as separate sections
  - Keep strict token budget per section to avoid truncation
- Remediation
  - Predefine remediation prompt variants per subject (simpler language, scaffolded steps)

### 12.5 API Summary (Minimal Set)

- Users: `POST /users`, `GET /users/{id}`
- Diagnostics: `POST /diagnostics/start`, `POST /diagnostics/answer`, `POST /diagnostics/finish`
- Profiles/Learning Path: `POST /profiles/{user}/learning-path/generate`, `POST /learning-path/reflow`
- Lessons: `POST /lessons/generate`, `POST /lessons/remediate`
- Exercises: `POST /exercises/attempt`
- Mastery: `POST /mastery/update`, `GET /mastery/{user}/{subject}`
- Dashboard: `GET /dashboard/{user}`
- Notifications: `POST /notifications/teacher`

### 12.6 UI Notes

- Replace free-form chat with:
  - Contextual “Get Hint” button per exercise with tiered hints
  - Inline worked examples toggle beneath the relevant concept
  - “Regenerate simpler explanation” button when struggling
- Keep the dashboard concise: today’s lessons, mastery badges, and quick start

This design grounds onboarding and daily learning in clear endpoints and data flows, ensures adaptive behavior without a chatbot, and keeps the system aligned to the SSS syllabus via RAG with citations and local context.

---

## 13) Migration Plan: Current Codebase → Proposed Architecture

This plan maps your existing files to the proposed structure and provides a practical execution order.

### 13.1 File Mapping (Current → Target)

- `dataLoading.py` →
  - `app/data/vectorstore.py` (build/load/init FAISS, metadata)
  - `app/data/ingestion.py` (PDF load, chunking)
  - `app/data/subjects.py` (discover available subjects)

- `rag.py` →
  - `app/rag/llm.py` (initialize_hf_llm)
  - `app/rag/prompts.py` (templates and builders)
  - `app/rag/retrieval.py` (retriever abstraction, k/MMR)
  - `app/rag/components.py` (create_rag_components)
  - `app/rag/pipeline.py` (generate_lesson orchestration; remediation & sectional gen)

- `main.py` →
  - `app/api/server.py` (FastAPI app factory, lifespan, CORS)
  - `app/api/routers/health.py` (`/`, `/health`, `/status`)
  - `app/api/routers/lessons.py` (`/lessons/generate`, `/lessons/remediate`)
  - `app/api/routers/topics.py` (`/topics`, `/subjects`)
  - Future routers: diagnostics, profiles, learning-path, mastery, dashboard, notifications

- New core
  - `app/core/config.py` (pydantic-settings)
  - `app/core/logging.py` (structured logging)
  - `app/core/errors.py` (exception types + handlers)

- Entry point
  - `main.py` becomes a thin runner that imports `app/api/server.py`.

### 13.2 Execution Order (Incremental)

1) Core setup
   - Add `app/core/config.py` (Settings) and wire `.env`/`.env.example`.
   - Add `app/core/logging.py` and replace prints gradually.

2) Data layer split
   - Move subject discovery, FAISS build/load, metadata into `app/data/*`.
   - Keep public functions compatible while refactoring imports in place.

3) RAG split
   - Extract `initialize_hf_llm` → `app/rag/llm.py`.
   - Move prompt template → `app/rag/prompts.py`.
   - Create `retrieval.py`, `components.py`, and `pipeline.py`; route `generate_lesson` through `pipeline`.

4) API modularization
   - Create `app/api/server.py` and `routers/health.py`, port `/`, `/health`, `/status`.
   - Create `routers/lessons.py`, port `/lesson` → `/lessons/generate`; add citations in response.
   - Add `routers/topics.py` for `/topics`, `/subjects`.

5) Product flow endpoints (minimal)
   - Add diagnostics: `start`, `answer`, `finish` (scaffold only).
   - Add profiles/learning-path generate and reflow (scaffold only).
   - Add mastery update and dashboard aggregates (scaffold only).

6) Testing and CI
   - Introduce `tests/` with unit tests for prompts and retrieval; FastAPI test client for endpoints.
   - Add formatting/linting/type-check in CI.

7) Deployment
   - Add Dockerfile and scripts; configure env-based settings; health and metrics.

### 13.3 Data and Storage Notes

- Keep FAISS and PDF flow as-is initially; extract clean interfaces for later swaps.
- For product features (users, diagnostics, mastery, learning paths):
  - Start with SQLite via SQLModel or SQLAlchemy; plan for Postgres in production.
  - Define tables: users, diagnostics, diagnostic_items, diagnostic_results, lessons, exercises, attempts, mastery, learning_paths, learning_path_items.
- Add migrations (Alembic) once schemas stabilize.

### 13.4 De-risking Tips

- Maintain compatibility layers during refactor (old function names import from new modules).
- Move one slice at a time; add tests before relocating logic.
- Feature-flag new endpoints; keep existing `/lesson` operational until parity is reached.
