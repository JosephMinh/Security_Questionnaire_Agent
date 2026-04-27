# AI Security Questionnaire Copilot — Implementation-Ready Demo Build Spec

## 1. Purpose
Build a **local Streamlit MVP** for a YouTube demo that answers a **single curated security questionnaire** from a **single bundled evidence pack**, shows exact supporting snippets, flags uncertain answers conservatively, and exports a polished review packet.

This is **not** a general-purpose product. It only needs to work for **one known demo use-case** and it needs to **look good on camera**.

---

## 2. Build goal
The app is successful if a viewer can watch this sequence and immediately understand the value:

1. Click **Load Demo Workspace**.
2. See that the curated questionnaire and evidence pack are ready.
3. Click **Run Copilot**.
4. Watch answers fill in row by row.
5. Open one supported answer and see exact source snippets.
6. Open one unsupported answer and see that it was routed to review instead of guessed.
7. Export a clean workbook and review files.

That is the entire goal.

---

## 3. Hard constraints
These constraints are mandatory. Do not expand scope beyond them.

### In scope
- Streamlit UI
- Python app
- OpenAI for embeddings and answer generation
- Chroma persistent local vector store
- One known questionnaire template
- One bundled evidence pack
- Exact snippet citations via `chunk_id`
- Deterministic confidence and status computed in code
- Styled Excel export
- Review summary files

### Out of scope
Do **not** build any of the following in this 10-hour version:
- support for arbitrary customer workbook layouts
- generic document ingestion from many file types
- OCR or scanned PDF support
- row-click table interactions
- preserving original workbook formatting
- Slack integration
- prior answers `.xlsx` ingestion
- multi-tenant behavior
- authentication
- background jobs
- human editing workflows inside the app
- polished support for custom uploads

If there is spare time, spend it on polish and reliability, not on new features.

---

## 4. Golden path to optimize
The app must have **one primary path** and that path must feel smooth.

### Required primary actions
1. **Load Demo Workspace**
2. **Run Copilot**
3. **Inspect Answers**
4. **Export Packet**

### Advanced controls
Put non-primary controls inside an **Advanced** expander:
- Rebuild Index
- Reset Demo

Do **not** make uploads a first-class path in this build.

---

## 5. Demo content contract
The demo data must be **hand-authored and checked into the repo**. Do not generate the content dynamically at runtime except for copying/resetting files.

### 5.1 Questionnaire size
Use **exactly 22 questions**.

Target mix:
- **15 supported**
- **3 partial**
- **4 unsupported**

Do not exceed 24 questions.

### 5.2 Evidence pack size
Use **exactly 5 evidence files**:
- `AcmeCloud_SOC2_Summary.pdf`
- `Encryption_Policy.md`
- `Access_Control_Policy.md`
- `Incident_Response_Policy.md`
- `Backup_and_Recovery_Policy.md`

Use **one text-based PDF** and **four markdown files**.

### 5.3 Critical content design rule
Design the evidence pack **backwards from the questionnaire**.

For each supported question:
- there must be **one obvious primary chunk** that answers it
- optionally one corroborating chunk may also support it

For each partial question:
- the evidence must answer **most** of the question but clearly miss one important detail

For each unsupported question:
- the answer must be **genuinely absent** from the evidence pack
- avoid near-match language that could confuse retrieval

### 5.4 Questionnaire schema
The runtime questionnaire workbook must contain a single sheet named `Questions` with these required columns:
- `Question ID`
- `Category`
- `Question`

The app must create these output columns in memory if they are not already present:
- `Answer`
- `Evidence`
- `Confidence`
- `Status`
- `Reviewer Notes`

### 5.5 Question matrix
Create the demo questionnaire with exactly these rows.

