import re
import urllib.parse
from typing import List, Dict, Any, Optional, Tuple, Set
from ddgs import DDGS
import requests

# Blocked domains including e-commerce, aggregators, search, and social media
BLOCKED_DOMAINS = {
    "microsoft.com", "youtube.com", "zhihu.com", "baidu.com", "wikipedia.org",
    "flipkart.com", "facebook.com", "instagram.com", "pinterest.com", "quora.com",
    "reddit.com", "medium.com", "linkedin.com", "justdial.com", "indiamart.com",
    "sulekha.com", "quikr.com", "yellowpages.com", "yelp.com", "mapquest.com",
    "tripadvisor.com", "glassdoor.com", "glassdoor.co.in", "naukri.com", "indeed.com",
    "google.com", "duckduckgo.com", "bing.com", "yahoo.com"
}

# Synonyms for business categories
KEYWORD_SYNONYMS = {
    "transport": ["transport", "logistics", "cargo", "cabs", "travels", "fleet", "movers", "packers", "carriers", "transit"],
    "fleet owner": ["fleet", "transport", "logistics", "trucks", "cabs", "vehicles", "commercial vehicles", "transporters"],
    "logistics": ["logistics", "supply chain", "freight", "cargo", "warehousing", "transport", "shipping"],
    "travel agencies": ["travels", "tours", "tourist", "cabs", "holidays", "travel agency", "packages", "trips"],
    "restaurants": ["restaurant", "dining", "food", "cafe", "kitchen", "eatery", "bistro", "bar & restaurant"],
    "real estate": ["real estate", "realty", "properties", "builders", "developers", "estates", "apartments", "housing"],
    "it": ["software", "tech", "technology", "it services", "solutions", "cloud", "digital", "systems"],
    "hotels": ["hotel", "resort", "inn", "suites", "stay", "guest house", "hospitality"],
    "clinics": ["clinic", "hospital", "health", "care", "medical", "dentist", "doctor", "specialist"],
    "retail": ["store", "mart", "retail", "supermarket", "fashion", "shop", "outlet"],
    "marketing agency": ["marketing", "advertising", "seo", "branding", "digital agency", "media"]
}

ARTICLE_PATTERNS = [
    r'\btop\s*\d+\b', r'\bbest\b', r'\bhow\s+to\b', r'\blist\s+of\b',
    r'\b10\s+best\b', r'\b5\s+best\b', r'\b20\s+best\b', r'\bblog\b',
    r'\bdirectory\b', r'\breviews\b', r'\bwiki\b'
]


def is_latin_or_english(text: str) -> bool:
    """Checks if text contains predominantly Latin/English characters."""
    if not text:
        return True
    # Strip common punctuation and numbers
    letters_only = re.sub(r'[\s\d\W]', '', text)
    if not letters_only:
        return True
    # Check ASCII / Latin letters
    latin_count = sum(1 for c in letters_only if '\u0000' <= c <= '\u024F')
    return (latin_count / len(letters_only)) >= 0.75


def get_root_domain(url: str) -> str:
    """Extracts company root domain (e.g. 'https://sub.domain.com/path' -> 'domain.com')."""
    try:
        netloc = urllib.parse.urlparse(url).netloc.lower()
        netloc = re.sub(r'^www\.', '', netloc)
        parts = netloc.split('.')
        if len(parts) >= 2:
            # Handle co.in, com.au, co.uk
            if len(parts) >= 3 and parts[-2] in ('co', 'com', 'org', 'gov', 'net') and len(parts[-1]) == 2:
                return ".".join(parts[-3:])
            return ".".join(parts[-2:])
        return netloc
    except Exception:
        return ""


def is_blocked_domain(domain: str) -> bool:
    """Checks if domain matches blocked list or amazon.*."""
    clean = domain.lower()
    if "amazon." in clean:
        return True
    for blocked in BLOCKED_DOMAINS:
        if blocked in clean:
            return True
    return False


def is_junk_result(title: str, snippet: str, url: str, business_type: str, city: str) -> bool:
    """
    1. Junk filter (before crawling):
    - Block domains
    - Skip non-Latin/English
    - Skip 'top 10', 'best', 'how to', 'list of'
    - Require business keyword (or synonym) AND city in title or snippet
    """
    root_domain = get_root_domain(url)
    if not root_domain or is_blocked_domain(root_domain):
        return True
        
    combined_text = f"{title} {snippet}".lower()
    
    # Check Latin script
    if not is_latin_or_english(title) or not is_latin_or_english(snippet):
        return True
        
    # Check for list or article patterns
    for pat in ARTICLE_PATTERNS:
        if re.search(pat, title, re.IGNORECASE):
            return True
            
    # Check city name
    city_lower = city.lower().strip()
    if city_lower not in combined_text and city_lower not in url.lower():
        return True
        
    # Check business keyword or synonyms
    bt_lower = business_type.lower().strip()
    synonyms = [bt_lower]
    for key, syn_list in KEYWORD_SYNONYMS.items():
        if key in bt_lower or bt_lower in key:
            synonyms.extend(syn_list)
            
    matched_keyword = any(syn in combined_text for syn in synonyms)
    if not matched_keyword:
        return True
        
    return False


