#!/usr/bin/env python3
"""
Parse CityStrides HTML data to extract useful information.
Processes the downloaded HTML files and extracts:
- City name
- Coverage percentage
- Total streets
- Streets completed
- Progress data
"""

import os
import json
import re
from pathlib import Path
from html.parser import HTMLParser


class CityStridesParser(HTMLParser):
    """Parse CityStrides HTML pages to extract data."""

    def __init__(self):
        super().__init__()
        self.city_name = None
        self.coverage = None
        self.streets_total = None
        self.streets_completed = None
        self.data = {}
        self.in_script = False
        self.script_content = ""

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.in_script = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_script = False
            # Try to extract JSON data from script content
            self._extract_json()
            self.script_content = ""

    def handle_data(self, data):
        if self.in_script:
            self.script_content += data

    def _extract_json(self):
        """Extract JSON data from script tags."""
        try:
            # Look for window.INITIAL_STATE or similar data patterns
            if "window." in self.script_content:
                # Find JSON objects in the script
                json_match = re.search(r"\{[^{}]*\".*?\"[^{}]*\}", self.script_content)
                if json_match:
                    try:
                        json_data = json.loads(json_match.group())
                        self.data.update(json_data)
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            pass


def parse_citystrides_file(html_file):
    """Parse a single CityStrides HTML file."""
    try:
        with open(html_file, "r", encoding="utf-8") as f:
            content = f.read()

        parser = CityStridesParser()
        parser.feed(content)

        # Try to extract useful data from HTML
        result = {
            "file": os.path.basename(html_file),
            "city_id": os.path.basename(html_file).split("_")[1].split(".")[0],
        }

        # Look for title tag which usually contains the city name
        title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
        if title_match:
            result["city_name"] = title_match.group(1).strip()

        # Look for coverage percentage (usually in format like "45.23%")
        coverage_match = re.search(r"(\d+\.?\d*)\s*%", content)
        if coverage_match:
            result["coverage"] = float(coverage_match.group(1))

        return result
    except Exception as e:
        return {"file": os.path.basename(html_file), "error": str(e)}


def main():
    """Main function to process all downloaded CityStrides data."""
    data_dir = Path("citystrides_data")

    if not data_dir.exists():
        print(f"Error: {data_dir} directory not found")
        print("Run fetch_citystrides_data.sh or .bat first")
        return

    html_files = sorted(data_dir.glob("city_*.html"))
    print(f"Found {len(html_files)} HTML files")
    print()

    results = []
    for i, html_file in enumerate(html_files, 1):
        print(f"[{i}/{len(html_files)}] Processing {html_file.name}...", end=" ")
        result = parse_citystrides_file(html_file)
        results.append(result)

        if "error" not in result:
            city_name = result.get("city_name", "Unknown")
            coverage = result.get("coverage", "N/A")
            print(f"✓ ({city_name}: {coverage}%)" if isinstance(coverage, (int, float)) else f"✓")
        else:
            print(f"✗ (Error: {result['error']})")

    # Save results to JSON file
    output_file = Path("citystrides_parsed_data.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print()
    print(f"Results saved to {output_file}")
    print(f"Successfully parsed: {sum(1 for r in results if 'error' not in r)}/{len(results)}")


if __name__ == "__main__":
    main()
