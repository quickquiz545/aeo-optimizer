from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


USER_AGENT = "AEOReadinessAuditor/2026 (+https://example.local/aeo-audit)"
QUESTION_STARTERS = {
    "what",
    "why",
    "how",
    "when",
    "where",
    "who",
    "which",
    "can",
    "could",
    "should",
    "do",
    "does",
    "did",
    "is",
    "are",
    "was",
    "were",
    "will",
}
SCHEMA_TYPES = {"FAQPage", "HowTo", "Product", "Article", "Organization"}
SKIP_CONTENT_TAGS = {
    "script",
    "style",
    "template",
    "canvas",
    "svg",
    "iframe",
    "noscript",
    "nav",
    "footer",
    "aside",
    "form",
}
BLOCK_TAGS = {"p", "li", "td", "th", "caption", "blockquote"}
MARKETING_FLUFF = {
    "game-changing",
    "cutting-edge",
    "revolutionary",
    "world-class",
    "best-in-class",
    "seamless",
    "unlock",
    "supercharge",
    "transform your",
    "take your",
    "next level",
    "ultimate",
    "robust",
    "innovative",
}
PROPRIETARY_MARKERS = {
    "case study",
    "original research",
    "proprietary data",
    "survey",
    "benchmark",
    "dataset",
    "chart",
    "figure",
    "graph",
    "experiment",
}


@dataclass
class ContentBlock:
    tag: str
    text: str


@dataclass
class Section:
    level: str
    heading: str
    blocks: list[ContentBlock] = field(default_factory=list)
    has_bullets: bool = False
    has_numbered_list: bool = False
    has_table: bool = False


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    evidence: str
    action: str


@dataclass
class RobotsStatus:
    url: str
    found: bool
    gptbot_blocked: bool = False
    ccbot_blocked: bool = False
    notes: list[str] = field(default_factory=list)


def compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def words(text: str) -> list[str]:
    return re.findall(r"\b[A-Za-z][A-Za-z0-9'-]*\b", text)


def word_count(text: str) -> int:
    return len(words(text))


