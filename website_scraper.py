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

# International phone formats (handles +91, (040), standard mobile/landlines)
PHONE_REGEXES = [
    re.compile(r'(?:\+?(\d{1,3}))?[-.\s]?(?:\(?(\d{2,5})\)?)?[-.\s]?(\d{3,5})[-.\s]?(\d{3,5})'),
    re.compile(r'\b(?:\+91[-\s]?)?[6-9]\d{9}\b'), # Indian 10-digit mobile
    re.compile(r'\b0\d{2,4}[-\s]?\d{6,8}\b'),     # Indian landlines (e.g. 040-XXXXXXXX)
    re.compile(r'\b(?:\+1[-\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'), # US/Canada
    re.compile(r'\b(?:\+44[-\s]?)?\d{4,5}[-\s]?\d{6}\b') # UK
]

_ROBOTS_CACHE: Dict[str, Optional[RobotFileParser]] = {}
_MX_CACHE: Dict[str, bool] = {}


def check_mx_record(domain: str) -> bool:
    """Free MX record lookup via dnspython."""
    clean = domain.strip().lower()
    if clean in _MX_CACHE:
        return _MX_CACHE[clean]
        
    try:
        answers = dns.resolver.resolve(clean, 'MX', lifetime=4)
        has_mx = len(answers) > 0
        _MX_CACHE[clean] = has_mx
        return has_mx
    except Exception:
        try:
            a_ans = dns.resolver.resolve(clean, 'A', lifetime=3)
            has_a = len(a_ans) > 0
            _MX_CACHE[clean] = has_a
            return has_a
        except Exception:
            _MX_CACHE[clean] = False
            return False


def can_fetch_url(url: str) -> bool:
    """Respects robots.txt before making requests."""
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


def clean_emails(raw_list: List[str]) -> List[str]:
    """Cleans emails: removes images/assets, lowercases, removes duplicates."""
    clean = []
    seen = set()
    ignored_ext = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.js', '.css', '.ico')
    for e in raw_list:
        low = e.strip().lower()
        if not low or "@" not in low:
            continue
        if any(low.endswith(ext) for ext in ignored_ext):
            continue
        if len(low) < 5 or len(low) > 60:
            continue
        if low not in seen:
            seen.add(low)
            clean.append(low)
    return clean


def clean_phones(raw_list: List[str]) -> List[str]:
    """Cleans phone numbers: formats, removes short numbers/noise."""
    clean = []
    seen_digits = set()
    for p in raw_list:
        p_str = p.strip()
        digits = re.sub(r'\D', '', p_str)
        # Skip invalid or common year numbers (e.g. 2024, 2026)
        if 8 <= len(digits) <= 15:
            if digits not in seen_digits:
                seen_digits.add(digits)
                clean.append(p_str)
    return clean


