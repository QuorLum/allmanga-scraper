import os
import re
import json
import time
import shutil
import argparse
import sqlite3
import requests

API_URL = "https://api.allanime.day/api"

# GraphQL query for Manga list
MANGA_QUERY = """
query(
  $search: SearchInput
  $limit: Int
  $page: Int
  $translationType: VaildTranslationTypeMangaEnumType
  $countryOrigin: VaildCountryOriginEnumType
) {
  mangas(
    search: $search
    limit: $limit
    page: $page
    translationType: $translationType
    countryOrigin: $countryOrigin
  ) {
    pageInfo {
      total
    }
    edges {
      _id
      name
      englishName
      nativeName
      thumbnail
      lastChapterInfo
      lastChapterDate
      chapterCount
      volumes
      type
      season
      score
      airedStart
      availableChapters
      lastUpdateEnd
      slugTime
      countryOfOrigin
      characterCount
      description
      status
      altNames
      authors
      genres
      tags
    }
  }
}
"""

# GraphQL query for Anime (shows) list
ANIME_QUERY = """
query(
  $search: SearchInput
  $limit: Int
  $page: Int
  $translationType: VaildTranslationTypeEnumType
  $countryOrigin: VaildCountryOriginEnumType
) {
  shows(
    search: $search
    limit: $limit
    page: $page
    translationType: $translationType
    countryOrigin: $countryOrigin
  ) {
    pageInfo {
      total
    }
    edges {
      _id
      name
      englishName
      nativeName
      slugTime
      thumbnail
      lastEpisodeInfo
      lastEpisodeDate
      type
      season
      score
      airedStart
      availableEpisodes
      episodeDuration
      episodeCount
      lastUpdateEnd
      characterCount
      description
      status
      genres
      tags
      altNames
      studios
      countryOfOrigin
      rating
      averageScore
    }
  }
}
"""

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Origin": "https://allmanga.to",
    "Referer": "https://allmanga.to/",
    "Content-Type": "application/json"
}

# Detect if running in Google Colab environment
try:
    import google.colab
    IN_COLAB = True
except ImportError:
    IN_COLAB = False

if IN_COLAB:
    from google.colab import drive
    print("Google Colab detected. Mounting Google Drive...")
    drive.mount('/content/drive')
    BASE_DIR = "/content/drive/MyDrive/Metadata"
    # Local paths on Colab local VM SSD to prevent SQLite/FUSE filesystem corruption
    LOCAL_DB_PATH = "/content/metadata.db"
    LOCAL_THUMBNAILS_DIR = "/content/Thumbnails"
else:
    BASE_DIR = "."
    LOCAL_DB_PATH = None
    LOCAL_THUMBNAILS_DIR = None

# Ensure base directory and backup folders exist on Drive/Local
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "Thumbnails"), exist_ok=True)

if LOCAL_THUMBNAILS_DIR:
    os.makedirs(LOCAL_THUMBNAILS_DIR, exist_ok=True)

def load_existing_data(file_path):
    """Loads existing JSON metadata list."""
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    print(f"Loaded {len(data)} existing items from {file_path}.")
                    return data
        except Exception as e:
            print(f"Warning: Could not parse existing JSON in {file_path} ({e}). Starting fresh.")
    return []

def save_data_atomic(file_path, data):
    """Saves data to a temporary file and renames it to prevent file corruption."""
    temp_path = file_path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        if os.path.exists(file_path):
            os.remove(file_path)
        os.rename(temp_path, file_path)
    except Exception as e:
        print(f"Error saving data to {file_path}: {e}")
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