def search_web_companies(
    business_type: str,
    city: str,
    country: str,
    max_results: int = 15,
    brave_api_key: str = "",
    serper_api_key: str = ""
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Source 2 web search: Queries '[business type] in [city] [country] contact'.
    Applies junk filter, root domain extraction, and domain deduplication.
    """
    query = f"{business_type} in {city} {country} contact"
    debug = {
        "query": query,
        "engine_used": "ddgs",
        "status": None,
        "error": None,
        "response_sample": "",
        "fallback_triggered": False
    }
    
    results = []
    seen_root_domains: Set[str] = set()
    
    try:
        ddgs_client = DDGS(timeout=10)
        raw_items = list(ddgs_client.text(query, max_results=max_results * 4))
        debug["status"] = 200
        debug["response_sample"] = str(raw_items[:2])[:200]
        
        for item in raw_items:
            url = item.get("href", "")
            title = item.get("title", "")
            snippet = item.get("body", "")
            
            if not url or not url.startswith("http"):
                continue
                
            # Junk filter
            if is_junk_result(title, snippet, url, business_type, city):
                continue
                
            root_dom = get_root_domain(url)
            if not root_dom or root_dom in seen_root_domains:
                continue
            seen_root_domains.add(root_dom)
            
            # Clean company name
            name = re.split(r'[:|\-–]|Contact|About|Home|Services', title)[0].strip()
            if not name or len(name) < 3:
                name = root_dom.split('.')[0].capitalize()
                
            # Extract emails and phones from snippet if present
            snippet_emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', snippet)
            snippet_phones = re.findall(r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5}', snippet)
            
            clean_phones = [p.strip() for p in snippet_phones if 8 <= len(re.sub(r'\D', '', p)) <= 15]
            
            results.append({
                "name": name,
                "website": f"https://{root_dom}",
                "city": city,
                "country": country,
                "business_type": business_type,
                "address": f"{city}, {country}",
                "phone": clean_phones[0] if clean_phones else "",
                "snippet": snippet,
                "initial_email": snippet_emails[0].lower() if snippet_emails else "",
                "source": "Web Search (ddgs)"
            })
            
            if len(results) >= max_results:
                break
                
        if results:
            return results, debug
    except Exception as e:
        debug["error"] = str(e)
        
    return results, debug


def parse_linkedin_snippet(title: str, snippet: str, default_role: str = "") -> Dict[str, str]:
    cleaned = re.sub(r'[\s\-|–]+LinkedIn.*$', '', title, flags=re.IGNORECASE).strip()
    parts = re.split(r'\s+[-–|]\s+', cleaned)
    name = parts[0].strip() if parts else ""
    role = parts[1].strip() if len(parts) >= 2 else ""
    
    if not role or role.lower() == "linkedin":
        match = re.search(r'(CEO|Founder|Director|Owner|Manager|Head|Lead|Partner|President)[^.,;|\n]*', snippet, re.IGNORECASE)
        role = match.group(0).strip() if match else default_role
        
    return {"name": name, "role": role}


def search_decision_maker_linkedin(
    role: str,
    company: str,
    city: str
) -> Tuple[Optional[Dict[str, str]], Dict[str, Any]]:
    query = f'{role} {company} {city} site:linkedin.com/in'
    debug = {"query": query, "status": None, "error": None, "response_sample": ""}
    
    try:
        client = DDGS(timeout=8)
        items = list(client.text(query, max_results=3))
        debug["status"] = 200
        debug["response_sample"] = str(items[:1])[:200]
        
        for item in items:
            href = item.get("href", "")
            if "linkedin.com/in/" in href:
                title = item.get("title", "")
                snippet = item.get("body", "")
                parsed = parse_linkedin_snippet(title, snippet, default_role=role)
                return {
                    "person_name": parsed["name"],
                    "person_role": parsed["role"],
                    "linkedin_url": href,
                    "snippet": snippet
                }, debug
    except Exception as e:
        debug["error"] = str(e)
        
    return None, debug
