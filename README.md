# Content Auditor

A local browser-based content auditor built from `Guidelines for Authors.docx`.

This workspace also includes `aeo_audit.py`, a URL-based AEO readiness auditor for static, machine-liftable HTML.

## What it checks

- Banned wording such as `also`, opinion phrases, weak certainty, and back-references.
- Sentences that start with `if` or `because`.
- Long sentences, passive voice, half-sentence list introductions, and possibility modals.
- Central entity coverage across the intro and sections.
- Central search intent coverage in the intro.
- Direct answers under question headings.
- Research, numeric detail, examples, units, percentages, and first-use abbreviations.
- Featured snippet length, image introductions, table comparison language, and anchor placement.

## Run

```powershell
& 'C:\Users\Abhishek.kumar.AGILEVEN\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' app.py 8000
```

Then open `http://127.0.0.1:8000`.

## Run the AEO URL audit

```powershell
& 'C:\Users\Abhishek.kumar.AGILEVEN\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' aeo_audit.py https://example.com/page --format markdown --output aeo-report.md
```

Use `--format json` when you need structured output for another workflow.

The AEO audit checks:

- Static H2/H3 content modules that AI crawlers can lift without client-side JavaScript.
- Question-style headings and 40-60 word direct answers.
- Bullets, numbered lists, comparison tables, and Definition -> Detail -> Example structure.
- FAQPage, HowTo, Product, Article, and Organization schema.
- Author, expert bio, proprietary data, quote, visual, and freshness signals.
- `robots.txt` and `llms.txt` readiness for GPTBot and CCBot.

## Supported input

Paste content directly, or upload `.txt`, `.md`, `.docx`, `.pdf`, `.html`, `.csv`, or `.rtf`.
