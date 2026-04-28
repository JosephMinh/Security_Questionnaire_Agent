# Security Questionnaire Agent

Local demo scaffold for a Streamlit workflow that answers one curated security questionnaire from one bundled evidence pack, shows source-backed evidence, and exports reviewer handoff files.

## Architecture
```mermaid
flowchart TB
    subgraph Seeds["Curated seed assets (checked into the repo)"]
        SQ["seed_data/questionnaire/<br/>Demo_Security_Questionnaire.xlsx"]
        SE["seed_data/evidence/<br/>Markdown policies + SOC 2 PDF"]
    end

    subgraph Setup["Workspace preparation and reset"]
        GDD["generate_demo_data.py<br/>prepare_demo_workspace()<br/>validate_runtime_workspace()"]
    end

    subgraph Workspace["Runtime workspace under data/"]
        DQ["data/questionnaires/<br/>runtime questionnaire copy"]
        DE["data/evidence/<br/>runtime evidence pack"]
        DM["data/workspace_manifest.json<br/>workspace hash + file inventory"]
        DC["data/chroma/<br/>persistent Chroma collection"]
        DO["data/outputs/<br/>Answered_Questionnaire.xlsx<br/>Review_Summary.md<br/>Needs_Review.csv"]
    end

    subgraph UI["Streamlit control plane in app.py"]
        U1["Workspace controls<br/>Load Demo Workspace<br/>Rebuild Index<br/>Reset Demo"]
        U2["Run + export controls<br/>Run Copilot<br/>Publish Export Packet"]
        U3["Session-state orchestration<br/>progress, question inspector,<br/>review queue, action feedback"]
    end

    subgraph Pipeline["Core RAG and export pipeline in rag.py"]
        P1["load_runtime_questionnaire()<br/>read workbook rows into RuntimeQuestionnaire"]
        P2["build_curated_evidence_chunks()<br/>normalize and chunk bundled evidence"]
        P3["ensure_curated_evidence_index()<br/>create / reuse / rebuild local index<br/>with integrity checks"]
        P4["retrieve evidence per question<br/>top-K chunks from Chroma"]
        P5["structured answer generation<br/>OpenAI model call with JSON schema"]
        P6["payload validation + citation resolution<br/>confidence scoring + review status"]
        P7["publish_export_packet()<br/>write workbook, summary, and CSV"]
    end

    subgraph Services["Libraries and external dependencies"]
        L1["Streamlit UI runtime"]
        L2["OpenPyXL workbook I/O"]
        L3["ChromaDB persistent vector store"]
        L4["OpenAI API<br/>embeddings + answer generation"]
    end

    subgraph Verification["Automated verification"]
        T1["tests/unit/*<br/>app.py, rag.py, generate_demo_data.py contracts"]
        T2["tests/e2e/run_deterministic_demo.py<br/>golden-path demo workflow"]
        T3["tests/e2e/run_failure_paths.py<br/>index and workspace failure scenarios"]
        T4["tests/e2e/run_blocked_recovery_paths_test.py<br/>blocked-state and recovery guidance"]
    end

    SQ --> GDD
    SE --> GDD

    GDD --> DQ
    GDD --> DE
    GDD --> DM
    GDD -. reset / rebuild .-> DC
    GDD -. clear old packets .-> DO

    U1 --> GDD
    U2 --> P1
    U2 --> P3
    U2 --> P7
    U3 --> U2

    DQ --> P1
    DE --> P2
    DM --> P3

    P2 --> P3
    P3 <--> DC
    P1 --> P4
    P3 --> P4
    P4 --> P5
    P5 --> P6
    P6 --> U3
    P6 --> DO
    P6 --> P7
    P7 --> DO

    P3 --> L3
    P3 --> L4
    P5 --> L4
    P7 --> L2
    L1 --> U1
    L1 --> U2
    L1 --> U3

    T1 --> GDD
    T1 --> P6
    T1 --> U3
    T2 --> U2
    T2 --> P7
    T3 --> GDD
    T3 --> P3
    T4 --> U1
    T4 --> U3
```

### How to read the diagram
- `generate_demo_data.py` is the workspace bootstrapper. It copies the curated assets from `seed_data/` into `data/`, rebuilds the workspace manifest, and can clear cached Chroma or prior output artifacts.
- `app.py` is the UI orchestrator only. It owns Streamlit session state, buttons, progress, and operator guidance, then delegates the real pipeline work to `generate_demo_data.py` and `rag.py`.
- `rag.py` owns the core system behavior: questionnaire loading, evidence chunking, local index lifecycle, retrieval, structured answer generation, validation, confidence scoring, and export publishing.
- `data/chroma/` is a persistent local cache. The app can reuse it when the workspace hash and chunk inventory still match, or rebuild it when integrity checks or workspace changes require that.
- `data/outputs/` is the reviewer handoff area. The final export packet contains the answered workbook, the markdown review summary, and the CSV queue of questions that still need manual review.
- The verification layer exercises the same architecture from multiple angles: unit tests lock the contracts, while deterministic end-to-end scripts cover the golden path, failure paths, and blocked-state recovery behavior.

## Setup
Install the repo dependencies and set the OpenAI key used by the live-provider path:

```bash
pip install -r requirements.txt
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env`, or export it in your shell before running the app.

## Run
Prepare the runtime workspace from the bundled seed assets:

```bash
python generate_demo_data.py
```

Launch the Streamlit entrypoint from the repo root:

```bash
streamlit run app.py
```

## Outputs
The review packet is written to `data/outputs/`:
- `Answered_Questionnaire.xlsx`
- `Review_Summary.md`
- `Needs_Review.csv`

## Verification
Quick confidence check:

```bash
python -m unittest discover -s tests/unit -p '*_test.py' -v
```

Shared full local validation contract for the remaining automation beads:

```bash
python -m unittest discover -s tests/unit -p '*_test.py' -v
python -m unittest tests.unit.app_test -v
python tests/e2e/run_deterministic_demo.py --log-dir data/outputs/verification/e2e --verbose
python tests/e2e/run_failure_paths.py --log-dir data/outputs/verification/e2e --verbose
python tests/e2e/run_blocked_recovery_paths_test.py --log-dir data/outputs/verification/e2e --verbose
```

Use `br-closeout-audit --issue <issue-id>` before closing high-risk beads and again after verification-heavy test or logging changes.
