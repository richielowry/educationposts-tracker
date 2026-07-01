"""
EducationPosts.ie → Google Sheets scraper
Fetches primary-level vacancies in Kilkenny & Laois,
geocodes each school via Nominatim, computes distance
from Kilkenny city, and appends new rows to a Google Sheet.
"""

import os
import re
import json
import math
import time
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

KILKENNY_CITY_LAT = 52.6541
KILKENNY_CITY_LON = -7.2448

TARGET_COUNTIES = {"Kilkenny", "Laois"}

BASE_URL = "https://www.educationposts.ie"
SEARCH_URL = f"{BASE_URL}/posts/primary_level"

PAGE_SIZE = 50

# ---------------------------------------------------------------------------
# Google Sheets
# ---------------------------------------------------------------------------

def get_worksheet():
    sa_info = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    creds = Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    gc = gspread.authorize(creds)
    sheet_id = os.environ["SHEET_ID"]
    return gc.open_by_key(sheet_id).sheet1


def get_existing_ids(ws):
    """Return a set of job IDs already in column A (excluding header)."""
    values = ws.col_values(1)
    return set(str(v).strip() for v in values[1:] if v)


# ---------------------------------------------------------------------------
# Distance
# ---------------------------------------------------------------------------

def haversine_km(lat, lon):
    R = 6371
    lat1 = math.radians(KILKENNY_CITY_LAT)
    lon1 = math.radians(KILKENNY_CITY_LON)
    lat2 = math.radians(lat)
    lon2 = math.radians(lon)
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return round(2 * R * math.asin(math.sqrt(a)), 1)


# ---------------------------------------------------------------------------
# Geocoding via Nominatim (free, no API key)
# ---------------------------------------------------------------------------

NOMINATIM_HEADERS = {
    "User-Agent": "EducationPostsTracker/1.0 (personal job alert tool)"
}


def geocode_school(school_name, county):
    """
    Try two queries: specific school name first, then county-only fallback.
    Returns (short_address, lat, lon) or ("", None, None) on failure.
    """
    queries = [
        f"{school_name}, Co. {county}, Ireland",
        f"{school_name}, {county}, Ireland",
    ]
    for query in queries:
        try:
            resp = requests.get(
                "https://nominatim.openstreetmap.org/search",
                params={"q": query, "format": "json", "limit": 1, "countrycodes": "ie"},
                headers=NOMINATIM_HEADERS,
                timeout=10
            )
            results = resp.json()
            if results:
                lat = float(results[0]["lat"])
                lon = float(results[0]["lon"])
                raw = results[0].get("display_name", "")
                parts = [p.strip() for p in raw.split(",")]
                address = ", ".join(parts[:4]) if len(parts) >= 4 else raw
                return address, lat, lon
        except Exception as e:
            print(f"  Geocode error for '{query}': {e}")
        time.sleep(1.1)  # Nominatim rate limit: max 1 request/second

    return "", None, None


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

SCRAPE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; personal job alert script)"
}

DATE_RE  = re.compile(r"\d{2}/\d{2}/\d{4}")
TOTAL_RE = re.compile(r"of\s+([\d,]+)\s*\)", re.IGNORECASE)


def clean_deadline(raw):
    """Extract DD/MM/YYYY from strings like '15/07/202615-Jul'."""
    m = DATE_RE.search(raw)
    return m.group(0) if m else raw.strip()


def parse_max_pages(soup):
    """
    Read 'Showing 1 to 50 (of 1626)' to calculate the real number of pages.
    Returns an int, or 50 as a safe fallback if the text isn't found.
    """
    text = soup.get_text(" ")
    m = TOTAL_RE.search(text)
    if m:
        total = int(m.group(1).replace(",", ""))
        pages = math.ceil(total / PAGE_SIZE)
        print(f"  Site reports {total} total listings → {pages} pages to fetch")
        return pages
    print("  Warning: could not read total listing count; using fallback of 50 pages")
    return 50


def scrape_jobs():
    """
    Scrape all pages of primary_level results, return list of dicts
    for Kilkenny and Laois only.
    """
    jobs = []
    seen_ids = set()   # deduplicate within this run
    max_pages = None
    page = 1

    while True:
        url = f"{SEARCH_URL}?p={page}&sb=application_closing_date&sd=0"
        label = f"{page}/{max_pages}" if max_pages else str(page)
        print(f"Fetching page {label}: {url}")

        try:
            resp = requests.get(url, headers=SCRAPE_HEADERS, timeout=20)
            resp.raise_for_status()
        except Exception as e:
            print(f"  Request error on page {page}: {e}")
            break

        soup = BeautifulSoup(resp.text, "html.parser")

        # First page only: read the total count to know when to stop
        if page == 1:
            max_pages = parse_max_pages(soup)

        table = soup.find("table")
        if not table:
            print("  No table found — stopping.")
            break

        rows = table.find_all("tr")[1:]   # skip header row
        if not rows:
            print("  Empty table — stopping.")
            break

        found_on_page = 0
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 6:
                continue

            job_id   = cells[0].get_text(strip=True)
            school   = cells[1].get_text(strip=True)
            vacancy  = cells[2].get_text(strip=True)
            status   = cells[3].get_text(strip=True)
            county   = cells[4].get_text(strip=True)
            deadline = clean_deadline(cells[5].get_text(strip=True))

            if county in TARGET_COUNTIES and job_id not in seen_ids:
                jobs.append({
                    "id":       job_id,
                    "school":   school,
                    "vacancy":  vacancy,
                    "status":   status,
                    "county":   county,
                    "deadline": deadline,
                    "link":     f"{BASE_URL}/post/view/{job_id}",
                })
                found_on_page += 1

            seen_ids.add(job_id)

        print(f"  Found {found_on_page} new Kilkenny/Laois jobs on page {page}")

        # Stop when we've fetched the last real page
        if page >= max_pages:
            print(f"  Reached last page ({max_pages}) — finished.")
            break

        page += 1
        time.sleep(1)   # be polite to the server

    return jobs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== EducationPosts scraper starting ===")

    print("Connecting to Google Sheet...")
    ws = get_worksheet()
    existing_ids = get_existing_ids(ws)
    print(f"  {len(existing_ids)} existing job IDs already in sheet")

    print("Scraping educationposts.ie...")
    all_jobs = scrape_jobs()
    new_jobs = [j for j in all_jobs if j["id"] not in existing_ids]
    print(f"Total Kilkenny/Laois jobs found: {len(all_jobs)}, new this run: {len(new_jobs)}")

    if not new_jobs:
        print("No new jobs — nothing to append.")
        return

    for i, job in enumerate(new_jobs, 1):
        print(f"[{i}/{len(new_jobs)}] {job['school']} ({job['county']}) ...")

        address, lat, lon = geocode_school(job["school"], job["county"])
        km = haversine_km(lat, lon) if lat is not None else ""

        print(f"  → {address or 'could not geocode'}  {f'({km} km)' if km else ''}")

        row = [
            job["id"],
            job["school"],
            address,
            km,
            job["vacancy"],
            job["status"],
            job["county"],
            job["deadline"],
            "",   # Applied  — left blank for manual entry
            "",   # Notes    — left blank
        ]

        ws.append_row(row, value_input_option="USER_ENTERED")
        time.sleep(0.5)

    print(f"=== Done. Appended {len(new_jobs)} new rows. ===")


if __name__ == "__main__":
    main()
