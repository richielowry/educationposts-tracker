# EducationPosts Job Tracker

Automatically scrapes primary-level vacancies in **Kilkenny** and **Laois** from
[educationposts.ie](https://www.educationposts.ie) and appends new listings to a
Google Sheet — including geocoded address and distance from Kilkenny city.

Runs every morning at 7:30am via GitHub Actions.

---

## Setup checklist

### 1. Google Sheet
- Sheet must have this header row in row 1:
  `ID | School Name | Address | KM to Kilkenny City | Type of Vacancy | Status of Post | County | Application Deadline | Applied | Notes`
- Share the sheet with your service account email (Editor access)

### 2. GitHub Secrets
Go to: **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full contents of your service account `.json` key file |
| `SHEET_ID` | The long ID from your Sheet URL: `.../spreadsheets/d/THIS_PART/edit` |

### 3. Enable Actions
Go to the **Actions** tab in your GitHub repo and enable workflows if prompted.

### 4. Test manually
Go to **Actions → EducationPosts Job Scraper → Run workflow** to trigger a manual run
and confirm rows appear in your sheet before relying on the daily schedule.

---

## How it works

1. Fetches all pages of primary-level results from educationposts.ie
2. Filters for Kilkenny and Laois jobs only
3. Compares job IDs against column A in your sheet — skips any already present
4. For each new job, calls OpenStreetMap Nominatim to geocode the school name
5. Calculates straight-line distance (km) from Kilkenny city centre
6. Appends a new row to the sheet

## Customising

- **Add more counties**: edit `TARGET_COUNTIES` in `scraper.py`
- **Change schedule**: edit the `cron` line in `.github/workflows/job_scraper.yml`
  (uses UTC — Ireland is UTC+1 in summer)
- **Add post-primary**: duplicate the scrape call with `/posts/second_level` URL
