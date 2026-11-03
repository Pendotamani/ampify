import re
import time
import urllib.parse
from urllib.robotparser import RobotFileParser
from typing import Dict, Any, List, Set, Optional, Tuple
import requests
from bs4 import BeautifulSoup
import dns.resolver

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 ApolloBot/1.0"
}

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
PHONE_REGEX = re.compile(r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5}')

_ROBOTS_CACHE: Dict[str, Optional[RobotFileParser]] = {}
_MX_CACHE: Dict[str, bool] = {}


def check_mx_record(domain: str) -> bool:
    """Free MX record lookup using dnspython (no SMTP)."""
    clean_domain = domain.strip().lower()
    if clean_domain in _MX_CACHE:
        return _MX_CACHE[clean_domain]
        
    try:
        answers = dns.resolver.resolve(clean_domain, 'MX', lifetime=4)
        has_mx = len(answers) > 0
        _MX_CACHE[clean_domain] = has_mx
        return has_mx
    except Exception:
        try:
            a_answers = dns.resolver.resolve(clean_domain, 'A', lifetime=3)
            has_a = len(a_answers) > 0
            _MX_CACHE[clean_domain] = has_a
            return has_a
        except Exception:
            _MX_CACHE[clean_domain] = False
            return False


def can_fetch_url(url: str) -> bool:
    """Checks robots.txt for URL permissions."""
    try:
        parsed = urllib.parse.urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base in _ROBOTS_CACHE:
            rp = _ROBOTS_CACHE[base]
        else:
            robots_url = urllib.parse.urljoin(base, "/robots.txt")
            rp = RobotFileParser()
            rp.set_url(robots_url)
            try:
                r_resp = requests.get(robots_url, headers=HEADERS, timeout=4)
                if r_resp.status_code == 200:
                    rp.parse(r_resp.text.splitlines())
                else:
                    rp = None
            except Exception:
                rp = None
            _ROBOTS_CACHE[base] = rp

        if rp:
            return rp.can_fetch(HEADERS["User-Agent"], url)
        return True
    except Exception:
        return True


def extract_social_links(soup: BeautifulSoup) -> List[str]:
    """Finds links to LinkedIn, Twitter/X, Facebook, Instagram."""
    social_links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower()
        if any(network in low for network in ["linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com"]):
            social_links.add(href)
    return list(social_links)[:4]