def load_progress(progress_file_path):
    """Loads incremental partition progress log."""
    if os.path.exists(progress_file_path):
        try:
            with open(progress_file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not parse progress log ({e}). Starting fresh.")
    return {
        "manga": {"current_year": 1940, "current_country": "JP", "current_page": 0},
        "anime": {"current_year": 1940, "current_country": "JP", "current_page": 0}
    }

def save_progress(progress_file_path, progress_data):
    """Saves incremental partition progress log."""
    try:
        with open(progress_file_path, "w", encoding="utf-8") as f:
            json.dump(progress_data, f, indent=2)
    except Exception as e:
        print(f"Error saving progress log to {progress_file_path}: {e}")

def load_processed_ids_from_db(db_path, table_name):
    """Retrieves processed IDs from the SQLite database to avoid duplicates."""
    processed = set()
    if os.path.exists(db_path):
        conn = None
        try:
            conn = sqlite3.connect(db_path, timeout=30.0)
            cursor = conn.cursor()
            # check if table exists
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' and name='{table_name}'")
            if cursor.fetchone():
                cursor.execute(f"SELECT _id FROM {table_name}")
                rows = cursor.fetchall()
                for row in rows:
                    processed.add(row[0])
        except Exception as e:
            print(f"Warning: Could not read processed IDs from SQLite {table_name}: {e}")
        finally:
            if conn:
                conn.close()
    return processed

def init_sqlite_db(db_path):
    """Creates the SQLite database and necessary tables if they do not exist."""
    print(f"Initializing SQLite database at {db_path}...")
    conn = None
    try:
        conn = sqlite3.connect(db_path, timeout=30.0)
        cursor = conn.cursor()
        
        # Manga Table (including BLOB for thumbnails)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS manga_metadata (
            _id TEXT PRIMARY KEY,
            name TEXT,
            englishName TEXT,
            nativeName TEXT,
            thumbnail_url TEXT,
            thumbnail_blob BLOB,
            lastChapterInfo TEXT,
            lastChapterDate TEXT,
            chapterCount TEXT,
            volumes TEXT,
            type TEXT,
            season TEXT,
            score REAL,
            airedStart TEXT,
            availableChapters TEXT,
            lastUpdateEnd TEXT,
            slugTime TEXT,
            countryOfOrigin TEXT,
            characterCount TEXT,
            description TEXT,
            status TEXT,
            altNames TEXT,
            authors TEXT,
            genres TEXT,
            tags TEXT
        )
        """)
        
        # Anime Table (including BLOB for thumbnails)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS anime_metadata (
            _id TEXT PRIMARY KEY,
            name TEXT,
            englishName TEXT,
            nativeName TEXT,
            slugTime TEXT,
            thumbnail_url TEXT,
            thumbnail_blob BLOB,
            lastEpisodeInfo TEXT,
            lastEpisodeDate TEXT,
            type TEXT,
            season TEXT,
            score REAL,
            airedStart TEXT,
            availableEpisodes TEXT,
            episodeDuration TEXT,
            episodeCount TEXT,
            lastUpdateEnd TEXT,
            characterCount TEXT,
            description TEXT,
            status TEXT,
            genres TEXT,
            tags TEXT,
            altNames TEXT,
            studios TEXT,
            countryOfOrigin TEXT,
            rating TEXT,
            averageScore REAL
        )
        """)
        
        conn.commit()
    except Exception as e:
        print(f"Error initializing SQLite database: {e}")
    finally:
        if conn:
            conn.close()

def download_thumbnail(thumbnail_url):
    """Downloads the thumbnail image binary content from the cover server CDN."""
    if not thumbnail_url:
        return None
    
    url = thumbnail_url
    # Resolve relative URL against cover CDN server verified domain
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://aln.youtube-anime.com/" + url.lstrip("/")
        
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code == 200:
            return response.content
    except Exception as e:
        print(f"  Warning: Failed to download thumbnail from {url} ({e})")
    return None

def fetch_page(query, variables, retries=5, backoff=2):
    """Fetches a single page of data with retries and exponential backoff."""
    for attempt in range(retries):
        try:
            response = requests.post(
                API_URL,
                json={"query": query, "variables": variables},
                headers=HEADERS,
                timeout=15
            )
            if response.status_code == 200:
                result = response.json()
                if "errors" in result:
                    print(f"GraphQL Errors: {result['errors']}")
                    return None
                return result.get("data", {})
            elif response.status_code in [429, 500, 502, 503, 504]:
                sleep_time = backoff ** attempt
                print(f"Temporary server error ({response.status_code}). Retrying in {sleep_time}s...")
                time.sleep(sleep_time)
            else:
                print(f"HTTP Error {response.status_code}: {response.text}")
                return None
        except Exception as e:
            sleep_time = backoff ** attempt
            print(f"Request failed: {e}. Retrying in {sleep_time}s...")
            time.sleep(sleep_time)
    print("Max retries exceeded.")
    return None

