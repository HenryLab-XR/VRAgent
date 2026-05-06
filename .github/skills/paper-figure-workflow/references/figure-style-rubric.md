# Figure Style Rubric

Use this rubric to keep the figure set consistent with strong software engineering and AI conference papers.

## Visual Goal

- Make figures look exact, restrained, and auditable.
- Optimize for comprehension of a claim, not visual novelty.
- The result should feel closer to an ICSE, FSE, ASE, ISSTA, or AI-for-SE best-paper figure than to a slide deck graphic.

## Core Constraints

- Prefer vector output.
- Design for IEEE one-column or two-column placement.
- Assume the figure may be printed in grayscale.
- Keep text legible after reduction.
- Use whitespace to separate concepts instead of heavy ornamentation.

## Typography

- Match the paper's existing TeX typography as closely as possible.
- Use concise labels, usually noun phrases or short verb phrases.
- Avoid paragraph text inside nodes.
- Prefer direct annotation over oversized legends.

## Stroke And Spacing

- Keep line widths in a narrow, consistent range.
- Use slightly heavier strokes only for the primary path or the main technique.
- Align boxes and nodes to an implicit grid.
- Keep padding consistent across figures in the same paper.

## Color Use

- Use a small semantic palette.
- Reserve saturated accents for key distinctions such as success versus failure, online versus offline, or baseline versus full method.
- Ensure that fills remain distinguishable without color by combining hue, brightness, dash style, or structure.

## Preferred Visual Grammar

- Forward pipeline: solid arrows.
- Feedback, memory, or optional flows: dashed arrows.
- Conditions, warnings, or blocked states: contrasting callout style.
- Major subsystems: light-tint panels or grouped regions.
- Measurements or outputs: chips, labels, or narrow summary boxes.

## TikZ-Specific Guidance

- Prefer reusable styles over ad hoc per-node formatting.
- Rounded corners are acceptable when subtle.
- Avoid cartoon bubbles, shadow effects, or oversized icons.
- Keep node widths deliberate so the figure reads as a system diagram, not a loose sketch.

## Chart Guidance

- No 3D bars, no perspective axes, and no chartjunk.
- Axes, units, and legends must be explicit.
- For small comparisons, annotate values directly when that improves readability.
- Use dashed or dotted line styles to help grayscale readers.
- If results are illustrative, make that status explicit in the caption or surrounding text.

## Screenshot Guidance

- Use screenshots only when evidence is inherently visual.
- Crop tightly to the relevant interaction region.
- Add only a small number of callouts.
- Do not downscale screenshots until they become unreadable.

## Good Figure Families For Method Papers

- motivating failure or scenario figure
- system overview
- component contract or data bus
- runtime execution loop
- memory, state, or graph structure
- evaluation comparison figure

## Anti-Patterns

- generic AI aesthetics
- glossy gradients
- stock icons that do not encode meaning
- eight unrelated colors in one figure
- vague labels such as "Module A" or "Step 1" with no semantics
- decorative 3D boxes
- fabricated numbers or made-up benchmark outcomes

## Acceptance Check

Before finalizing a figure, verify all of the following:

- the figure supports a concrete paper claim
- the caption can be defended from code, docs, or measured data
- the figure is readable at its target column width
- the figure remains understandable in grayscale
- the figure matches the visual language of the rest of the paper