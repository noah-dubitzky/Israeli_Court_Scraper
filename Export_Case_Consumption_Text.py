"""Export a case-consumption output folder to a readable UTF-8 text document."""

import argparse
import json
import re
from pathlib import Path


def label(key):
    if key == "ID":
        return "Internal case ID"
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", key.replace("_", " ")).capitalize()


def render(value, indent=0):
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return [prefix + "No data recorded."]
        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(prefix + label(key) + ":")
                lines.extend(render(item, indent + 2))
            else:
                text = "Not recorded" if item is None else (
                    "Yes" if item is True else "No" if item is False else str(item) or "(empty)"
                )
                parts = text.splitlines() or ["(empty)"]
                lines.append(prefix + label(key) + ": " + parts[0])
                lines.extend(prefix + "  " + part for part in parts[1:])
        return lines
    if isinstance(value, list):
        if not value:
            return [prefix + "None."]
        lines = []
        for index, item in enumerate(value, 1):
            if isinstance(item, (dict, list)):
                lines.append(prefix + f"Item {index}")
                lines.extend(render(item, indent + 2))
                lines.append("")
            else:
                lines.append(prefix + f"{index}. {item}")
        return lines
    return [prefix + str(value)]


def export(directory, output):
    summary = json.loads((directory / "summary.json").read_text(encoding="utf-8-sig"))
    lines = ["COURT CASE EXTRACTION REPORT", "=" * 80,
             "Source: " + directory.name, "",
             "RUN SUMMARY", "-" * 80]
    lines.extend(render({key: value for key, value in summary.items() if key != "cases"}))
    for index, entry in enumerate(summary["cases"], 1):
        path = directory / entry["file"]
        record = json.loads(path.read_text(encoding="utf-8-sig"))
        lines.extend(["", "=" * 80, f"CASE {index}: {record['number']}", "=" * 80,
                      "EXTRACTION MEASUREMENTS", "-" * 80])
        lines.extend(render(entry))
        lines.extend(["", "GENERAL CASE DATA", "-" * 80])
        lines.extend(render({key: value for key, value in record.items() if key != "details"}))
        lines.extend(["", "EXTRACTED CASE DETAILS", "-" * 80])
        lines.extend(render(record.get("details", {})))
    output.parent.mkdir(parents=True, exist_ok=True)
    # A BOM lets Windows editors detect Hebrew UTF-8 text reliably.
    output.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return len(summary["cases"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    destination = args.output or args.directory / "readable_cases.txt"
    count = export(args.directory, destination)
    print(f"Exported {count} cases to {destination.resolve()}")