| Question ID | Category | Question | Intended Outcome | Primary Evidence |
|---|---|---|---|---|
| Q01 | Encryption | Is customer data encrypted at rest in production systems? | supported | Encryption_Policy.md |
| Q02 | Encryption | Is customer data encrypted in transit over public networks? | supported | Encryption_Policy.md |
| Q03 | Encryption | Are encryption keys managed centrally using a KMS? | supported | Encryption_Policy.md |
| Q04 | Access Control | Is MFA required for administrative access? | supported | Access_Control_Policy.md |
| Q05 | Access Control | Is role-based access control used for internal systems? | supported | Access_Control_Policy.md |
| Q06 | Access Control | Are user access reviews performed at least quarterly? | supported | Access_Control_Policy.md |
| Q07 | Access Control | Is production access restricted to authorized personnel only? | supported | Access_Control_Policy.md |
| Q08 | Incident Response | Do you maintain a documented incident response plan? | supported | Incident_Response_Policy.md |
| Q09 | Incident Response | Are security incidents triaged internally within 24 hours? | supported | Incident_Response_Policy.md |
| Q10 | Incident Response | Are incident response tabletop exercises performed at least annually? | supported | Incident_Response_Policy.md |
| Q11 | Backup & Recovery | Are production backups performed daily? | supported | Backup_and_Recovery_Policy.md |
| Q12 | Backup & Recovery | Are restore tests performed at least quarterly? | supported | Backup_and_Recovery_Policy.md |
| Q13 | Backup & Recovery | Are target RTO and RPO values defined? | supported | Backup_and_Recovery_Policy.md |
| Q14 | Compliance | Has the company completed a SOC 2 Type II audit? | supported | AcmeCloud_SOC2_Summary.pdf |
| Q15 | Compliance | Was the SOC 2 audit performed by an independent third party? | supported | AcmeCloud_SOC2_Summary.pdf |
| Q16 | Access Control | Is SSO enforced for all workforce applications? | partial | Access_Control_Policy.md |
| Q17 | Incident Response | Are customers notified of confirmed breaches within 72 hours? | partial | Incident_Response_Policy.md |
| Q18 | Backup & Recovery | Are backups immutable for all production systems? | partial | Backup_and_Recovery_Policy.md |
| Q19 | Encryption | Do you support customer-managed encryption keys (BYOK)? | unsupported | none |
| Q20 | Data Residency | Can customers choose the region where data is stored? | unsupported | none |
| Q21 | Monitoring | Is there a 24/7 managed security operations center monitoring alerts? | unsupported | none |
| Q22 | Security Testing | Do you perform annual external penetration testing? | unsupported | none |

### 5.6 Required evidence file contents
Write the evidence files so the language matches the questionnaire language closely.

#### `Encryption_Policy.md`
Must contain sections that explicitly state:
- data at rest is encrypted with AES-256
- data in transit is protected with TLS 1.2+
- encryption keys are managed in a cloud KMS
- key access is restricted to authorized security or platform administrators

#### `Access_Control_Policy.md`
Must contain sections that explicitly state:
- MFA is required for administrative access
- RBAC is used for internal systems
- access reviews occur quarterly
- production access is limited to authorized personnel
- SSO is used for core workforce systems, but do **not** claim it covers **all** workforce applications

#### `Incident_Response_Policy.md`
Must contain sections that explicitly state:
- there is a documented incident response plan
- incidents are triaged internally within 24 hours
- tabletop exercises occur annually
- customer notifications happen without undue delay and according to legal or contractual obligations, but do **not** promise a universal 72-hour commitment

#### `Backup_and_Recovery_Policy.md`
Must contain sections that explicitly state:
- production backups run daily
- restore tests are performed quarterly
- RPO is 24 hours and RTO is 8 hours
- immutable backups are used for critical systems, but do **not** claim immutability for **all** production systems

#### `AcmeCloud_SOC2_Summary.pdf`
Must be a simple text-based PDF that explicitly states:
- AcmeCloud completed a SOC 2 Type II examination
- the examination was conducted by an independent audit firm
- the audit period dates
- the report covers relevant security controls

Do **not** make the PDF scanned or image-based.

---

## 6. Repo and file layout
Use this repo structure.

