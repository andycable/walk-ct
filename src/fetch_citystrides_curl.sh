#!/bin/bash

# Fetch all CityStrides data for Connecticut towns using curl

USER_ID="43318"
OUTPUT_DIR="citystrides_data"
CITY_IDS_FILE="city_ids.txt"

mkdir -p "$OUTPUT_DIR"

# Extract city IDs if not already done
if [ ! -f "$CITY_IDS_FILE" ]; then
    echo "Extracting city IDs from Towns.md..."
    grep -o 'cities/[0-9]*' Towns.md | cut -d'/' -f2 | sort -u > "$CITY_IDS_FILE"
fi

TOTAL=$(wc -l < "$CITY_IDS_FILE")
COUNT=0

echo "Fetching data for $TOTAL cities..."
echo ""

while IFS= read -r CITY_ID; do
    COUNT=$((COUNT + 1))
    URL="https://citystrides.com/users/$USER_ID/cities/$CITY_ID"
    OUTPUT_FILE="$OUTPUT_DIR/city_${CITY_ID}.json"

    printf "[%3d/%d] City ID %s: " "$COUNT" "$TOTAL" "$CITY_ID"

    # Fetch the page and extract data
    RESPONSE=$(curl -s -L \
        -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
        "$URL")

    if [ -n "$RESPONSE" ]; then
        echo "$RESPONSE" > "$OUTPUT_FILE"
        echo "✓"
    else
        echo "✗"
    fi

    sleep 0.3
done < "$CITY_IDS_FILE"

echo ""
echo "Complete! Data saved to $OUTPUT_DIR/"
ls -1 "$OUTPUT_DIR" | wc -l
echo "files created"