def sync_to_drive(local_db_path, drive_db_path, local_thumb_dir, drive_thumb_dir):
    """Synchronizes updated database and local image backups to Google Drive mount."""
    try:
        # 1. Sync database file
        if local_db_path and os.path.exists(local_db_path):
            shutil.copy2(local_db_path, drive_db_path)
            
        # 2. Sync newly downloaded thumbnail files
        if local_thumb_dir and os.path.exists(local_thumb_dir):
            for file_name in os.listdir(local_thumb_dir):
                src_file = os.path.join(local_thumb_dir, file_name)
                dst_file = os.path.join(drive_thumb_dir, file_name)
                # Only copy if file doesn't exist on Google Drive or size is different
                if not os.path.exists(dst_file) or os.path.getsize(src_file) != os.path.getsize(dst_file):
                    shutil.copy2(src_file, dst_file)
                    
        # 3. Force FUSE flush
        if hasattr(os, "sync"):
            os.sync()
    except Exception as e:
        print(f"Warning: Synchronization to Google Drive failed: {e}")

def scrape_metadata(target_type, output_file, db_path, progress_file, max_pages, delay):
    """Orchestrates the scraping process, partitioning by year and countryOrigin to bypass page capping."""
    print(f"\n--- Starting Partitioned Scrape for {target_type.upper()} ---")
    print(f"JSON Output file: {output_file}")
    
    # Determine the execution paths (local SSD if in Colab to prevent corruption)
    current_db = LOCAL_DB_PATH if IN_COLAB else db_path
    current_thumbnails_dir = LOCAL_THUMBNAILS_DIR if IN_COLAB else os.path.join(BASE_DIR, "Thumbnails")
    drive_thumbnails_dir = os.path.join(BASE_DIR, "Thumbnails")
    
    # 1. Load existing JSON items and DB processed IDs
    items = load_existing_data(output_file)
    json_ids = {item["_id"] for item in items if "_id" in item}
    
    table_name = "manga_metadata" if target_type == "manga" else "anime_metadata"
    db_ids = load_processed_ids_from_db(current_db, table_name)
    
    fetched_ids = json_ids.union(db_ids)
    print(f"Total processed records loaded: {len(fetched_ids)}")
    
    # 2. Determine partition resume state
    progress = load_progress(progress_file)
    
    # Load progress parameters safely, with defaults pointing to year 1940
    start_year = progress.get(target_type, {}).get("current_year", 1940)
    start_country = progress.get(target_type, {}).get("current_country", "JP")
    start_page = progress.get(target_type, {}).get("current_page", 1)
    
    print(f"Resuming partition: Year {start_year}, Country {start_country}, Page {start_page}.")
    
    # Define query-specific settings
    if target_type == "manga":
        query = MANGA_QUERY
        translation_type = "sub"
        data_key = "mangas"
    else:
        query = ANIME_QUERY
        translation_type = "sub"
        data_key = "shows"

    # Define partition dimensions
    years = list(range(1940, 2027))
    countries = ["JP", "CN", "KR", "OTHER"]
    
    pages_processed = 0
    
    for year in years:
        if year < start_year:
            continue
            
        for country in countries:
            # If we are in the resuming year, skip countries that were completed
            if year == start_year:
                if countries.index(country) < countries.index(start_country):
                    continue
            
            # Determine start page for this partition
            if year == start_year and country == start_country:
                page = start_page
            else:
                page = 1
                
            print(f"\n>>> Scrape Partition: Year {year} | Country {country} | Starting at Page {page} <<<")
            all_partition_ids = set()
            
            while True:
                if max_pages and pages_processed >= max_pages:
                    print(f"Reached specified page limit ({max_pages} pages). Stopping.")
                    return
                
                # Capped at page 100 (2,000 items) by AllManga API
                if page > 100:
                    print("Reached API page limit (Page 100) for this partition. Moving to next partition.")
                    break
                    
                variables = {
                    "search": {
                        "allowAdult": True,
                        "allowUnknown": True,
                        "year": year
                    },
                    "limit": 20,
                    "page": page,
                    "translationType": translation_type,
                    "countryOrigin": country
                }
                
                print(f"Fetching Year {year} | Country {country} | Page {page}...")
                data = fetch_page(query, variables)
                
                if not data:
                    print("Failed to fetch page data. Stopping execution to preserve state.")
                    return
                    
                result_set = data.get(data_key, {})
                if not result_set:
                    print(f"No data set key '{data_key}' found in response. Finishing partition.")
                    break
                    
                edges = result_set.get("edges", [])
                if not edges:
                    print("No more records returned for this partition. Moving to next.")
                    break
                
                # Check for wrap-around duplication
                page_ids = [edge["_id"] for edge in edges if edge]
                new_partition_ids = [pid for pid in page_ids if pid not in all_partition_ids]
                if len(new_partition_ids) == 0 and len(page_ids) > 0:
                    print("API wrapped around to page 1 results. Finished this partition.")
                    break
                
                all_partition_ids.update(page_ids)
                
                # Write page-by-page results to SQLite
                conn = sqlite3.connect(current_db, timeout=30.0)
                try:
                    cursor = conn.cursor()
                    new_items_count = 0
                    for edge in edges:
                        if not edge:
                            continue
                        _id = edge.get("_id")
                        if _id not in fetched_ids:
                            # 1. Download cover image
                            thumbnail_url = edge.get("thumbnail")
                            print(f"Downloading cover thumbnail for: {edge.get('name') or _id}...")
                            thumbnail_blob = download_thumbnail(thumbnail_url)
                            
                            # 2. Store image to separate folder as standalone backup
                            if thumbnail_blob and current_thumbnails_dir:
                                # Extract extension from URL, default to jpg
                                ext = "jpg"
                                if thumbnail_url:
                                    ext_match = re.search(r'\.(webp|png|jpg|jpeg|gif)\b', thumbnail_url, re.IGNORECASE)
                                    if ext_match:
                                        ext = ext_match.group(1).lower()
                                img_path = os.path.join(current_thumbnails_dir, f"{_id}.{ext}")
                                try:
                                    with open(img_path, "wb") as img_file:
                                        img_file.write(thumbnail_blob)
                                except Exception as e:
                                    print(f"  Warning: Failed to save thumbnail file to disk: {e}")
                            
                            # 3. Insert metadata and BLOB into SQLite
                            if target_type == "manga":
                                cursor.execute("""
                                INSERT OR REPLACE INTO manga_metadata (
                                    _id, name, englishName, nativeName, thumbnail_url, thumbnail_blob,
                                    lastChapterInfo, lastChapterDate, chapterCount, volumes, type, season,
                                    score, airedStart, availableChapters, lastUpdateEnd, slugTime,
                                    countryOfOrigin, characterCount, description, status, altNames,
                                    authors, genres, tags
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    _id,
                                    edge.get("name"),
                                    edge.get("englishName"),
                                    edge.get("nativeName"),
                                    thumbnail_url,
                                    sqlite3.Binary(thumbnail_blob) if thumbnail_blob else None,
                                    json.dumps(edge.get("lastChapterInfo")),
                                    json.dumps(edge.get("lastChapterDate")),
                                    edge.get("chapterCount"),
                                    edge.get("volumes"),
                                    edge.get("type"),
                                    json.dumps(edge.get("season")),
                                    edge.get("score"),
                                    json.dumps(edge.get("airedStart")),
                                    json.dumps(edge.get("availableChapters")),
                                    edge.get("lastUpdateEnd"),
                                    edge.get("slugTime"),
                                    edge.get("countryOfOrigin"),
                                    edge.get("characterCount"),
                                    edge.get("description"),
                                    edge.get("status"),
                                    json.dumps(edge.get("altNames")),
                                    json.dumps(edge.get("authors")),
                                    json.dumps(edge.get("genres")),
                                    json.dumps(edge.get("tags"))
                                ))
                            else:
                                cursor.execute("""
                                INSERT OR REPLACE INTO anime_metadata (
                                    _id, name, englishName, nativeName, slugTime, thumbnail_url, thumbnail_blob,
                                    lastEpisodeInfo, lastEpisodeDate, type, season, score, airedStart,
                                    availableEpisodes, episodeDuration, episodeCount, lastUpdateEnd,
                                    characterCount, description, status, genres, tags, altNames,
                                    studios, countryOfOrigin, rating, averageScore
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    _id,
                                    edge.get("name"),
                                    edge.get("englishName"),
                                    edge.get("nativeName"),
                                    edge.get("slugTime"),
                                    thumbnail_url,
                                    sqlite3.Binary(thumbnail_blob) if thumbnail_blob else None,
                                    json.dumps(edge.get("lastEpisodeInfo")),
                                    json.dumps(edge.get("lastEpisodeDate")),
                                    edge.get("type"),
                                    json.dumps(edge.get("season")),
                                    edge.get("score"),
                                    json.dumps(edge.get("airedStart")),
                                    json.dumps(edge.get("availableEpisodes")),
                                    edge.get("episodeDuration"),
                                    edge.get("episodeCount"),
                                    edge.get("lastUpdateEnd"),
                                    edge.get("characterCount"),
                                    edge.get("description"),
                                    edge.get("status"),
                                    json.dumps(edge.get("genres")),
                                    json.dumps(edge.get("tags")),
                                    json.dumps(edge.get("altNames")),
                                    json.dumps(edge.get("studios")),
                                    edge.get("countryOfOrigin"),
                                    edge.get("rating"),
                                    edge.get("averageScore")
                                ))
                            
                            items.append(edge)
                            fetched_ids.add(_id)
                            new_items_count += 1
                    conn.commit()
                finally:
                    conn.close()
                
                print(f"Page {page} processed. Added {new_items_count} new records. Total saved items: {len(items)}")
                
                # Save JSON file atomically
                save_data_atomic(output_file, items)
                
                # Update progress log
                progress[target_type] = {
                    "current_year": year,
                    "current_country": country,
                    "current_page": page,
                    "processed_count": len(items)
                }
                save_progress(progress_file, progress)
                
                # Sync local changes to Google Drive mount if in Colab
                if IN_COLAB:
                    print("Syncing files to Google Drive...")
                    sync_to_drive(LOCAL_DB_PATH, db_path, LOCAL_THUMBNAILS_DIR, drive_thumbnails_dir)
                    print("Sync complete.")
                
                pages_processed += 1
                page += 1
                
                if delay > 0:
                    time.sleep(delay)
                    
            # Reset page to 1 for completed country partitions
            progress[target_type] = {
                "current_year": year,
                "current_country": country,
                "current_page": 1,
                "processed_count": len(items)
            }
            save_progress(progress_file, progress)

    print(f"Finished fetching {target_type.upper()}. Total saved: {len(items)} items.")

