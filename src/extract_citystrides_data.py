#!/usr/bin/env python3
"""
Extract CityStrides data using Playwright headless browser.
Renders each town's page and extracts progress metrics.
"""

import os
import json
import csv
from pathlib import Path
from playwright.sync_api import sync_playwright
import re


def extract_data_from_page(page):
    """Extract useful data from a rendered CityStrides page."""
    try:
        # Get page title
        title = page.title()

        # Extract town name from title
        # Format: "Andy Cable is running {Town}, Connecticut - CityStrides"
        town_match = re.search(r'is running ([^,]+), Connecticut', title)
        town_name = town_match.group(1) if town_match else "Unknown"

        # Wait for content to load
        page.wait_for_load_state('networkidle')

        # Try to extract completion percentage from the page
        # Look for common patterns like "45.23%" or "45.23 %"
        page_content = page.content()

        coverage = None

        # Look for percentage in various formats
        percentage_patterns = [
            r'(\d+\.?\d*)\s*%',  # e.g., "45.23%" or "45 %"
            r'"percentage":\s*(\d+\.?\d*)',  # JSON format
            r'completion["\']?\s*[:=]\s*(\d+\.?\d*)',  # completion: 45.23
        ]

        for pattern in percentage_patterns:
            match = re.search(pattern, page_content, re.IGNORECASE)
            if match:
                coverage = float(match.group(1))
                break

        # Try to get text content that might have completion info
        try:
            # Look for elements with completion/coverage text
            completion_text = page.query_selector_all('text=completed')
            if completion_text:
                for elem in completion_text:
                    try:
                        text = elem.text_content()
                        if text:
                            # Try to extract percentage from text
                            match = re.search(r'(\d+\.?\d*)\s*%', text)
                            if match and not coverage:
                                coverage = float(match.group(1))
                                break
                    except:
                        pass
        except:
            pass

        return {
            "town_name": town_name,
            "coverage_percent": coverage,
            "page_title": title,
            "success": True
        }

    except Exception as e:
        return {
            "town_name": "Unknown",
            "coverage_percent": None,
            "error": str(e),
            "success": False
        }


def main():
    """Main function to extract data from all CityStrides city pages."""
    data_dir = Path("citystrides_data")

    if not data_dir.exists():
        print(f"Error: {data_dir} directory not found")
        return

    html_files = sorted(data_dir.glob("*.html"))
    print(f"Found {len(html_files)} HTML files")
    print("Starting extraction with Playwright...")
    print()

    results = []

    with sync_playwright() as p:
        # Launch browser once and reuse for speed
        browser = p.chromium.launch(headless=True)

        for i, html_file in enumerate(html_files, 1):
            city_id = html_file.stem
            print(f"[{i:3d}/{len(html_files)}] City {city_id}: ", end="", flush=True)

            try:
                # Create a new page for each city
                page = browser.new_page()

                # Load the local HTML file
                file_url = f"file:///{html_file.resolve()}".replace("\\", "/")
                page.goto(file_url, wait_until="networkidle", timeout=30000)

                # Extract data
                data = extract_data_from_page(page)
                data["city_id"] = city_id
                results.append(data)

                if data["success"]:
                    town = data.get("town_name", "Unknown")
                    coverage = data.get("coverage_percent")
                    if coverage is not None:
                        print(f"[OK] {town} ({coverage:.1f}%)")
                    else:
                        print(f"[OK] {town}")
                else:
                    print(f"[FAIL] (Error: {data.get('error', 'Unknown')})")

                page.close()

            except Exception as e:
                print(f"[FAIL] (Exception: {str(e)[:50]})")
                results.append({
                    "city_id": city_id,
                    "success": False,
                    "error": str(e)
                })

        browser.close()

    # Save results to JSON
    json_output = Path("citystrides_extracted_data.json")
    with open(json_output, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nJSON results saved to {json_output}")

    # Save results to CSV
    csv_output = Path("citystrides_extracted_data.csv")
    with open(csv_output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["city_id", "town_name", "coverage_percent", "success", "error"]
        )
        writer.writeheader()
        for result in results:
            writer.writerow({
                "city_id": result.get("city_id", ""),
                "town_name": result.get("town_name", "Unknown"),
                "coverage_percent": result.get("coverage_percent", ""),
                "success": result.get("success", False),
                "error": result.get("error", "")
            })
    print(f"CSV results saved to {csv_output}")

    # Summary
    successful = sum(1 for r in results if r.get("success"))
    with_coverage = sum(1 for r in results if r.get("coverage_percent") is not None)

    print()
    print(f"Summary:")
    print(f"  Total cities: {len(results)}")
    print(f"  Successfully processed: {successful}")
    print(f"  With coverage data: {with_coverage}")


if __name__ == "__main__":
    main()
