---
name: paper-figure-workflow
description: "Generate publication-ready paper figures from current TeX or LaTeX, code, planning docs, architecture notes, experiment scripts, and accessible workspace chat history. Use for missing figures, weak diagrams, figure placeholders, TikZ redraws, IEEE/ICSE/FSE/ASE/ISSTA/AI4SE papers, and full-paper refresh passes that create or regenerate the whole figure set in best-paper style."
argument-hint: "TeX path plus scope, for example: _doc/ICSE27_VRAgent2.0_PVEO/icse27_vragent2_main.tex ; refresh all figures in best-paper style"
user-invocable: true
---

# Paper Figure Workflow

Use this skill when the task is to turn a paper repository into a coherent figure set instead of drawing isolated diagrams one by one.

## Required Outcomes

- Build a figure inventory for the target paper: existing, missing, weak, placeholder, or stale figures.
- Tie every figure to a paper claim, section, or evaluation need.
- Generate or refresh publication-ready figure source files in the paper figures directory.
- Update TeX when a figure is newly added, renamed, or currently missing from the paper.
- Return a short report that separates evidence-backed figures from illustrative placeholders.

## Inputs To Use

1. The current editor `.tex` file if it is the paper entry point.
2. An explicit TeX path from the user, if provided.
3. The paper root, figures directory, and nearby planning docs.
4. Repository code, scripts, experiment outputs, and architecture notes.
5. Accessible repository memory and accessible workspace chat history, if available.

## Start From The Closest Anchor

1. If the user gave a TeX path, start there.
2. Else if the active editor is a paper TeX file, use it.
3. Else search the repo for the main paper `.tex` file and pick the most likely entry point.
4. If multiple candidates remain ambiguous, ask one narrow question before editing anything.

## Mine Prior Decisions Before Drawing

1. Read the target TeX file around:
   - title, abstract, contributions
   - section headings
   - figure environments
   - captions, labels, TODOs, and planned result tables
2. Read repository memory if present.
3. If workspace chat session JSONL files are accessible, mine only sessions relevant to this repo or paper:
   - architecture decisions
   - renamed modules
   - evaluation metrics
   - known figure ideas, accepted layouts, or rejected layouts
4. Read the smallest set of planning docs needed to recover:
   - the system story
   - the evaluation story
   - terminology that must stay consistent with the paper and code
5. Read the owning code modules for the claims each figure is meant to support.

## Build A Figure Inventory First

Create an internal table for every figure candidate with this structure:

- figure id
- output file
- paper section and claim
- status: keep / refine / regenerate / create
- evidence sources
- figure type
- placeholder allowed: yes / no
- TeX edit needed: yes / no

Use the template in [figure-brief-template](./assets/figure-brief-template.md).

## Choose Figure Types Deliberately

Use the heuristics in [figure-selection-heuristics](./references/figure-selection-heuristics.md).

Default choices:

- Prefer TikZ for architecture, pipelines, agent contracts, state machines, taxonomies, feedback loops, ablation schematics, bar charts, line charts, and protocol flows.
- Prefer SVG or PDF only when the figure is too complex for maintainable TikZ.
- Use PNG only for screenshots, scene snapshots, or evidence that is inherently raster.

## Style Rules

Follow [figure-style-rubric](./references/figure-style-rubric.md).

Non-negotiable style goals:

- Vector-first.
- IEEE two-column safe.
- Readable after reduction.
- Minimal palette, grayscale-safe separation, strong stroke contrast.
- Information-dense, not decorative.
- No generic AI art, glossy gradients, stock icons, or fake 3D perspective.
- Labels and captions must reflect repository evidence and paper terminology.

## Placeholder Policy

- Never invent experimental wins, percentages, benchmarks, or claims.
- If the paper clearly marks a result as planned, placeholders may be illustrative only.
- Any illustrative result figure must be obviously non-final in caption text or surrounding paper text.
- Conceptual figures may be fully finalized before experiments if they are evidence-backed by code and design docs.

## Execution Procedure

1. Locate the paper root and the figures directory.
2. Inventory all `\input{figures/...}` and `\includegraphics{figures/...}` references.
3. Compare TeX references with files already present under the figures directory.
4. Scan for missing visual needs implied by the narrative, usually including some subset of:
   - motivation or failure example
   - system overview
   - component or contract bus
   - runtime or execution loop
   - feedback or memory structure
   - evaluation plots or comparison bars
5. For each figure, write a concise brief before drawing.
6. Generate or refresh figure source files with stable semantic names such as `fig_overview.tex`, `fig_runtime_loop.tex`, or `fig_bar_comparison.tex`.
7. Reuse existing paper color and style macros when they already form a coherent family.
8. If the paper lacks shared TikZ styles, add only the minimum consistent style definitions needed.
9. Update TeX only when necessary:
   - new figure environment
   - missing `\input` or `\includegraphics`
   - stale file name
   - caption or label mismatch
10. Validate:
    - every referenced figure file exists
    - no renamed figure leaves broken references
    - captions match the actual figure semantics
    - no fabricated quantitative claims were introduced
11. If a narrow TeX compile is available, run it. Otherwise validate paths and references directly.

## Important Behaviors

- Prefer one coherent paper-wide figure pass over one-off local optimizations.
- Keep figure terminology aligned with code, module names, and planning documents.
- Preserve existing labels where practical to avoid breaking cross-references.
- If an existing figure is already strong and consistent, keep it.
- If several figures are weak in the same way, refactor them into a shared visual language.
- When data is missing, strengthen conceptual figures first and postpone final result plots.

## Expected Final Report

Return:

- which figures were created, refreshed, or kept
- which figures remain illustrative placeholders
- which paper claims still need real experimental data or screenshots
- any TeX labels, captions, or path updates that were made