```text
app.py
rag.py
generate_demo_data.py
requirements.txt
.env.example
README.md
seed_data/
  questionnaire/
    Demo_Security_Questionnaire.xlsx
  evidence/
    AcmeCloud_SOC2_Summary.pdf
    Encryption_Policy.md
    Access_Control_Policy.md
    Incident_Response_Policy.md
    Backup_and_Recovery_Policy.md
data/
  questionnaires/
  evidence/
  outputs/
  chroma/
```

### File responsibilities
- `app.py`: Streamlit UI and orchestration
- `rag.py`: loading, chunking, indexing, retrieval, model call, post-processing, scoring
- `generate_demo_data.py`: copy curated seed files into runtime folders, clear outputs, optionally clear index

Do not introduce a large framework. Keep the code direct.

---

## 7. Setup script behavior
`generate_demo_data.py` is a **reset/setup script**, not a content generator.

### Required behavior
When run, it must:
1. create `data/questionnaires/`, `data/evidence/`, `data/outputs/`, and `data/chroma/` if missing
2. copy the seed questionnaire into `data/questionnaires/`
3. copy the 5 seed evidence files into `data/evidence/`
4. clear prior files from `data/outputs/`
5. optionally clear `data/chroma/` when a reset flag is provided
6. write a simple manifest file with file hashes for the current runtime workspace

### CLI behavior
Support these commands:
- `python generate_demo_data.py` → copy seed files and clear outputs only
- `python generate_demo_data.py --reset-index` → also clear `data/chroma/`

---

## 8. Runtime data contracts
Use the following in-memory structures.

### 8.1 Chunk metadata
Every chunk stored in Chroma must include metadata shaped like this:

```json
{
  "chunk_id": "enc_003",
  "source": "Encryption_Policy.md",
  "doc_type": "policy",
  "section": "Data at Rest",
  "page": null
}
```

For PDF chunks, `page` should be the page number and `section` can be `null`.

### 8.2 Result row schema
Each processed question row must produce at least these internal fields:

```json
{
  "question_id": "Q01",
  "category": "Encryption",
  "question": "Is customer data encrypted at rest in production systems?",
  "answer": "Yes. Customer data at rest is encrypted using AES-256 in production systems.",
  "answer_type": "supported",
  "citation_ids": ["enc_001"],
  "citations": [
    {
      "chunk_id": "enc_001",
      "source": "Encryption_Policy.md",
      "section": "Data at Rest",
      "snippet": "...",
      "display_label": "Encryption Policy — Data at Rest"
    }
  ],
  "confidence_score": 0.9,
  "confidence_band": "High",
  "status": "Ready for Review",
  "reviewer_note": "Supported by the encryption policy."
}
```

### 8.3 Exported columns
The final workbook must contain these visible columns in this order:
- `Question ID`
- `Category`
- `Question`
- `Answer`
- `Evidence`
- `Confidence`
- `Status`
- `Reviewer Notes`

Use the `Evidence` column for friendly labels joined with `; `.

---

## 9. Indexing and caching rules
### 9.1 Required behavior
- Use a persistent local Chroma collection.
- Reuse the existing index if the runtime workspace file hashes have not changed.
- Skip re-indexing on repeated demo runs when the manifest matches.

### 9.2 Collection name
Use a single collection name such as `security_questionnaire_demo`.

### 9.3 Hashing
Hash the contents of all files in:
- `data/questionnaires/`
- `data/evidence/`

Save the combined hash to the manifest file.

### 9.4 Rebuild behavior
If the user clicks **Rebuild Index** or the hash changes:
- delete and recreate the collection
- rebuild embeddings from the current runtime files

---

## 10. Loader and chunking rules
Implement only the loaders needed for the curated demo.

### 10.1 Allowed loaders
- markdown loader
- text loader
- simple PDF text loader using `pypdf`

Do **not** implement spreadsheet evidence loading.

### 10.2 Text normalization
Before chunking:
- normalize line endings
- collapse repeated blank lines
- strip trailing spaces
- preserve headings if present

