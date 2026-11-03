import re
import urllib.parse
from typing import List, Dict, Any, Optional, Set
from duckduckgo_search import DDGS

# Excluded domains to filter out aggregators and directory listings
EXCLUDED_DOMAINS = {
    "duckduckgo.com", "google.com", "bing.com", "yahoo.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "youtube.com", "wikipedia.org",
    "justdial.com", "indiamart.com", "sulekha.com", "quikr.com", "linkedin.com",
    "yellowpages.com", "yelp.com", "mapquest.com", "tripadvisor.com",
    "glassdoor.co.in", "naukri.com", "indeed.com"
}


def search_duckduckgo_websites(keyword: str, city: str, max_results: int = 15) -> List[Dict[str, Any]]:
    """
    Finds active company websites using DuckDuckGo public search.
    Queries both specific and broad commercial patterns.
    """
    clean_kw = keyword.strip()
    queries = [
        f"{clean_kw} {city} contact email",
        f"top {clean_kw} companies in {city}",
        f"{clean_kw} services {city}"
    ]
    
    results = []
    seen_domains: Set[str] = set()
    
    try:
        ddgs = DDGS()
        for q in queries:
            try:
                items = ddgs.text(q, max_results=max_results)
                for item in items:
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
                    
                    # Clean company name
                    name_candidate = re.split(r'[:|\-–]|Contact|About|Home|Services', title)[0].strip()
                    if not name_candidate or len(name_candidate) < 3:
                        name_candidate = domain_clean.split('.')[0].capitalize()
                        
                    snippet_emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', snippet)
                    
                    results.append({
                        "name": name_candidate,
                        "website": clean_url,
                        "city": city,
                        "type": keyword,
                        "address": f"{city}, India",
                        "phone": "",
                        "snippet": snippet,
                        "initial_email": snippet_emails[0] if snippet_emails else "",
                        "source": "DuckDuckGo Public Search"
                    })
                    
                    if len(results) >= max_results:
                        return results
            except Exception:
                continue
    except Exception as e:
        print(f"Error querying DuckDuckGo: {e}")
        
    return results


def parse_linkedin_title_snippet(title: str, snippet: str, default_role: str = "") -> Dict[str, str]:
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
    Searches DuckDuckGo for LinkedIn profile snippet without logging in.
    """
    query = f'site:linkedin.com/in "{role}" "{company}"'
    
    try:
        ddgs = DDGS()
        items = ddgs.text(query, max_results=4)
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
        pass
        
    return None
