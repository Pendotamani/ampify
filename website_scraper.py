import re
import time
import urllib.parse
from urllib.robotparser import RobotFileParser
from typing import Dict, Any, List, Set, Optional
import requests
from bs4 import BeautifulSoup
import dns.resolver

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
PHONE_REGEX = re.compile(r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5}')

_ROBOTS_CACHE: Dict[str, Optional[RobotFileParser]] = {}
_MX_CACHE: Dict[str, bool] = {}


def check_mx_record(domain: str) -> bool:
    """
    Free MX record lookup using dnspython (no SMTP connections or spamming).
    """
    clean_domain = domain.strip().lower()
    if clean_domain in _MX_CACHE:
        return _MX_CACHE[clean_domain]
        
    try:
        answers = dns.resolver.resolve(clean_domain, 'MX', lifetime=4)
        has_mx = len(answers) > 0
        _MX_CACHE[clean_domain] = has_mx
        return has_mx
    except Exception:
        # Fallback check for A record if no MX record
        try:
            a_answers = dns.resolver.resolve(clean_domain, 'A', lifetime=3)
            has_a = len(a_answers) > 0
            _MX_CACHE[clean_domain] = has_a
            return has_a
        except Exception:
            _MX_CACHE[clean_domain] = False
            return False


def verify_emails_mx(emails: List[str]) -> List[str]:
    """
    Filters or marks emails having valid MX/domain records.
    """
    verified = []
    for email in emails:
        parts = email.split('@')
        if len(parts) == 2:
            domain = parts[1]
            if check_mx_record(domain):
                verified.append(f"{email} [Valid MX]")
            else:
                verified.append(f"{email} [No MX]")
        else:
            verified.append(email)
    return verified


def guess_emails(person_name: str, domain_or_url: str) -> List[str]:
    """
    Generates guessed emails:
    - name@domain
    - first.last@domain
    - info@domain
    And checks MX records.
    """
    if not domain_or_url:
        return []
        
    # Extract domain
    if domain_or_url.startswith("http"):
        domain = urllib.parse.urlparse(domain_or_url).netloc
    else:
        domain = domain_or_url
    domain = re.sub(r'^www\.', '', domain.split('/')[0]).strip().lower()
    
    if not domain or "." not in domain:
        return []
        
    guesses = []
    
    # 1. info@domain
    guesses.append(f"info@{domain}")
    
    # Clean person name
    clean_name = re.sub(r'[^a-zA-Z\s]', '', person_name).strip().lower()
    parts = clean_name.split()
    
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        guesses.append(f"{first}.{last}@{domain}")
        guesses.append(f"{first}@{domain}")
        guesses.append(f"{first[0]}{last}@{domain}")
    elif len(parts) == 1 and parts[0]:
        guesses.append(f"{parts[0]}@{domain}")
        
    # Check MX records for domain
    has_mx = check_mx_record(domain)
    status_tag = "[Valid MX]" if has_mx else "[No MX]"
    
    return [f"{g} {status_tag}" for g in list(dict.fromkeys(guesses))]


def can_fetch_url(url: str) -> bool:
    """Checks robots.txt for URL permission."""
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


def extract_emails(text: str) -> List[str]:
    raw_matches = set(EMAIL_REGEX.findall(text))
    valid = []
    ignored_ext = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.js', '.css')
    for m in raw_matches:
        low = m.lower()
        if not any(low.endswith(ext) for ext in ignored_ext) and len(low) < 60:
            valid.append(m)
    return valid


def extract_phones(text: str) -> List[str]:
    matches = PHONE_REGEX.findall(text)
    clean_phones = set()
    for p in matches:
        digits = re.sub(r'\D', '', p.strip())
        if 8 <= len(digits) <= 15:
            clean_phones.add(p.strip())
    return list(clean_phones)


def scrape_single_page(url: str, timeout: int = 8) -> Dict[str, Any]:
    data = {"emails": [], "phones": [], "contact_pages": []}
    if not can_fetch_url(url):
        return data

    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return data
            
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
            
        page_text = soup.get_text(separator=" ")
        data["emails"] = extract_emails(page_text)
        data["phones"] = extract_phones(page_text)
        
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith("mailto:"):
                mail = href.replace("mailto:", "").split("?")[0].strip()
                if mail and mail not in data["emails"]:
                    data["emails"].append(mail)
            elif href.startswith("tel:"):
                phone = href.replace("tel:", "").strip()
                if phone and phone not in data["phones"]:
                    data["phones"].append(phone)
                    
            href_lower = href.lower()
            anchor_text = a.get_text().lower()
            if any(term in href_lower or term in anchor_text for term in ["contact", "about", "reach-us"]):
                full_link = urllib.parse.urljoin(url, href)
                if urllib.parse.urlparse(full_link).netloc == urllib.parse.urlparse(url).netloc:
                    if full_link not in data["contact_pages"] and full_link != url:
                        data["contact_pages"].append(full_link)
    except Exception:
        pass
        
    return data


def scrape_website_info(base_url: str, delay_sec: float = 1.0) -> Dict[str, Any]:
    """
    Visits homepage and explicitly tests /contact and /about pages.
    Extracts emails, performs MX checks, and gathers phones.
    """
    if not base_url:
        return {"scraped_emails": "", "scraped_phones": "", "contact_links": ""}
        
    all_emails: Set[str] = set()
    all_phones: Set[str] = set()
    all_contact_pages: Set[str] = set()
    
    # 1. Scrape Homepage
    hp_data = scrape_single_page(base_url)
    all_emails.update(hp_data["emails"])
    all_phones.update(hp_data["phones"])
    all_contact_pages.update(hp_data["contact_pages"])
    
    # 2. Add direct /contact and /about URLs to test
    parsed = urllib.parse.urlparse(base_url)
    base_origin = f"{parsed.scheme}://{parsed.netloc}"
    direct_candidates = [
        urllib.parse.urljoin(base_origin, "/contact"),
        urllib.parse.urljoin(base_origin, "/contact-us"),
        urllib.parse.urljoin(base_origin, "/about"),
        urllib.parse.urljoin(base_origin, "/about-us")
    ]
    for cand in direct_candidates:
        if cand not in all_contact_pages and cand != base_url:
            all_contact_pages.add(cand)
            
    # Visit up to 2 discovered / contact pages
    to_visit = list(all_contact_pages)[:2]
    for page_url in to_visit:
        if delay_sec > 0:
            time.sleep(delay_sec)
        sub_data = scrape_single_page(page_url)
        all_emails.update(sub_data["emails"])
        all_phones.update(sub_data["phones"])
        
    # Apply free MX check on scraped emails
    verified_emails = verify_emails_mx(list(all_emails)[:3])
    
    return {
        "scraped_emails": ", ".join(verified_emails),
        "scraped_phones": ", ".join(list(all_phones)[:3]),
        "contact_links": ", ".join(list(all_contact_pages)[:3])
    }
