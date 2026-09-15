# Approach Summary — The Golden Target

> **Required submission artifact.** Answer the seven questions below.
> **Hard limit: ≤ 1,500 words total** (a ceiling, not a target — concise is good).
> Fill this in **after** the tool is built and run. Everything below is a template; replace
> the *(write here)* placeholders and delete these instruction blocks before submitting.
>
> Tip: keep it evidence-led — reference what you actually checked and what the authority
> (UniProt / EBI Proteins API) returned, not what you assumed.

---

## 1. Audit strategy — what did you check for every row, and how did you decide that list was complete?
*(write here)*

<!-- Prompts to consider (delete before submitting):
- Which checks ran on every row (identifier validity, organism, symbol currency, duplicates…)?
- How did you know the checklist covered every defect class the data could contain?
- How did you separate per-row checks from cross-source / cross-record checks? -->

## 2. Identity validation — what fields did you rely on, and where did you cross-check?
*(write here)*

<!-- Prompts:
- Primary join key (UniProt accession) vs. secondary keys (gene symbol, organism)?
- What did you resolve against the authority, and which returned fields settled identity? -->

## 3. Decision rules — what made something a defect rather than legitimately messy?
*(write here)*

<!-- Prompts:
- Your explicit rule for defect vs. harmless variance (e.g. `Homo sapiens` vs `H. sapiens`).
- Rule separating a WRONG mapping from a STALE-BUT-VALID label from a DUPLICATE identity.
- How severity/classification were assigned. -->

## 4. One thing you investigated and chose NOT to flag — and why.
*(write here)*

<!-- Prompts:
- A concrete case you resolved as harmless, with the evidence that made you confident.
- (The `pmid` collisions and species-string formatting are obvious candidates.) -->

## 5. How did you validate your tool before running it on the exam?
*(write here)*

<!-- Prompts:
- Test fixtures / known-answer cases (see tests/). Remember the graded set is HIDDEN. -->

## 6. How did you work with Claude — what did you delegate, and what did you verify yourself?
*(write here)*

<!-- Prompts:
- Be specific and honest; the chat export must corroborate this. What you checked by hand. -->

## 7. What would you harden before running this in production?
*(write here)*

<!-- Prompts:
- Rate limits / retries / caching for the authority; schema drift; monitoring; re-verification. -->

---

*Word count: ___ / 1,500*