def scrape_page(url: str, timeout: int = 8) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Scrapes a single page for emails, phones, social links, and subpage candidates."""
    data = {"emails": [], "phones": [], "socials": [], "subpages": []}
    debug = {"url": url, "status": None, "error": None, "response_sample": ""}
    
    if not can_fetch_url(url):
        debug["error"] = "Blocked by robots.txt"
        return data, debug

    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        debug["status"] = resp.status_code
        debug["response_sample"] = resp.text[:200]
        
        if resp.status_code != 200:
            debug["error"] = f"HTTP {resp.status_code}"
            return data, debug
            
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
            
        text = soup.get_text(separator=" ")
        
        # Emails
        raw_emails = set(EMAIL_REGEX.findall(text))
        for m in raw_emails:
            low = m.lower()
            if not any(low.endswith(ext) for ext in ('.png', '.jpg', '.jpeg', '.svg', '.webp', '.js', '.css')) and len(low) < 60:
                data["emails"].append(m)
                
        # Phones
        for p in PHONE_REGEX.findall(text):
            digits = re.sub(r'\D', '', p)
            if 8 <= len(digits) <= 15:
                data["phones"].append(p.strip())
                
        # Mailto / tel links
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith("mailto:"):
                mail = href.replace("mailto:", "").split("?")[0].strip()
                if mail and mail not in data["emails"]:
                    data["emails"].append(mail)
            elif href.startswith("tel:"):
                tel = href.replace("tel:", "").strip()
                if tel and tel not in data["phones"]:
                    data["phones"].append(tel)
                    
        # Social links
        data["socials"] = extract_social_links(soup)
        
        # Discover subpages
        netloc = urllib.parse.urlparse(url).netloc
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            low = href.lower()
            anchor_text = a.get_text().lower()
            if any(term in low or term in anchor_text for term in ["contact", "about", "team", "people", "reach"]):
                full = urllib.parse.urljoin(url, href)
                if urllib.parse.urlparse(full).netloc == netloc and full != url:
                    data["subpages"].append(full)
                    
    except Exception as e:
        debug["error"] = str(e)
        
    return data, debug


def crawl_company_website(website_url: str, delay: float = 0.5) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Website crawler:
    Checks homepage, /contact, /about, and /team.
    Extracts emails, phones, social links. Respects robots.txt and delays.
    """
    if not website_url:
        return {"emails": [], "phones": [], "socials": [], "pages_visited": []}, []
        
    debug_logs = []
    all_emails: Set[str] = set()
    all_phones: Set[str] = set()
    all_socials: Set[str] = set()
    visited_pages: Set[str] = set()
    
    # 1. Homepage
    hp_data, hp_dbg = scrape_page(website_url)
    debug_logs.append(hp_dbg)
    all_emails.update(hp_data["emails"])
    all_phones.update(hp_data["phones"])
    all_socials.update(hp_data["socials"])
    visited_pages.add(website_url)
    
    # 2. Build candidate subpages (/contact, /about, /team, and any discovered links)
    parsed = urllib.parse.urlparse(website_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    direct_candidates = [
        urllib.parse.urljoin(origin, "/contact"),
        urllib.parse.urljoin(origin, "/about"),
        urllib.parse.urljoin(origin, "/team")
    ]
    
    combined_candidates = []
    for cand in direct_candidates + hp_data.get("subpages", []):
        if cand not in visited_pages and cand not in combined_candidates:
            combined_candidates.append(cand)
            
    # Visit up to 3 subpages with polite delay
    for page in combined_candidates[:3]:
        if delay > 0:
            time.sleep(delay)
        sub_data, sub_dbg = scrape_page(page)
        debug_logs.append(sub_dbg)
        all_emails.update(sub_data["emails"])
        all_phones.update(sub_data["phones"])
        all_socials.update(sub_data["socials"])
        visited_pages.add(page)
        
    return {
        "emails": list(all_emails),
        "phones": list(all_phones)[:3],
        "socials": list(all_socials)[:4],
        "pages_visited": list(visited_pages)
    }, debug_logs


def generate_and_verify_emails(
    person_name: str,
    domain_or_url: str,
    found_on_site: List[str]
) -> List[Dict[str, str]]:
    """
    Step 7 Emails:
    Guesses name@domain, first.last@domain, info@domain.
    Checks MX records and marks each email status as:
    - 'found on site'
    - 'guessed'
    - 'MX valid' (or 'No MX')
    """
    results = []
    
    # 1. First register emails found on site
    seen_addresses = set()
    for email in found_on_site:
        clean = email.strip().lower()
        if clean not in seen_addresses:
            seen_addresses.add(clean)
            domain = clean.split("@")[-1]
            mx_ok = check_mx_record(domain)
            status = "found on site | MX valid" if mx_ok else "found on site | No MX"
            results.append({"email": clean, "status": status})
            
    # 2. Extract domain for guessing
    if not domain_or_url:
        return results
        
    if domain_or_url.startswith("http"):
        domain = urllib.parse.urlparse(domain_or_url).netloc
    else:
        domain = domain_or_url
    domain = re.sub(r'^www\.', '', domain.split('/')[0]).strip().lower()
    
    if not domain or "." not in domain:
        return results
        
    has_mx = check_mx_record(domain)
    mx_label = "MX valid" if has_mx else "No MX"
    
    # 3. Guess info@domain
    info_email = f"info@{domain}"
    if info_email not in seen_addresses:
        seen_addresses.add(info_email)
        results.append({"email": info_email, "status": f"guessed | {mx_label}"})
        
    # 4. Guess person variations if name available
    clean_name = re.sub(r'[^a-zA-Z\s]', '', person_name).strip().lower()
    parts = clean_name.split()
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        guesses = [
            f"{first}.{last}@{domain}",
            f"{first}@{domain}",
            f"{first[0]}{last}@{domain}"
        ]
        for g in guesses:
            if g not in seen_addresses:
                seen_addresses.add(g)
                results.append({"email": g, "status": f"guessed | {mx_label}"})
    elif len(parts) == 1 and parts[0]:
        single_g = f"{parts[0]}@{domain}"
        if single_g not in seen_addresses:
            seen_addresses.add(single_g)
            results.append({"email": single_g, "status": f"guessed | {mx_label}"})
            
    return results
