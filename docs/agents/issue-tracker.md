# Issue tracker: Local Markdown by Default

Issues and PRDs for this repo live as markdown files in `.scratch/` by default.

Use GitHub Issues for `lumina-layer-studio/Lumina-studio` only when the user explicitly says the work is for collaboration development.

## Conventions

- One feature per directory: `.scratch/<feature-slug>/`
- The PRD is `.scratch/<feature-slug>/PRD.md`
- Implementation issues are `.scratch/<feature-slug>/issues/<NN>-<slug>.md`, numbered from `01`
- Triage state is recorded as a `Status:` line near the top of each issue file
- Comments and conversation history append to the bottom of the file under a `## Comments` heading

## When a skill says "publish to the issue tracker"

By default, create a new file under `.scratch/<feature-slug>/`.

If the user explicitly requests collaboration development, use GitHub Issues instead.

## When a skill says "fetch the relevant ticket"

For local work, read the file at the referenced `.scratch/` path. The user will normally pass the path or issue number directly.