def excerpt(text: str, limit: int = 220) -> str:
    text = compact(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def fetch_text(url: str, timeout: int = 15) -> tuple[str, str, int | None]:
    request = Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,text/plain,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace"), response.geturl(), response.status
    except HTTPError as exc:
        charset = exc.headers.get_content_charset() if exc.headers else None
        body = exc.read().decode(charset or "utf-8", errors="replace")
        return body, url, exc.code
    except URLError as exc:
        raise RuntimeError(f"Could not fetch {url}: {exc.reason}") from exc


class StaticHTMLExtractor(HTMLParser):
    """Extracts server-rendered, machine-liftable content without executing JavaScript."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[Section] = []
        self.meta: dict[str, str] = {}
        self.links: list[dict[str, str]] = []
        self.visible_text: list[str] = []
        self.skip_stack: list[str] = []
        self.heading_tag: str | None = None
        self.heading_parts: list[str] = []
        self.block_tag: str | None = None
        self.block_parts: list[str] = []
        self.current: Section | None = None
        self.in_body = False
        self.list_stack: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs_dict = {name.lower(): value or "" for name, value in attrs}
        if tag == "body":
            self.in_body = True
        if tag in SKIP_CONTENT_TAGS:
            self.skip_stack.append(tag)
            return
        if self.skip_stack:
            return
        if tag == "meta":
            key = attrs_dict.get("name") or attrs_dict.get("property")
            if key:
                self.meta[key.lower()] = attrs_dict.get("content", "")
        if tag == "link":
            self.links.append(attrs_dict)
        if tag in {"ul", "ol"}:
            self.list_stack.append(tag)
            if self.current and tag == "ul":
                self.current.has_bullets = True
            if self.current and tag == "ol":
                self.current.has_numbered_list = True
        if tag == "table" and self.current:
            self.current.has_table = True
        if tag in {"h2", "h3"}:
            self.heading_tag = tag
            self.heading_parts = []
            return
        if tag in BLOCK_TAGS and self.current:
            self.block_tag = tag
            self.block_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self.skip_stack:
            if tag == self.skip_stack[-1]:
                self.skip_stack.pop()
            return
        if tag == "body":
            self.in_body = False
        if tag in {"ul", "ol"} and self.list_stack:
            self.list_stack.pop()
        if self.heading_tag == tag:
            heading = compact(" ".join(self.heading_parts))
            if heading:
                self.current = Section(level=tag.upper(), heading=heading)
                self.sections.append(self.current)
            self.heading_tag = None
            self.heading_parts = []
        if self.block_tag == tag and self.current:
            text = compact(" ".join(self.block_parts))
            if text:
                self.current.blocks.append(ContentBlock(tag=tag, text=text))
                self.visible_text.append(text)
            self.block_tag = None
            self.block_parts = []

    def handle_data(self, data: str) -> None:
        if self.skip_stack:
            return
        text = compact(data)
        if not text:
            return
        if self.heading_tag:
            self.heading_parts.append(text)
            return
        if self.block_tag:
            self.block_parts.append(text)


def schema_name(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, str):
        names.add(value.rsplit("/", 1)[-1])
    elif isinstance(value, list):
        for item in value:
            names.update(schema_name(item))
    return names


def collect_schema_types(html: str) -> set[str]:
    found: set[str] = set()
    for match in re.finditer(
        r"<script\b[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
        flags=re.I | re.S,
    ):
        raw = re.sub(r"<!--|-->", "", match.group(1)).strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        stack = payload if isinstance(payload, list) else [payload]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                found.update(schema_name(item.get("@type")))
                graph = item.get("@graph")
                if isinstance(graph, list):
                    stack.extend(graph)
                for value in item.values():
                    if isinstance(value, dict):
                        stack.append(value)
                    elif isinstance(value, list):
                        stack.extend(v for v in value if isinstance(v, dict))
    found.update(re.findall(r"schema\.org/([A-Za-z]+)", html, flags=re.I))
    return found


def extract_page(html: str) -> tuple[list[Section], dict[str, str], set[str], str]:
    parser = StaticHTMLExtractor()
    parser.feed(html)
    schemas = collect_schema_types(html)
    visible_text = "\n\n".join(parser.visible_text)
    return parser.sections, parser.meta, schemas, visible_text


def is_question_heading(heading: str) -> bool:
    normalized = compact(heading).lower()
    first = words(normalized)[:1]
    return normalized.endswith("?") and bool(first) and first[0] in QUESTION_STARTERS


def first_answer(section: Section) -> str:
    for block in section.blocks:
        if block.text:
            return block.text
    return ""


def has_definition_detail_example(text: str) -> bool:
    lowered = text.lower()
    has_definition = bool(re.search(r"\b(?:is|are|means|refers to|defines|describes)\b", lowered))
    has_detail = word_count(text) >= 40
    has_example = bool(re.search(r"\b(?:for example|for instance|such as|e\.g\.)\b", lowered))
    return has_definition and has_detail and has_example


def is_fluffy(text: str) -> list[str]:
    lowered = text.lower()
    return [term for term in MARKETING_FLUFF if term in lowered]


def paragraph_too_long(text: str) -> bool:
    return len(text) > 330 or word_count(text) > 75


def add_finding(
    findings: list[Finding],
    severity: str,
    category: str,
    message: str,
    evidence: str,
    action: str,
) -> None:
    findings.append(Finding(severity, category, message, excerpt(evidence), action))


def analyze_sections(sections: list[Section], findings: list[Finding]) -> dict[str, int]:
    metrics = {
        "sections": len(sections),
        "question_headings": 0,
        "concise_answers": 0,
        "bullet_sections": 0,
        "numbered_sections": 0,
        "table_sections": 0,
        "definition_detail_example_sections": 0,
    }
    for section in sections:
        answer = first_answer(section)
        answer_words = word_count(answer)
        if is_question_heading(section.heading):
            metrics["question_headings"] += 1
        else:
            add_finding(
                findings,
                "high",
                "Heading structure",
                f"{section.level} should be rephrased as a direct question.",
                section.heading,
                f"Rewrite as a question, for example: 'What is {section.heading.rstrip('?')}?'",
            )
        if 40 <= answer_words <= 60:
            metrics["concise_answers"] += 1
        else:
            add_finding(
                findings,
                "high" if not answer else "medium",
                "Conciseness and directness",
                f"The first answer after '{section.heading}' is {answer_words} words; target 40-60 words.",
                answer or section.heading,
                "Place a clear 40-60 word answer immediately after the heading before expanding with details.",
            )
        if section.has_bullets:
            metrics["bullet_sections"] += 1
        if section.has_numbered_list:
            metrics["numbered_sections"] += 1
        if section.has_table:
            metrics["table_sections"] += 1
        if has_definition_detail_example(" ".join(block.text for block in section.blocks[:4])):
            metrics["definition_detail_example_sections"] += 1
        else:
            add_finding(
                findings,
                "low",
                "Answer hierarchy",
                f"'{section.heading}' does not clearly follow Definition -> Detail -> Example.",
                " ".join(block.text for block in section.blocks[:3]) or section.heading,
                "Structure the section as Definition -> Detail -> Example so LLMs can extract a standalone answer.",
            )
        for block in section.blocks:
            if block.tag == "p" and paragraph_too_long(block.text):
                add_finding(
                    findings,
                    "medium",
                    "Paragraph length",
                    "A paragraph appears longer than three readable lines.",
                    block.text,
                    "Split it into a short definition paragraph plus separate detail or example paragraphs.",
                )
            fluff = is_fluffy(block.text)
            if fluff:
                add_finding(
                    findings,
                    "medium",
                    "Marketing fluff",
                    f"Paragraph contains non-factual promotional language: {', '.join(fluff[:4])}.",
                    block.text,
                    "Replace promotional claims with factual definitions, data, constraints, outcomes, or cited proof.",
                )
    return metrics


def analyze_formatting(sections: list[Section], findings: list[Finding]) -> None:
    if not any(section.has_bullets for section in sections):
        add_finding(
            findings,
            "medium",
            "Content formatting",
            "No bullet lists were found in machine-liftable H2/H3 sections.",
            "No ul/li content detected",
            "Add bullet lists for attributes, requirements, benefits, risks, or steps where synthesis needs discrete facts.",
        )
    if not any(section.has_numbered_list for section in sections):
        add_finding(
            findings,
            "low",
            "Content formatting",
            "No numbered lists were found.",
            "No ol/li content detected",
            "Use numbered lists for procedures, prioritization, or step-by-step recommendations.",
        )
    if not any(section.has_table for section in sections):
        add_finding(
            findings,
            "medium",
            "Content formatting",
            "No comparison tables were found.",
            "No table content detected",
            "Add a concise comparison table near the first section that compares options, criteria, or use cases.",
        )


def analyze_schema(schemas: set[str], findings: list[Finding]) -> dict[str, bool]:
    detected = {schema: schema in schemas for schema in sorted(SCHEMA_TYPES)}
    if not any(detected.values()):
        add_finding(
            findings,
            "high",
            "Schema markup",
            "No target AEO schema types were found.",
            ", ".join(sorted(schemas)) or "No schema detected",
            "Insert JSON-LD for FAQPage, Article, and Organization in the HTML <head>; add HowTo or Product when the page intent matches.",
        )
    else:
        missing = [schema for schema, present in detected.items() if not present]
        if missing:
            add_finding(
                findings,
                "low",
                "Schema markup",
                f"Missing optional schema types: {', '.join(missing)}.",
                ", ".join(sorted(schemas)),
                "Add only schema that matches visible content. Place JSON-LD in the <head> or before </body> if your CMS restricts head edits.",
            )
    return detected


def analyze_eeat(html: str, meta: dict[str, str], visible_text: str, findings: list[Finding]) -> dict[str, bool]:
    text = f"{visible_text}\n{html[:20000]}"
    lowered = text.lower()
    signals = {
        "author": bool(meta.get("author") or re.search(r"\b(?:by|author|written by|reviewed by)\b", lowered)),
        "expert_bio": bool(re.search(r"\b(?:expert bio|reviewed by|medical reviewer|editorial review|credentials|phd|md|certified)\b", lowered)),
        "proprietary_data": any(marker in lowered for marker in PROPRIETARY_MARKERS),
        "freshness": bool(re.search(r"\b(?:last updated|updated on|published on|modified)\b", lowered)),
        "quote": bool(re.search(r'"[^"]{40,}"\s*(?:-|--|,?\s+(?:said|says|according to))', text, re.I)),
    }
    if not signals["author"]:
        add_finding(
            findings,
            "high",
            "E-E-A-T signals",
            "No clear author byline was detected.",
            meta.get("author", "") or "No byline phrase found",
            "Add a visible author byline near the title and connect it to Article schema author data.",
        )
    if not signals["expert_bio"]:
        add_finding(
            findings,
            "medium",
            "E-E-A-T signals",
            "No expert bio, reviewer, or credential signal was detected.",
            "No credential terms found",
            "Add a short expert bio, reviewer note, or credential block close to the article footer.",
        )
    if not signals["proprietary_data"]:
        add_finding(
            findings,
            "medium",
            "E-E-A-T signals",
            "No proprietary data, chart, benchmark, or case study marker was detected.",
            "No proprietary evidence markers found",
            "Add original visuals, charts, benchmarks, case study data, or expert quotes to improve citation trust.",
        )
    if not signals["freshness"]:
        add_finding(
            findings,
            "medium",
            "Freshness signals",
            "No Last Updated or equivalent freshness date was detected.",
            "No freshness phrase found",
            "Add a visible 'Last Updated' date and mirror it in Article schema dateModified.",
        )
    return signals


def parse_robot_groups(text: str) -> list[tuple[list[str], list[str]]]:
    groups: list[tuple[list[str], list[str]]] = []
    agents: list[str] = []
    disallows: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            if agents or disallows:
                groups.append((agents, disallows))
            agents, disallows = [], []
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "user-agent":
            if disallows:
                groups.append((agents, disallows))
                agents, disallows = [], []
            agents.append(value.lower())
        elif key == "disallow":
            disallows.append(value)
    if agents or disallows:
        groups.append((agents, disallows))
    return groups


def robot_blocks_bot(text: str, bot: str, path: str) -> bool:
    bot = bot.lower()
    path = path or "/"
    for agents, disallows in parse_robot_groups(text):
        if bot not in agents and "*" not in agents:
            continue
        for rule in disallows:
            if rule == "/":
                return True
            if rule and path.startswith(rule.rstrip("*")):
                return True
    return False


def check_robots(target_url: str, timeout: int = 15) -> RobotsStatus:
    parsed = urlparse(target_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = urljoin(root, "/robots.txt")
    status = RobotsStatus(url=robots_url, found=False)
    try:
        text, _, code = fetch_text(robots_url, timeout=timeout)
    except RuntimeError as exc:
        status.notes.append(str(exc))
        return status
    if code and code >= 400:
        status.notes.append(f"robots.txt returned HTTP {code}.")
        return status
    status.found = True
    path = parsed.path or "/"
    status.gptbot_blocked = robot_blocks_bot(text, "gptbot", path)
    status.ccbot_blocked = robot_blocks_bot(text, "ccbot", path)
    if status.gptbot_blocked:
        status.notes.append("GPTBot appears blocked for this URL path.")
    if status.ccbot_blocked:
        status.notes.append("CCBot appears blocked for this URL path.")
    if not status.notes:
        status.notes.append("No GPTBot or CCBot block was detected for this path.")
    return status


def check_llms_txt(target_url: str, timeout: int = 15) -> dict[str, Any]:
    parsed = urlparse(target_url)
    llms_url = f"{parsed.scheme}://{parsed.netloc}/llms.txt"
    try:
        text, _, code = fetch_text(llms_url, timeout=timeout)
    except RuntimeError as exc:
        return {"url": llms_url, "found": False, "notes": [str(exc)]}
    if code and code >= 400:
        return {"url": llms_url, "found": False, "notes": [f"llms.txt returned HTTP {code}."]}
    notes = ["llms.txt was found."]
    if not re.search(r"https?://|^#|\b(?:sitemap|docs|about|contact)\b", text, re.I | re.M):
        notes.append("File exists but may not provide clear LLM crawl guidance or canonical resources.")
    return {"url": llms_url, "found": True, "notes": notes}


def score(findings: list[Finding]) -> int:
    penalties = {"high": 10, "medium": 5, "low": 2}
    return max(0, 100 - sum(penalties[finding.severity] for finding in findings))


def audit_url(url: str, timeout: int = 15) -> dict[str, Any]:
    html, final_url, status_code = fetch_text(url, timeout=timeout)
    sections, meta, schemas, visible_text = extract_page(html)
    findings: list[Finding] = []

    if not sections:
        add_finding(
            findings,
            "high",
            "Crawl and extraction",
            "No H2/H3 machine-liftable content blocks were found in static HTML.",
            "No H2/H3 sections extracted",
            "Server-render key content or add static HTML summaries so AI crawlers do not depend on client-side JavaScript.",
        )
    section_metrics = analyze_sections(sections, findings)
    analyze_formatting(sections, findings)
    schema_status = analyze_schema(schemas, findings)
    eeat_status = analyze_eeat(html, meta, visible_text, findings)
    robots_status = check_robots(final_url, timeout=timeout)
    llms_status = check_llms_txt(final_url, timeout=timeout)

    if robots_status.gptbot_blocked or robots_status.ccbot_blocked:
        add_finding(
            findings,
            "high",
            "Technical readiness",
            "AI crawlers appear blocked in robots.txt.",
            "; ".join(robots_status.notes),
            "Update robots.txt to allow GPTBot and CCBot for public pages intended to be cited or summarized.",
        )
    if not llms_status["found"]:
        add_finding(
            findings,
            "medium",
            "Technical readiness",
            "No llms.txt file was found.",
            "; ".join(llms_status["notes"]),
            "Publish /llms.txt with canonical page groups, documentation links, brand/entity details, and preferred citation resources.",
        )

    findings.sort(key=lambda item: ({"high": 0, "medium": 1, "low": 2}[item.severity], item.category, item.message))
    return {
        "url": url,
        "final_url": final_url,
        "status_code": status_code,
        "score": score(findings),
        "summary": {
            **section_metrics,
            "schemas_detected": sorted(schemas),
            "target_schema_status": schema_status,
            "eeat_status": eeat_status,
            "robots": asdict(robots_status),
            "llms_txt": llms_status,
        },
        "machine_liftable_sections": [
            {
                "level": section.level,
                "heading": section.heading,
                "is_question": is_question_heading(section.heading),
                "first_answer_words": word_count(first_answer(section)),
                "has_bullets": section.has_bullets,
                "has_numbered_list": section.has_numbered_list,
                "has_table": section.has_table,
                "first_answer": excerpt(first_answer(section), 300),
            }
            for section in sections
        ],
        "findings": [asdict(finding) for finding in findings],
        "aeo_action_plan": build_action_plan(findings),
    }


def build_action_plan(findings: list[Finding]) -> list[str]:
    plan = [
        "Modularize content: make every H2/H3 block a standalone module that makes sense when extracted without the rest of the page.",
        "Use the Answer Hierarchy: start each section with Definition -> Detail -> Example before adding nuance.",
        "Add freshness signals: include a visible Last Updated date and dateModified in Article schema.",
        "Keep entity consistency: use the full brand name consistently across headings, intro copy, schema, author bio, and organization references.",
    ]
    seen: set[str] = set(plan)
    for finding in findings:
        step = finding.action
        if step not in seen:
            plan.append(step)
            seen.add(step)
    return plan


def format_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"# AEO Readiness Audit: {report['final_url']}",
        "",
        f"Score: **{report['score']}/100**",
        "",
        "## Snapshot",
        f"- Static H2/H3 modules found: {summary['sections']}",
        f"- Question-style headings: {summary['question_headings']}",
        f"- 40-60 word direct answers: {summary['concise_answers']}",
        f"- Sections with bullets / numbered lists / tables: {summary['bullet_sections']} / {summary['numbered_sections']} / {summary['table_sections']}",
        f"- Schemas detected: {', '.join(summary['schemas_detected']) or 'None'}",
        f"- robots.txt: {'found' if summary['robots']['found'] else 'not found'}; GPTBot blocked: {summary['robots']['gptbot_blocked']}; CCBot blocked: {summary['robots']['ccbot_blocked']}",
        f"- llms.txt: {'found' if summary['llms_txt']['found'] else 'not found'}",
        "",
        "## AEO Action Plan",
    ]
    lines.extend(f"{index}. {item}" for index, item in enumerate(report["aeo_action_plan"], start=1))
    lines.extend(["", "## Findings"])
    for finding in report["findings"]:
        lines.extend(
            [
                f"### [{finding['severity'].upper()}] {finding['category']}",
                finding["message"],
                f"- Evidence: {finding['evidence']}",
                f"- Action: {finding['action']}",
                "",
            ]
        )
    lines.extend(["## Machine-Liftable Sections"])
    for section in report["machine_liftable_sections"]:
        lines.extend(
            [
                f"- {section['level']} {section['heading']}",
                f"  - Question heading: {section['is_question']}",
                f"  - First answer words: {section['first_answer_words']}",
                f"  - Formats: bullets={section['has_bullets']}, numbered={section['has_numbered_list']}, table={section['has_table']}",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a 2026 AEO readiness audit against a URL.")
    parser.add_argument("url", help="URL to crawl and audit.")
    parser.add_argument("--format", choices={"markdown", "json"}, default="markdown", help="Output format.")
    parser.add_argument("--timeout", type=int, default=15, help="HTTP timeout in seconds.")
    parser.add_argument("--output", help="Optional file path for the report.")
    args = parser.parse_args(argv)

    report = audit_url(args.url, timeout=args.timeout)
    output = json.dumps(report, indent=2, ensure_ascii=False) if args.format == "json" else format_markdown(report)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(output)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
