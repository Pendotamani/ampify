# Local Business Lead Finder Agent

A modular, free-tier Python lead generation application built with Streamlit, OpenStreetMap (Overpass API), Requests/BeautifulSoup, and DuckDuckGo SERP scraping.

## Features
- **No Paid APIs Required**: Completely free data sourcing.
- **OpenStreetMap Overpass API**: Discovers local businesses based on target city and category.
- **Polite Website Scraping**: Crawls homepages and Contact/About links with configurable delays, extracts emails and phone numbers, and adheres to `robots.txt`.
- **DuckDuckGo LinkedIn SERP Search**: Finds decision-makers (`site:linkedin.com/in "[Role]" "[Company]"`) without logging into or scraping LinkedIn directly.
- **Deduplication**: Automatically filters out duplicate records.
- **CSV Export & Google Sheets**: View interactive data tables, download results as CSV, and trigger the `push_to_google_sheet()` placeholder.

## Project Structure
- [`finder.py`](file:///C:/Users/shank/.gemini/antigravity/scratch/lead-finder-agent/finder.py): Handles Overpass QL queries and parses OSM responses.
- [`website_scraper.py`](file:///C:/Users/shank/.gemini/antigravity/scratch/lead-finder-agent/website_scraper.py): Implements polite crawling, `robots.txt` checks, contact page detection, email & phone extraction.
- [`search.py`](file:///C:/Users/shank/.gemini/antigravity/scratch/lead-finder-agent/search.py): Queries DuckDuckGo HTML endpoint and parses LinkedIn profile snippets.
- [`app.py`](file:///C:/Users/shank/.gemini/antigravity/scratch/lead-finder-agent/app.py): Streamlit web interface with filters, progress tracking, deduplication, CSV export, and Google Sheets placeholder.
- [`requirements.txt`](file:///C:/Users/shank/.gemini/antigravity/scratch/lead-finder-agent/requirements.txt): Python dependencies.

## How to Run

1. Open a terminal in this directory:
   ```bash
   cd C:\Users\shank\.gemini\antigravity\scratch\lead-finder-agent
   ```
2. Start the Streamlit app:
   ```bash
   streamlit run app.py
   ```
