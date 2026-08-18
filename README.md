# CPI AI Assistant

An AI assistant for SAP Integration Suite (CPI) that reads real integration flow
artifacts from Git and answers questions grounded in actual iFlow structure —
not guesses. Single tenant, multiple CPI packages.

## Why this exists

Most "CPI chatbots" just answer generic questions. This project's goal is an
assistant that understands *your specific* integration landscape: what each
iFlow actually does, what it depends on, what breaks if you change something,
and eventually, proactive alerts before things go wrong. See the full
capability roadmap this was scoped against (19 capability groups, phased
rollout) — captured in project planning, not repeated here.

## Architecture

Git repo (CPI packages)
│
▼
┌─────────────────┐
│ Parser Layer │ src/parser/iflow_parser.py
│ (.iflw → JSON) │ Extracts BPMN structure: steps, router conditions,
└────────┬─────────┘ message flows, system connectivity
│
▼
┌─────────────────┐
│ Resolver Registry│ src/parser/resolver_registry.py
│ (by extension) │ .wsdl → wsdl_resolver.py
└────────┬─────────┘ .mmap → mapping_resolver.py
│ .groovy → groovy_summarizer.py (manual-cache based)
▼
┌─────────────────┐
│ output/*.json │ One normalized IFlowArtifact per package
└────────┬─────────┘ (pydantic schema: src/models/schema.py)
│
▼
┌─────────────────┐
│ Neo4j Loader │ src/graph/loader.py
│ (graph DB) │ Idempotent per-IFlow reload, shared System/Resource nodes
└──────────────────┘


**Design principle carried through the whole build:** never guess a file
format's schema — inspect the real file first, write the parser against
confirmed structure, and treat "can't confidently parse this" as a visible
warning, never a silent wrong answer.

## What's actually working (validated against real data, not assumed)

- **Parser** (`src/parser/iflow_parser.py`) — parses all 11 packages cleanly.
  Extracts every BPMN node type (not just processing steps — start/end
  events and gateways too), sequence flow edges with router conditions,
  message flows with direction/protocol/endpoint, and participant systems.
  Validated line-by-line against the Integration Suite designer canvas for
  `com.sap.scenarios.s42c4c.attachment.replicate`.

- **Resolvers** (`src/parser/*_resolver.py`, `groovy_summarizer.py`) —
  - WSDL: extracts `message`/`part` definitions (these WSDLs don't define
    `portType`/`service` — confirmed by inspection, not assumed)
  - Mapping (`.mmap`): extracts field-level source→target bindings from
    SAP's `tr:XiTrafo` brick structure, flags non-trivial transformations
    as `"complex"` rather than guessing their logic
  - Groovy: **no automated summarization** (no Anthropic API key in use —
    avoiding API cost). Uses a manual content-hash cache instead:
    `groovy_summarizer.py` checks `output/.groovy_cache/<sha256>.json`;
    if missing, it reports the expected path rather than crashing. Cache
    files are currently populated by manual/Copilot analysis, not a live
    API call. Only 2 Groovy scripts exist across all 11 packages — both
    cached and validated (one trivial logging script, one genuine
    business-logic deduplication rule).
  - Registry pattern (`resolver_registry.py`) means adding a new file type
    (XSLT, Value Mapping, etc.) later is a new resolver + one registry
    line — not a rewrite.

- **Neo4j graph** (`src/graph/loader.py`, `neo4j_client.py`) — all 11
  packages loaded. Schema:

(:Package)
(:IFlow {id, version})-[:PART_OF]->(:Package)
(:Step {id, name, bpmn_type, activity_type})-[:BELONGS_TO]->(:IFlow)
(:Step)-[:NEXT {condition}]->(:Step)
(:Step)-[:USES]->(:Resource {filename, kind, resolved, purpose, complexity})
(:Step)-[:CALLS {direction, component_type, address}]->(:System {name})

  Idempotent per-IFlow reload (safe to re-run after a Git update).
  `System`/`Resource` nodes are shared/deduplicated across packages via
  `MERGE`. Validated: 113 Steps (no dedup expected), 15 Resources, 11
  distinct Systems (deduplicated correctly from a raw 31). First real
  landscape query already answered: **S4 and C4C are touched by 10 of 11
  packages each** — confirms this is fundamentally an S4↔C4C replication
  landscape.

## What's NOT built yet

- No natural-language query layer. Right now, answering a question means
  writing Cypher by hand in Neo4j Browser. The actual "ask a question, get
  an answer" assistant experience — the whole point of the project — is
  the next phase.
- No automated Groovy summarization (would need a live Anthropic API key;
  currently avoided to keep cost at $0 while validating the approach).
- No Git webhook / automatic re-ingestion on push — parsing is run
  manually against a local clone.
- No deployment/runtime data (Phase 5+ in the original roadmap) — this is
  purely static Git-artifact analysis so far.

## Project structure

cpi-ai-assistant/
├── data/raw_artifacts/CPI-NorthWind/ # cloned source repo (gitignored)
├── output/ # parsed JSON, one file per package
│ └── .groovy_cache/ # manually-populated script summaries
├── src/
│ ├── parser/ # iflow_parser.py, resolver_registry.py, resolvers
│ ├── models/schema.py # IFlowArtifact pydantic model
│ ├── graph/ # neo4j_client.py, loader.py
│ └── enrichment/ # (reserved for future LLM-based enrichment)
├── tests/
├── .env # local secrets, gitignored — copy from .env.example
└── requirements.txt


## Setup (from scratch)

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
Copy-Item .env.example .env   # then fill in real Neo4j credentials
```

Requires Neo4j Desktop running locally with a DBMS started
(`bolt://localhost:7687` by default).

## Running the pipeline

```powershell
# Parse a single package
python -m src.parser.iflow_parser data\raw_artifacts\CPI-NorthWind\<package-folder>

# Parse all packages, print summary table
python -m src.parser.run_all

# Load all parsed output into Neo4j (idempotent, safe to re-run)
python -m src.graph.loader
```

## Next planned step

A thin natural-language query layer: predefined tool-calling functions
(not free-form LLM-generated Cypher, for safety/predictability) covering
the first 3-4 capability questions — "what does this iFlow do," "what
systems does it talk to," "what depends on this resource" — wired to an
LLM that picks the right function and turns the graph result into a
readable answer.