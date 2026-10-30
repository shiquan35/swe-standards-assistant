"""Display a handbook topic's title and root section source ranges."""

import argparse
from pathlib import Path

from app.ingestion import parse_markdown_file


def main() -> None:
    """Parse the supplied topic, defaulting to the API standards example."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path(__file__).parent
        / "knowledge_base"
        / "engineering-handbook"
        / "api-standards.md",
        help="Markdown file to parse (default: API standards handbook topic).",
    )
    args = parser.parse_args()
    document = parse_markdown_file(args.path)

    print(f"Title: {document.title}")  # noqa: T201 - CLI output
    print(f"Source: {document.source_path}")  # noqa: T201 - CLI output
    for section in document.sections:
        heading_path = " > ".join(section.heading_path)
        source_range = section.source_range
        print(  # noqa: T201 - CLI output
            f"{heading_path}: lines {source_range.start_line}-{source_range.end_line}"
        )


if __name__ == "__main__":
    main()
