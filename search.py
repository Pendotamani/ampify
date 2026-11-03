import re
import urllib.parse
from typing import List, Dict, Any, Optional, Set
from duckduckgo_search import DDGS

# Exclude social media directories and generic directories to ensure real business sites
EXCLUDED_DOMAINS = {
    "duckduckgo.com", "google.com", "bing.com", "yahoo.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "youtube.com", "wikipedia.org",
    "justdial.com", "indiamart.com", "sulekha.com", "quikr.com", "linkedin.com",
    "yellowpages.com", "yelp.com", "mapquest.com", "tripadvisor.com",
    "dictionary.cambridge.org", "merriam-webster.com", "glassdoor.co.in"
}


def search_duckduckgo_websites(keyword: str, city: str, max_results: int = 15) -> List[Dict[str, Any]]:
    """
    Second source: Searches DuckDuckGo for:
    '[keyword] [city] contact email'
    and collects company websites, titles, and snippets.
    """
    query = f"{keyword} {city} contact email"
    results = []
    seen_domains: Set[str] = set()
    
    try:
        ddgs = DDGS()
        raw_items = ddgs.text(query, max_results=max_results * 2)
        
        for item in raw_items:
            clean_url = item.get("href", "")
            if not clean_url or not clean_url.startswith("http"):
                continue
                
            domain = urllib.parse.urlparse(clean_url).netloc.lower()
            domain_clean = re.sub(r'^www\.', '', domain)
            
            if any(excluded in domain_clean for excluded in EXCLUDED_DOMAINS):
                continue
                
            if domain_clean in seen_domains:
                continue
            seen_domains.add(domain_clean)
            
            title = item.get("title", domain_clean)
            snippet = item.get("body", "")
            
            # Derive reasonable company name
            company_name = re.split(r'[:|\-–]|Contact|About|Home', title)[0].strip()
            if not company_name or len(company_name) < 3:
                company_name = domain_clean.split('.')[0].capitalize()
                
            # Check snippet for inline emails
            snippet_emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', snippet)
            
            results.append({
                "name": company_name,
                "website": clean_url,
                "city": city,
                "type": keyword,
                "address": f"{city}, India",
                "phone": "",
                "snippet": snippet,
                "initial_email": snippet_emails[0] if snippet_emails else "",
                "source": "DuckDuckGo Web Search"
            })
            
            if len(results) >= max_results:
                break
    except Exception as e:
        print(f"Error querying DuckDuckGo websites: {e}")
        
    return results


def parse_linkedin_title_snippet(title: str, snippet: str, default_role: str = "") -> Dict[str, str]:
    """
    Parses LinkedIn SERP snippet and title to extract person name and role.
    Example titles:
    'John Doe - Managing Director - XYZ Logistics | LinkedIn'
    """
    cleaned_title = re.sub(r'[\s\-|–]+LinkedIn.*$', '', title, flags=re.IGNORECASE).strip()
    name = ""
    role = ""
    
    parts = re.split(r'\s+[-–|]\s+', cleaned_title)
    if len(parts) >= 2:
        name = parts[0].strip()
        role = parts[1].strip()
    elif len(parts) == 1:
        name = parts[0].strip()
        
    if not role or role.lower() == "linkedin":
        match = re.search(r'(Owner|Founder|Director|Manager|CEO|COO|Head|Lead|Partner|President)[^.,;|\n]*', snippet, re.IGNORECASE)
        if match:
            role = match.group(0).strip()
        else:
            role = default_role
            
    return {"name": name, "role": role}


def search_duckduckgo_linkedin(role: str, company: str) -> Optional[Dict[str, str]]:
    """
    Searches DuckDuckGo for: site:linkedin.com/in "[Role]" "[Company]"
    Extracts profile URL, person name, and role from snippet.
    """
    query = f'site:linkedin.com/in "{role}" "{company}"'
    
    try:
        ddgs = DDGS()
        items = ddgs.text(query, max_results=5)
        for item in items:
            href = item.get("href", "")
            if "linkedin.com/in/" in href:
                title = item.get("title", "")
                snippet = item.get("body", "")
                meta = parse_linkedin_title_snippet(title, snippet, default_role=role)
                return {
                    "linkedin_url": href,
                    "person_name": meta["name"],
                    "person_role": meta["role"],
                    "search_snippet": snippet
                }
    except Exception as e:
        print(f"Error querying DuckDuckGo LinkedIn for {company}: {e}")
        
    return None