def scrape_page(url: str, timeout: int = 8) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Extracts emails and phones (regex + mailto: + tel:)."""
    data = {"emails": [], "phones": [], "subpages": []}
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
            
        page_text = soup.get_text(separator=" ")
        
        # Regex extraction
        found_emails = EMAIL_REGEX.findall(page_text)
        found_phones = []
        for rx in PHONE_REGEXES:
            matches = rx.findall(page_text)
            for m in matches:
                if isinstance(m, tuple):
                    # Filter out empty tuple items from capture groups
                    joined = "".join(m)
                    if joined:
                        found_phones.append(joined)
                elif isinstance(m, str) and m:
                    found_phones.append(m)
            
        # Mailto: and tel: links
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith("mailto:"):
                mail = href.replace("mailto:", "").split("?")[0].strip()
                if mail:
                    found_emails.append(mail)
            elif href.startswith("tel:"):
                phone = href.replace("tel:", "").strip()
                if phone:
                    found_phones.append(phone)
                    
            # Subpages candidate check
            href_low = href.lower()
            anchor_low = a.get_text().lower()
            if any(term in href_low or term in anchor_low for term in ["contact", "about"]):
                full_link = urllib.parse.urljoin(url, href)
                if urllib.parse.urlparse(full_link).netloc == urllib.parse.urlparse(url).netloc and full_link != url:
                    data["subpages"].append(full_link)
                    
        data["emails"] = clean_emails(found_emails)
        data["phones"] = clean_phones(found_phones)
    except Exception as e:
        debug["error"] = str(e)
        
    return data, debug


def crawl_company_website(website_url: str, delay: float = 0.5) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    2. Contact extraction:
    Crawls: homepage, /contact, /contact-us, /about, /about-us.
    Extracts emails (regex + mailto:), phones (country regex + tel:).
    Cleans data, lowercases, removes image extensions and duplicates.
    """
    if not website_url:
        return {"emails": [], "phones": [], "pages_visited": []}, []
        
    debug_logs = []
    all_emails: Set[str] = set()
    all_phones: Set[str] = set()
    visited_pages: Set[str] = set()
    
    parsed = urllib.parse.urlparse(website_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    
    # Target URL list in exact priority order
    targets = [
        website_url,
        urllib.parse.urljoin(origin, "/contact"),
        urllib.parse.urljoin(origin, "/contact-us"),
        urllib.parse.urljoin(origin, "/about"),
        urllib.parse.urljoin(origin, "/about-us")
    ]
    
    for target in targets:
        if target in visited_pages:
            continue
        visited_pages.add(target)
        
        if len(visited_pages) > 1 and delay > 0:
            time.sleep(delay)
            
        data, dbg = scrape_page(target)
        debug_logs.append(dbg)
        all_emails.update(data["emails"])
        all_phones.update(data["phones"])
        
        # If we have both an email and phone, stop crawling further pages to be fast
        if all_emails and all_phones:
            break
            
    return {
        "emails": clean_emails(list(all_emails)),
        "phones": clean_phones(list(all_phones))[:3],
        "pages_visited": list(visited_pages)
    }, debug_logs


def extract_root_domain(domain_or_url: str) -> str:
    """Extracts root domain for email guessing."""
    try:
        if domain_or_url.startswith("http"):
            domain = urllib.parse.urlparse(domain_or_url).netloc
        else:
            domain = domain_or_url
        domain = re.sub(r'^www\.', '', domain.split('/')[0]).strip().lower()
        parts = domain.split('.')
        if len(parts) >= 3 and parts[-2] in ('co', 'com', 'org', 'gov', 'net') and len(parts[-1]) == 2:
            return ".".join(parts[-3:])
        return domain
    except Exception:
        return ""


def process_emails_and_fallbacks(
    found_emails: List[str],
    domain_or_url: str,
    person_name: str = ""
) -> List[Dict[str, str]]:
    """
    4. Fallback:
    If site has emails -> mark as 'found on site | [MX status]'
    If site has NO email -> generate info@domain, contact@domain, mark 'guessed | [MX status]'
    """
    results = []
    seen = set()
    
    # 1. Register emails found on site
    for email in found_emails:
        clean = email.lower().strip()
        if clean not in seen:
            seen.add(clean)
            domain = clean.split("@")[-1]
            mx_ok = check_mx_record(domain)
            mx_status = "MX valid" if mx_ok else "No MX"
            results.append({
                "email": clean,
                "status": f"found on site | {mx_status}"
            })
            
    # 2. Fallback if no email was found on the site
    root_domain = extract_root_domain(domain_or_url)
    if not results and root_domain and "." in root_domain:
        mx_ok = check_mx_record(root_domain)
        mx_status = "MX valid" if mx_ok else "No MX"
        
        fallback_candidates = [
            f"info@{root_domain}",
            f"contact@{root_domain}"
        ]
        
        # Also guess person name if available
        if person_name:
            c_name = re.sub(r'[^a-zA-Z\s]', '', person_name).strip().lower()
            parts = c_name.split()
            if len(parts) >= 2:
                fallback_candidates.append(f"{parts[0]}.{parts[-1]}@{root_domain}")
            elif len(parts) == 1 and parts[0]:
                fallback_candidates.append(f"{parts[0]}@{root_domain}")
                
        for cand in fallback_candidates:
            if cand not in seen:
                seen.add(cand)
                results.append({
                    "email": cand,
                    "status": f"guessed | {mx_status}"
                })
                
    return results