### 10.3 Chunking
Use fixed chunking with these settings:
- chunk size: **700 characters**
- overlap: **100 characters**

### 10.4 Chunk IDs
Use stable chunk IDs based on file stem and order.
Examples:
- `enc_001`
- `enc_002`
- `acc_001`
- `ir_001`
- `bkp_001`
- `soc2_001`

### 10.5 Section labels
For markdown files, capture the nearest markdown heading when possible and save it as `section` metadata.
If heading extraction is not easy, use the file stem as the fallback display label.

---

## 11. Retrieval and answer pipeline
For each question, the code must run this exact sequence.

### Step 1: retrieve
Query Chroma for the top **5** chunks.

### Step 2: build model input
Pass the model:
- the question text
- the list of retrieved chunks
- each chunk’s `chunk_id`
- each chunk’s source filename
- each chunk’s chunk text

### Step 3: model response
The model must return structured JSON with:
- `answer`
- `answer_type`
- `citation_ids`
- `reviewer_note`

### Step 4: validate response
Validate all returned `citation_ids`.
Drop any citation IDs that were not present in the retrieved chunk list.

### Step 5: resolve citations
Map valid citation IDs back to exact snippets and friendly display labels.
Use at most the first **2 valid citations** for the UI and exports.

### Step 6: score in code
Compute confidence and status in code using the deterministic rules below.

### Step 7: store result row
Append the result to the in-memory dataframe and refresh the UI.

---

## 12. Model output contract
Use structured outputs with this schema.

```json
{
  "answer": "string",
  "answer_type": "supported | partial | unsupported",
  "citation_ids": ["string"],
  "reviewer_note": "string"
}
```

### Answer formatting rules
The model must obey all of these:
- answer must be **1 to 3 sentences**
- answer must begin with exactly one of: `Yes.`, `No.`, `Partially.`, `Not stated.`
- answer must use only the supplied evidence
- answer must not claim certainty beyond the evidence
- answer must not invent citations
- answer must not include raw filenames inside the prose unless necessary

### Allowed answer type meanings
- `supported`: the evidence clearly supports the answer
- `partial`: the evidence supports only part of the answer or leaves a key detail unspecified
- `unsupported`: the evidence does not support the answer

---

## 13. Prompt contract
Use a prompt that enforces conservative behavior.

### Required system instructions
The system prompt should communicate all of the following:
- answer only from the provided evidence chunks
- do not use outside knowledge
- do not invent policies, timelines, or capabilities
- cite only `chunk_id` values from the provided list
- if evidence is incomplete, use `partial`
- if evidence is missing, use `unsupported`
- keep answers short and readable
- start the answer with `Yes.`, `No.`, `Partially.`, or `Not stated.`

### Required user input shape
Pass evidence chunks in a readable format like:

```text
Question:
Is customer data encrypted at rest in production systems?

Evidence chunks:
[enc_001] source=Encryption_Policy.md
<Data chunk text>

[enc_002] source=Encryption_Policy.md
<Data chunk text>
```

---

## 14. Confidence and status rules
Compute these values in code. Do not ask the model to compute them.

### 14.1 Confidence score rules
Use this exact logic:
- if `answer_type == unsupported` → `confidence_score = 0.30`
- else if `answer_type == partial` → `confidence_score = 0.55`
- else if `answer_type == supported` and valid citation count is `1` → `confidence_score = 0.78`
- else if `answer_type == supported` and valid citation count is `2 or more` → `confidence_score = 0.90`
- if valid citation count is `0`, override to `confidence_score = 0.25`

### 14.2 Confidence band rules
Map score to band like this:
- `>= 0.85` → `High`
- `>= 0.60 and < 0.85` → `Medium`
- `< 0.60` → `Low`

### 14.3 Status rules
Use this exact logic:
- if `answer_type == supported` and valid citation count is at least `1` → `Ready for Review`
- otherwise → `Needs Review`

