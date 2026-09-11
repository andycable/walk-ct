@echo off
REM Fetch CityStrides data for all 169 Connecticut towns
REM Extracts city IDs from Towns.md and fetches data via curl

setlocal enabledelayedexpansion

set OUTPUT_DIR=citystrides_data
set TOWNS_FILE=Towns.md
set USER_ID=43318

REM Create output directory if it doesn't exist
if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

echo Extracting city IDs from %TOWNS_FILE%...

REM Extract city IDs from Towns.md using findstr
REM This will find all lines with 'cities/' and extract the ID
for /f "tokens=* delims=" %%A in ('findstr /R "cities/[0-9]" "%TOWNS_FILE%"') do (
    for /f "tokens=1 delims=/" %%B in ("%%A") do (
        if "%%B"=="cities" (
            REM Extract the city ID number
            for /f "tokens=2 delims=/" %%C in ("%%A") do (
                set CITY_IDS=!CITY_IDS! %%C
            )
        )
    )
)

echo.
echo Starting fetch...
echo.

set COUNT=0
for %%I in (%CITY_IDS%) do (
    set /a COUNT=!COUNT!+1
    set CITY_ID=%%I
    set URL=https://citystrides.com/users/%USER_ID%/cities/!CITY_ID!
    set OUTPUT_FILE=%OUTPUT_DIR%\city_!CITY_ID!.html

    echo [!COUNT!] Fetching city ID !CITY_ID! ...

    REM Fetch with curl
    curl -s -L ^
        -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" ^
        "!URL!" > "!OUTPUT_FILE!"

    REM Add a small delay to be respectful to the server (1 second)
    timeout /t 1 /nobreak > nul
)

echo.
echo Fetch complete! Data saved to %OUTPUT_DIR%
echo.
pause
