import re
import urllib.parse
from typing import List, Dict, Any, Optional
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def parse_ddg_html_response(html: str) -> List[Dict[str, str]]:
    """
    Parses DuckDuckGo HTML results page to extract snippet, title, and link.
    """
    soup = BeautifulSoup(html, "html.parser")
    results = []
    
    # DDG HTML search structure: .result or .result__body
    for result in soup.find_all("div", class_=re.compile(r"result\b")):
        title_tag = result.find("a", class_="result__snippet") or result.find("a", class_="result__url")
        link_tag = result.find("a", class_="result__url") or result.find("a", href=True)
        snippet_tag = result.find("a", class_="result__snippet") or result.find("div", class_="result__snippet")
        
        # Link resolution
        raw_href = link_tag.get("href", "") if link_tag else ""
        if "uddg=" in raw_href:
            # DuckDuckGo redirect link
            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_href).query)
            clean_url = parsed.get("uddg", [""])[0]
        else:
            clean_url = raw_href
            
        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ""
        title = result.find("h2").get_text(strip=True) if result.find("h2") else ""
        
        if "linkedin.com/in/" in clean_url or "linkedin.com/in/" in raw_href:
            results.append({
                "url": clean_url,
                "title": title,
                "snippet": snippet
            })
            
    return results


def parse_linkedin_title_snippet(title: str, snippet: str, default_role: str = "") -> Dict[str, str]:
    """
    Parses LinkedIn SERP snippet and title to extract Name and Role.
    Typical LinkedIn titles:
    'John Doe - Managing Director - XYZ Logistics | LinkedIn'
    'Jane Smith - Owner - ABC Transports | LinkedIn'
    """
    # Remove " | LinkedIn" or "- LinkedIn"
    cleaned_title = re.sub(r'[\s\-|–]+LinkedIn.*$', '', title, flags=re.IGNORECASE).strip()
    
    name = ""
    role = ""
    
    # Check delimiters in title like " - " or " – " or " | "
    parts = re.split(r'\s+[-–|]\s+', cleaned_title)
    if len(parts) >= 2:
        name = parts[0].strip()
        role = parts[1].strip()
    elif len(parts) == 1:
        name = parts[0].strip()
        
    # If role couldn't be cleanly parsed from title, search snippet
    if not role or role.lower() == "linkedin":
        # Look for common role indicators in snippet
        match = re.search(r'(Owner|Founder|Director|Manager|CEO|COO|Head|Lead|Partner)[^.,;|\n]*', snippet, re.IGNORECASE)
        if match:
            role = match.group(0).strip()
        else:
            role = default_role
            
    return {
        "name": name,
        "role": role
    }


def search_duckduckgo_linkedin(role: str, company: str) -> Optional[Dict[str, str]]:
    """
    Searches DuckDuckGo HTML endpoint without API keys.
    Query: site:linkedin.com/in "[Role]" "[Company]"
    """
    query = f'site:linkedin.com/in "{role}" "{company}"'
    endpoint = "https://html.duckduckgo.com/html/"
    
    try:
        # DDG requires POST on /html/
        resp = requests.post(
            endpoint, 
            data={"q": query, "b": ""}, 
            headers=HEADERS, 
            timeout=10
        )
        if resp.status_code != 200:
            # Fallback to standard GET query
            resp = requests.get(
                endpoint,
                params={"q": query},
                headers=HEADERS,
                timeout=10
            )
            
        if resp.status_code == 200:
            results = parse_ddg_html_response(resp.text)
            if results:
                first = results[0]
                parsed_meta = parse_linkedin_title_snippet(first["title"], first["snippet"], default_role=role)
                return {
                    "linkedin_url": first["url"],
                    "person_name": parsed_meta["name"],
                    "person_role": parsed_meta["role"],
                    "search_snippet": first["snippet"]
                }
    except Exception as e:
        print(f"Error querying DuckDuckGo: {e}")
        
    # Optional fallback using DuckDuckGo lite / instant API
    return None