### 14.4 Display rules
- In the **UI**, show the confidence **band**, not the numeric score.
- In the internal dataframe, keep the numeric score for sorting.

---

## 15. Failure handling rules
The app must fail safely and continue row-by-row.

### Required fail-closed behavior
If any of the following happens:
- retrieval returns no chunks
- model output is malformed
- schema validation fails
- all cited `chunk_id` values are invalid after validation

Then do this for that row:
- set `answer` to `Not stated. The available evidence does not support a reliable answer.`
- set `answer_type` to `unsupported`
- set `confidence_score` to `0.25`
- set `confidence_band` to `Low`
- set `status` to `Needs Review`
- set `reviewer_note` to a short reason such as `Model output invalid; routed to review.` or `No reliable evidence retrieved.`
- continue processing the remaining rows

### Retry rule
Allow **one retry** for a model call only if parsing or schema validation fails.
Do not retry more than once.

---

## 16. UI specification
The app must look deliberate and simple.

### 16.1 Header area
Show:
- app title
- short subtitle
- a small label such as `Demo Mode: curated questionnaire + bundled evidence pack`

### 16.2 Section 1: Workspace
Show:
- primary button: **Load Demo Workspace**
- status text indicating whether workspace files are present
- status text indicating whether the index is ready or reused

Inside an **Advanced** expander, show:
- **Rebuild Index** button
- **Reset Demo** button

Behavior:
- `Load Demo Workspace` must run the setup logic and ensure the index is available
- if hashes match and the index exists, reuse it instead of rebuilding

### 16.3 Section 2: Run Copilot
Show:
- total question count
- **Run Copilot** button
- progress bar
- status text showing current question ID during processing

Behavior:
- process one row at a time
- update the results table live as rows complete

### 16.4 Summary cards
After at least one row is processed, show these cards:
- `Questions`
- `Ready for Review`
- `Needs Review`
- `Sources Indexed`

### 16.5 Results table
Show a simple dataframe or table with these columns:
- `Question ID`
- `Category`
- `Answer`
- `Confidence`
- `Status`

Do not require row-click interactions.

### 16.6 Inspector
Use a `selectbox` keyed by `Question ID`.
When a row is selected, show:
- full question text
- drafted answer
- confidence band
- status badge
- reviewer note
- exact evidence snippets

For each citation, show:
- friendly label such as `Encryption Policy — Data at Rest`
- source filename in small text if useful
- snippet text in a readable container

### 16.7 Default selected question
After the run finishes:
- if there are any `Needs Review` items, auto-select the first one with the lowest confidence score
- otherwise auto-select the first question

### 16.8 Review queue
Show a second filtered table containing rows where:
- `Status == Needs Review`
  or
- `confidence_score < 0.75`

Sort this table by:
1. ascending `confidence_score`
2. ascending `Question ID`

---

## 17. Export specification
Exports are mandatory and must look good.

### 17.1 Required files
Write these files to `data/outputs/`:
- `Answered_Questionnaire.xlsx`
- `Review_Summary.md`
- `Needs_Review.csv`

### 17.2 Workbook rules
Create a **new workbook**. Do not mutate the seed questionnaire file in place.

### 17.3 Workbook styling requirements
The workbook must include:
- bold header row
- frozen top row
- autofilter enabled
- wrapped text for long cells
- reasonable column widths
- status cell fill colors

Recommended status colors:
- `Ready for Review` → light green
- `Needs Review` → light amber

### 17.4 Workbook content rules
The `Evidence` column must contain friendly labels joined by `; `.
Example:
- `Encryption Policy — Data at Rest; SOC 2 Summary — Page 1`

### 17.5 Review summary markdown
`Review_Summary.md` must contain:
- total question count
- ready-for-review count
- needs-review count
- list of question IDs requiring review with short notes

### 17.6 Needs review CSV
`Needs_Review.csv` must contain only rows that require review.
Include these columns:
- `Question ID`
- `Category`
- `Question`
- `Answer`
- `Confidence`
- `Status`
- `Reviewer Notes`