def main():
    parser = argparse.ArgumentParser(description="AllManga.to Manga and Anime Metadata Scraper (Colab & Google Drive Support)")
    parser.add_argument(
        "--type", 
        type=str, 
        choices=["manga", "anime", "both"], 
        default="both",
        help="Type of metadata to fetch (manga, anime, or both)"
    )
    parser.add_argument(
        "--pages", 
        type=int, 
        default=0, 
        help="Number of pages to fetch (0 for all pages)"
    )
    parser.add_argument(
        "--delay", 
        type=float, 
        default=0.5, 
        help="Delay in seconds between requests"
    )
    parser.add_argument(
        "--output-manga", 
        type=str, 
        default="manga_metadata.json", 
        help="Output file name for manga JSON metadata"
    )
    parser.add_argument(
        "--output-anime", 
        type=str, 
        default="anime_metadata.json", 
        help="Output file name for anime JSON metadata"
    )
    parser.add_argument(
        "--db", 
        type=str, 
        default="metadata.db", 
        help="SQLite database filename"
    )
    parser.add_argument(
        "--progress-file", 
        type=str, 
        default="scraping_progress.json", 
        help="Filename for scraping progress logs"
    )
    
    args, unknown = parser.parse_known_args()
    
    # Resolve all files against the BASE_DIR (points to Drive in Colab, or local folder)
    output_manga_path = os.path.join(BASE_DIR, args.output_manga)
    output_anime_path = os.path.join(BASE_DIR, args.output_anime)
    db_path = os.path.join(BASE_DIR, args.db)
    progress_path = os.path.join(BASE_DIR, args.progress_file)
    
    print(f"Working Directory resolved: {BASE_DIR}")
    
    # Initialize SQLite database schema
    # If Colab, initialize local database first
    current_db = LOCAL_DB_PATH if IN_COLAB else db_path
    init_sqlite_db(current_db)
    
    if args.type in ["manga", "both"]:
        scrape_metadata("manga", output_manga_path, db_path, progress_path, args.pages, args.delay)
        
    if args.type in ["anime", "both"]:
        scrape_metadata("anime", output_anime_path, db_path, progress_path, args.pages, args.delay)

if __name__ == "__main__":
    main()
