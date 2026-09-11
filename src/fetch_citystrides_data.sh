#!/bin/bash

# Fetch CityStrides data for all 169 Connecticut towns
# Extracts city IDs from Towns.md and fetches data via curl

OUTPUT_DIR="./citystrides_data"
TOWNS_FILE="./Towns.md"
USER_ID="43318"

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Extract all city IDs from Towns.md
# Pattern: /users/43318/cities/XXXXX
echo "Extracting city IDs from $TOWNS_FILE..."
CITY_IDS=$(grep -oP 'cities/\K[0-9]+' "$TOWNS_FILE" | sort -u)

TOTAL=$(echo "$CITY_IDS" | wc -l)
COUNT=0

echo "Found $TOTAL unique cities"
echo "Starting fetch..."
echo ""

# Loop through each city ID and fetch the page
while IFS= read -r CITY_ID; do
    COUNT=$((COUNT + 1))
    URL="https://citystrides.com/users/$USER_ID/cities/$CITY_ID"
    OUTPUT_FILE="$OUTPUT_DIR/city_$CITY_ID.html"

    printf "[%3d/%d] Fetching city ID %s..." "$COUNT" "$TOTAL" "$CITY_ID"

    # Fetch with curl - add User-Agent to avoid being blocked
    if curl -s -L \
        -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
        "$URL" > "$OUTPUT_FILE" 2>/dev/null; then

        # Check if we got a valid response (file has content)
        if [ -s "$OUTPUT_FILE" ]; then
            echo " ✓"
        else
            echo " ✗ (empty response)"
            rm "$OUTPUT_FILE"
        fi
    else
        echo " ✗ (curl failed)"
        rm -f "$OUTPUT_FILE"
    fi

    # Add a small delay to be respectful to the server (500ms)
    sleep 0.5
done <<< "$CITY_IDS"

echo ""
echo "Fetch complete! Data saved to $OUTPUT_DIR/"
echo "Total files created: $(ls -1 "$OUTPUT_DIR" 2>/dev/null | wc -l)"
