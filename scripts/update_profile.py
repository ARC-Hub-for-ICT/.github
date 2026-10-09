"""Refresh the GitHub organisation profile from the public ARC Hub project API."""

from __future__ import annotations

import html
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import json


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "profile" / "README.md"
API_URL = "https://ict.archub.ie/wp-json/wp/v2/arc_projects"
START = "<!-- projects:start -->"
END = "<!-- projects:end -->"
DIRECTORY = "https://ict.archub.ie/arc-hub-for-ict-projects/"


class PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def plain_text(value: str) -> str:
    parser = PlainText()
    parser.feed(value)
    return " ".join(html.unescape(" ".join(parser.parts)).split())


def markdown_text(value: str) -> str:
    return re.sub(r"([\\`*_{}\[\]#+!|<>])", r"\\\1", value)


def fetch_projects() -> tuple[list[dict], int]:
    projects: list[dict] = []
    page = 1
    total = 0
    total_pages = 1
    while page <= total_pages:
        query = urlencode({"per_page": 100, "page": page, "_fields": "link,title,excerpt"})
        request = Request(
            f"{API_URL}?{query}",
            headers={"User-Agent": "ARC-Hub-GitHub-profile/1.0"},
        )
        with urlopen(request, timeout=25) as response:
            page_total = int(response.headers["X-WP-Total"])
            page_count = int(response.headers["X-WP-TotalPages"])
            page_projects = json.load(response)
        if page == 1:
            total, total_pages = page_total, page_count
        elif (page_total, page_count) != (total, total_pages):
            raise ValueError("Project count changed during refresh; retry on the next run")
        if not isinstance(page_projects, list):
            raise ValueError("The project API returned invalid data")
        projects.extend(page_projects)
        page += 1
    if not projects or len(projects) != total:
        raise ValueError("The project API did not return the full directory")
    return projects, total


def render_projects(projects: list[dict], total: int) -> str:
    entries = []
    seen_urls = set()
    for project in projects:
        url = project["link"]
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "ict.archub.ie" or not parsed.path.startswith("/projects/"):
            raise ValueError(f"Unexpected project URL: {url}")
        raw_title = plain_text(project["title"]["rendered"])
        title = markdown_text(raw_title)
        description_text = plain_text(project["excerpt"]["rendered"])
        sentences = re.split(r"(?<=[.!?])\s+", description_text)
        description = sentences[0]
        title_lower = raw_title.casefold()
        if (len(description) > 160 and title_lower not in description.casefold()) or f"({title_lower})" in description.casefold():
            for sentence in sentences[1:8]:
                if sentence.casefold().startswith((title_lower, "this project")):
                    description = sentence
                    break
        description = markdown_text(description)
        if not title or not description or url in seen_urls:
            raise ValueError("A project has missing information or a duplicate URL")
        seen_urls.add(url)
        entries.append((raw_title.casefold(), title, url, description))
    lines = [f"**All {total} projects**, alphabetically. Each link opens its full profile on [our website]({DIRECTORY}).", ""]
    lines.extend(f"- **[{title}]({url})** — {description}" for _, title, url, description in sorted(entries))
    return "\n".join(lines)


def main() -> None:
    projects, total = fetch_projects()
    readme = README.read_text(encoding="utf-8")
    if readme.count(START) != 1 or readme.count(END) != 1:
        raise ValueError("Expected one pair of project markers in the README")
    before, rest = readme.split(START, 1)
    _, after = rest.split(END, 1)
    updated = before + START + "\n" + render_projects(projects, total) + "\n" + END + after
    if updated != readme:
        README.write_text(updated, encoding="utf-8")


if __name__ == "__main__":
    main()
