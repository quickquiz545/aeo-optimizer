# AEO Optimizer

A Python-based URL crawler and AEO readiness auditor for static, machine-liftable HTML. It checks whether a page is structured for AI engines and answer engines to extract direct, trustworthy answers without relying on heavy client-side JavaScript.

## What It Checks

- Static H2/H3 content modules that AI crawlers can lift without executing JavaScript.
- Question-style H2/H3 headings.
- Clear 40-60 word answers immediately after headings.
- Bullet lists, numbered lists, and comparison tables.
- Definition -> Detail -> Example section structure.
- FAQPage, HowTo, Product, Article, and Organization schema.
- Author bylines, expert bios, proprietary data, quotes, visuals, and freshness signals.
- `robots.txt` and `llms.txt` readiness for GPTBot and CCBot.
- Long paragraphs and marketing fluff that reduce factual extractability.

## Vercel Deployment

The project includes:

- `index.html`: the public web interface served at `/`.
- `api/audit.py`: a Vercel Python Function served at `/api/audit`.
- `vercel.json`: function bundle configuration.

After Vercel redeploys the latest `main` branch, open the project URL and run an audit from the form.

## CLI Run

```powershell
python aeo_audit.py https://example.com/page --format markdown --output aeo-report.md
```

Use JSON output for automation:

```powershell
python aeo_audit.py https://example.com/page --format json --output aeo-report.json
```

If Python is not on PATH in the Codex runtime, use the bundled interpreter:

```powershell
& 'C:\Users\Abhishek.kumar.AGILEVEN\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' aeo_audit.py https://example.com/page --format markdown --output aeo-report.md
```

## Output

The report includes:

- A numeric AEO readiness score.
- A snapshot of headings, answer blocks, schemas, formatting, and technical readiness.
- Prioritized findings with evidence and exact actions.
- A step-by-step AEO Action Plan.
- A list of machine-liftable H2/H3 sections with answer length and formatting signals.
