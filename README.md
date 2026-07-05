# AllManga.to Manga & Anime Metadata Scraper

A robust, production-grade Python scraper that extracts the entire manga and anime catalog from `allmanga.to` using their internal GraphQL endpoints, storing everything in both JSON format and a SQLite database.

Designed specifically to run on your local machine or seamlessly inside a **Google Colab** environment with automated **Google Drive** storage and interruption-resilient resuming.

---

## Technical Overview & Capping Bypass

### The 2,000-Record Capping Limitation
The AllManga GraphQL backend limits standard pagination queries to **100 pages** (or **2,000 items**). Any query requesting page `101` wraps around to page `1` results. 

### The Partitioning Solution
To extract the complete database (over 216,000 manga and 24,000 anime records), the scraper implements **two-dimensional query partitioning**:
1. **Year Partitioning**: Splits queries by release year from `1940` to `2026`. For most years, the total count is well under 2,000 records.
2. **Country Partitioning**: For years that exceed 2,000 records (e.g. 2018-2024), the scraper splits queries by country of origin (`JP`, `CN`, `KR`, `OTHER`), keeping each batch size under 2,000 items.

By query partitioning, the script retrieves **100% of the catalog** without hitting pagination capping thresholds.

---

## Features

- **Double Format Output**: Saves data in JSON lists and a structured SQLite database (`metadata.db`).
- **BLOB Thumbnail Storage**: Resolvescover image CDNs (`https://aln.youtube-anime.com/`) for relative covers, downloads the binary content, and stores it in the database as a `BLOB`.
- **Granular Progress Resuming**: Writes partition progress to `scraping_progress.json` after every page. If interrupted, simply restart the scraper to resume from the exact year, country, and page.
- **Atomic Writing**: Writes to a temporary `.tmp` file before replacing the target JSON to prevent file corruption during sudden execution terminations.
- **Network Resilience**: Uses exponential backoff and automatic retry logic for transient HTTP errors (429, 500, 502, 503, 504).
- **Google Colab Detection**: Automatically detects Google Colab, mounts Google Drive (`/content/drive`), and saves all metadata files to `/content/drive/MyDrive/Metadata`.

---

## How to Use

### A. Run in Google Colab (Recommended)
Colab has pre-installed packages and high-bandwidth network connectivity, making it the fastest place to run this.

1. Open [fetch_metadata.ipynb](fetch_metadata.ipynb) in Google Colab.
2. Run the cells:
   - **Cell 1**: Installs `requests`.
   - **Cell 2**: Registers the scraper code.
   - **Cell 3**: Runs the scraper. On first run, it will prompt you for authorization to mount your Google Drive.
3. The script will save all outputs (JSON files, SQLite database, progress logs) to the `/Metadata` folder in the root of your Google Drive.

### B. Run Locally
Clone the repository and install the requirements:
```bash
pip install requests
```

Run a test run to fetch 2 pages of manga and anime:
```bash
python fetch_metadata.py --type both --pages 2 --output-manga test_manga.json --output-anime test_anime.json --db metadata.db
```

To run a full database scrape (downloads everything by default):
```bash
python fetch_metadata.py
```

### CLI Command Options
- `--type`: What to fetch. Choices: `manga`, `anime`, `both` (default: `both`)
- `--pages`: Number of pages to fetch per partition (default: `0` [unlimited / fetch all])
- `--delay`: Delay in seconds between requests (default: `0.5` seconds)
- `--db`: SQLite database filename (default: `metadata.db`)
- `--progress-file`: Progress logging JSON (default: `scraping_progress.json`)
- `--output-manga`: Manga JSON filename (default: `manga_metadata.json`)
- `--output-anime`: Anime JSON filename (default: `anime_metadata.json`)

---

## Database Schema (SQLite)

### 1. `manga_metadata`
- `_id` TEXT (Primary Key)
- `name` TEXT, `englishName` TEXT, `nativeName` TEXT
- `thumbnail_url` TEXT
- `thumbnail_blob` **BLOB** (Binary cover image)
- `lastChapterInfo` TEXT (JSON stringified)
- `lastChapterDate` TEXT (JSON stringified)
- `chapterCount` TEXT, `volumes` TEXT, `type` TEXT, `season` TEXT (JSON stringified), `score` REAL, `airedStart` TEXT (JSON stringified), `availableChapters` TEXT (JSON stringified), `lastUpdateEnd` TEXT, `slugTime` TEXT, `countryOfOrigin` TEXT, `characterCount` TEXT, `description` TEXT, `status` TEXT, `altNames` TEXT (JSON stringified array), `authors` TEXT (JSON stringified array), `genres` TEXT (JSON stringified array), `tags` TEXT (JSON stringified array)

### 2. `anime_metadata`
- `_id` TEXT (Primary Key)
- `name` TEXT, `englishName` TEXT, `nativeName` TEXT
- `slugTime` TEXT, `thumbnail_url` TEXT
- `thumbnail_blob` **BLOB** (Binary cover image)
- `lastEpisodeInfo` TEXT (JSON stringified), `lastEpisodeDate` TEXT (JSON stringified)
- `type` TEXT, `season` TEXT (JSON stringified), `score` REAL, `airedStart` TEXT (JSON stringified), `availableEpisodes` TEXT (JSON stringified), `episodeDuration` TEXT, `episodeCount` TEXT, `lastUpdateEnd` TEXT, `characterCount` TEXT, `description` TEXT, `status` TEXT, `genres` TEXT (JSON stringified array), `tags` TEXT (JSON stringified array), `altNames` TEXT (JSON stringified array), `studios` TEXT (JSON stringified array), `countryOfOrigin` TEXT, `rating` TEXT, `averageScore` REAL
