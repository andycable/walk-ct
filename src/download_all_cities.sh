#!/bin/bash

# Simple curl loop to download all CityStrides city pages
# Since it's a React SPA, we're getting the HTML shell but this can be used with Playwright/Puppeteer later

USER_ID="43318"
OUTPUT_DIR="citystrides_data"

mkdir -p "$OUTPUT_DIR"

# Extract city IDs from Towns.md
echo "Extracting city IDs from Towns.md..."
CITY_IDS=$(grep -o 'cities/[0-9]*' Towns.md | cut -d'/' -f2 | sort -u)

TOTAL=$(echo "$CITY_IDS" | wc -l)
COUNT=0

echo "Found $TOTAL unique cities"
echo "Starting fetch..."
echo ""

while IFS= read -r CITY_ID; do
    COUNT=$((COUNT + 1))
    URL="https://citystrides.com/users/$USER_ID/cities/$CITY_ID"
    OUTPUT_FILE="$OUTPUT_DIR/${CITY_ID}.html"

    printf "[%3d/%d] City %s: " "$COUNT" "$TOTAL" "$CITY_ID"

    if curl -s -L \
        -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
        -o "$OUTPUT_FILE" \
        "$URL"; then
        echo "✓"
    else
        echo "✗"
        rm -f "$OUTPUT_FILE"
    fi

    sleep 0.5
done <<< "$CITY_IDS"

echo ""
echo "Complete! Downloaded $(ls -1 "$OUTPUT_DIR" 2>/dev/null | wc -l) files to $OUTPUT_DIR/"
