import time
import re
import urllib.parse
from typing import List, Dict, Any, Optional, Tuple, Set
from ddgs import DDGS
import requests

EXCLUDED_DOMAINS = {
    "duckduckgo.com", "google.com", "bing.com", "yahoo.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "youtube.com", "wikipedia.org",
    "justdial.com", "indiamart.com", "sulekha.com", "quikr.com", "linkedin.com",
    "yellowpages.com", "yelp.com", "mapquest.com", "tripadvisor.com",
    "glassdoor.co.in", "glassdoor.com", "naukri.com", "indeed.com"
}


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
    Uses ddgs package, with retries on rate limits, and falls back to Brave Search or Serper if keys are provided.
    Returns (results, debug_info).
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
    seen_domains: Set[str] = set()
    
    # 1. Primary: ddgs package with retry
    for attempt in range(2):
        try:
            ddgs_client = DDGS(timeout=10)
            raw_items = list(ddgs_client.text(query, max_results=max_results * 2))
            debug["status"] = 200
            debug["response_sample"] = str(raw_items[:2])[:200]
            
            for item in raw_items:
                clean_url = item.get("href", "")
                if not clean_url or not clean_url.startswith("http"):
                    continue
                    
                domain = urllib.parse.urlparse(clean_url).netloc.lower()
                clean_domain = re.sub(r'^www\.', '', domain)
                
                if any(ex in clean_domain for ex in EXCLUDED_DOMAINS):
                    continue
                if clean_domain in seen_domains:
                    continue
                seen_domains.add(clean_domain)
                
                title = item.get("title", clean_domain)
                snippet = item.get("body", "")
                
                name = re.split(r'[:|\-–]|Contact|About|Home|Services', title)[0].strip()
                if not name or len(name) < 3:
                    name = clean_domain.split('.')[0].capitalize()
                    
                snippet_emails = re.findall(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', snippet)
                
                results.append({
                    "name": name,
                    "website": clean_url,
                    "city": city,
                    "country": country,
                    "business_type": business_type,
                    "address": f"{city}, {country}",
                    "phone": "",
                    "snippet": snippet,
                    "initial_email": snippet_emails[0] if snippet_emails else "",
                    "source": "Web Search (ddgs)"
                })
                
                if len(results) >= max_results:
                    break
                    
            if results:
                return results, debug
        except Exception as e:
            debug["error"] = str(e)
            time.sleep(1.5)
            
    # 2. Fallback to Brave Search if provided
    if not results and brave_api_key.strip():
        debug["fallback_triggered"] = True
        debug["engine_used"] = "Brave Search API"
        try:
            brave_url = "https://api.search.brave.com/res/v1/web/search"
            headers = {"Accept": "application/json", "X-Subscription-Token": brave_api_key.strip()}
            b_resp = requests.get(brave_url, params={"q": query, "count": max_results}, headers=headers, timeout=8)
            debug["status"] = b_resp.status_code
            debug["response_sample"] = b_resp.text[:200]
            if b_resp.status_code == 200:
                b_items = b_resp.json().get("web", {}).get("results", [])
                for b in b_items:
                    url = b.get("url")
                    dom = re.sub(r'^www\.', '', urllib.parse.urlparse(url).netloc.lower())
                    if not any(ex in dom for ex in EXCLUDED_DOMAINS) and dom not in seen_domains:
                        seen_domains.add(dom)
                        results.append({
                            "name": b.get("title", dom).split("-")[0].strip(),
                            "website": url,
                            "city": city,
                            "country": country,
                            "business_type": business_type,
                            "address": f"{city}, {country}",
                            "phone": "",
                            "snippet": b.get("description", ""),
                            "initial_email": "",
                            "source": "Web Search (Brave API)"
                        })
                return results, debug
        except Exception as e:
            debug["error"] = f"Brave Search Error: {e}"

    # 3. Fallback to Serper.dev if provided
    if not results and serper_api_key.strip():
        debug["fallback_triggered"] = True
        debug["engine_used"] = "Serper.dev API"
        try:
            serper_url = "https://google.serper.dev/search"
            headers = {"X-API-KEY": serper_api_key.strip(), "Content-Type": "application/json"}
            s_resp = requests.post(serper_url, json={"q": query, "num": max_results}, headers=headers, timeout=8)
            debug["status"] = s_resp.status_code
            debug["response_sample"] = s_resp.text[:200]
            if s_resp.status_code == 200:
                s_items = s_resp.json().get("organic", [])
                for s in s_items:
                    url = s.get("link")
                    dom = re.sub(r'^www\.', '', urllib.parse.urlparse(url).netloc.lower())
                    if not any(ex in dom for ex in EXCLUDED_DOMAINS) and dom not in seen_domains:
                        seen_domains.add(dom)
                        results.append({
                            "name": s.get("title", dom).split("-")[0].strip(),
                            "website": url,
                            "city": city,
                            "country": country,
                            "business_type": business_type,
                            "address": f"{city}, {country}",
                            "phone": "",
                            "snippet": s.get("snippet", ""),
                            "initial_email": "",
                            "source": "Web Search (Serper.dev)"
                        })
                return results, debug
        except Exception as e:
            debug["error"] = f"Serper Error: {e}"

    return results, debug


def parse_linkedin_snippet(title: str, snippet: str, default_role: str = "") -> Dict[str, str]:
    """Extracts person name, role from LinkedIn SERP snippet."""
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
    """
    Step 6 Decision makers:
    Search '[role] [company] [city] site:linkedin.com/in' via ddgs.
    Never log into or scrape LinkedIn directly.
    """
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