---

## 18. Implementation order
Build in this order and do not jump ahead.

### Hour 1 — scaffold and seed assets
- create repo structure
- add runtime folders
- add `.env.example`
- create the 22-question workbook in `seed_data/questionnaire/`
- write the four markdown evidence files
- add the text-based SOC 2 PDF

### Hour 2 — setup/reset flow
- implement `generate_demo_data.py`
- copy seed files into runtime folders
- clear outputs
- add manifest hashing
- support `--reset-index`

### Hours 3–4 — loaders, chunking, indexing
- implement markdown/text loader
- implement text-based PDF loader with `pypdf`
- normalize text
- chunk documents
- assign stable `chunk_id` values
- persist chunks to Chroma
- implement index reuse based on manifest hash

### Hours 5–6 — question answering pipeline
- retrieve top 5 chunks per question
- build the structured model call
- validate returned `citation_ids`
- resolve citations back to exact snippets
- compute confidence and status in code
- implement fail-closed behavior and one retry
- return structured row results

### Hour 7 — UI
- build header and demo mode label
- implement `Load Demo Workspace`
- implement `Run Copilot`
- show progress bar and status text
- show summary cards
- show results table
- show selectbox inspector
- show review queue

### Hour 8 — export
- create styled Excel workbook
- write markdown summary
- write needs-review CSV
- add export buttons or download actions in Streamlit

### Hour 9 — tuning and stabilization
- run 3 smoke tests: one supported, one partial, one unsupported
- fix prompt wording until the three cases behave correctly
- tune evidence wording if retrieval is weak
- verify that one bad row never breaks the run
- verify that the index reuse path works

### Hour 10 — polish for recording
- improve labels and spacing
- confirm the default selected question behavior
- confirm review queue sorting
- verify export styling
- rehearse the full on-camera flow

---

## 19. Smoke tests
These are required.

### Supported case
Question: `Q01`
Expected:
- answer begins with `Yes.`
- status is `Ready for Review`
- confidence band is `Medium` or `High`
- citation comes from `Encryption_Policy.md`

### Partial case
Question: `Q17`
Expected:
- answer begins with `Partially.`
- status is `Needs Review`
- confidence band is `Low` or `Medium`
- citation comes from `Incident_Response_Policy.md`

### Unsupported case
Question: `Q21`
Expected:
- answer begins with `Not stated.`
- status is `Needs Review`
- confidence band is `Low`
- no confident capability claim is made

---

## 20. Required dependencies
Keep dependencies minimal.

Required:
- `streamlit`
- `openai`
- `chromadb`
- `pandas`
- `openpyxl`
- `pypdf`
- `python-dotenv`

Do not add heavyweight orchestration libraries unless truly necessary.

---

## 21. README requirements
The README only needs to explain:
- what the demo does
- how to set `OPENAI_API_KEY`
- how to run `generate_demo_data.py`
- how to launch Streamlit
- what files will be written to `data/outputs/`

Keep the README short.

---

## 22. Acceptance criteria
The build is done when all of the following are true:
- the app runs locally from Streamlit without manual file editing
- `Load Demo Workspace` prepares the runtime files successfully
- the index is reused on repeated runs when the workspace is unchanged
- the app answers all 22 questions without crashing
- supported answers show exact source-backed snippets
- unsupported answers are conservative and routed to review
- the review queue is believable and sorted correctly
- the exported workbook is styled and readable
- the exported markdown and CSV are present and correct
- the UI feels clean enough to record for a demo video

---

## 23. Explicit build decisions
These decisions are intentional. Do not “improve” them during the 10-hour build.

- one bundled demo workspace only
- one known questionnaire format only
- one PDF plus four markdown evidence files only
- no Slack
- no prior answers spreadsheet
- no custom upload path as a required feature
- no agent framework
- no fancy front-end interactions
- no attempt to generalize beyond the demo

The right tradeoff is **less scope, more polish**.
