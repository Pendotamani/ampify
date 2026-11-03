import re
import time
import urllib.parse
from urllib.robotparser import RobotFileParser
from typing import Dict, Any, List, Set, Optional
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 LeadFinderBot/1.0"
}

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
PHONE_REGEX = re.compile(r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,5}\)?[-.\s]?\d{3,5}[-.\s]?\d{3,5}')

# Cache robots parsers by domain to avoid repetitive downloads
_ROBOTS_CACHE: Dict[str, Optional[RobotFileParser]] = {}


def can_fetch_url(url: str) -> bool:
    """
    Checks robots.txt for the given URL to respect crawl permissions.
    """
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
                # Short timeout for robots.txt
                r_resp = requests.get(robots_url, headers=HEADERS, timeout=5)
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
    """Finds emails in text while excluding common false positives (e.g. image extensions)."""
    raw_matches = set(EMAIL_REGEX.findall(text))
    valid = []
    ignored_ext = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.js', '.css')
    for m in raw_matches:
        low = m.lower()
        if not any(low.endswith(ext) for ext in ignored_ext) and len(low) < 60:
            valid.append(m)
    return valid


def extract_phones(text: str) -> List[str]:
    """Finds phone-like strings in text."""
    matches = PHONE_REGEX.findall(text)
    clean_phones = set()
    for p in matches:
        p_clean = p.strip()
        # Filter out numbers too short or obviously not telephone numbers
        digits = re.sub(r'\D', '', p_clean)
        if 8 <= len(digits) <= 15:
            clean_phones.add(p_clean)
    return list(clean_phones)


def scrape_single_page(url: str, timeout: int = 10) -> Dict[str, Any]:
    """
    Scrapes a single page for emails, phones, and contact/about links.
    """
    data = {
        "emails": [],
        "phones": [],
        "contact_pages": []
    }
    
    if not can_fetch_url(url):
        return data

    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return data
            
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Remove scripts and style elements
        for script in soup(["script", "style", "noscript"]):
            script.decompose()
            
        page_text = soup.get_text(separator=" ")
        data["emails"] = extract_emails(page_text)
        data["phones"] = extract_phones(page_text)
        
        # Search mailto and tel links
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
                    
            # Identify Contact / About pages
            href_lower = href.lower()
            anchor_text = a.get_text().lower()
            if any(term in href_lower or term in anchor_text for term in ["contact", "about", "reach-us", "touch"]):
                full_link = urllib.parse.urljoin(url, href)
                # Keep within the same domain
                if urllib.parse.urlparse(full_link).netloc == urllib.parse.urlparse(url).netloc:
                    if full_link not in data["contact_pages"] and full_link != url:
                        data["contact_pages"].append(full_link)
                        
    except Exception as e:
        pass
        
    return data


def scrape_website_info(base_url: str, delay_sec: float = 1.0) -> Dict[str, Any]:
    """
    Crawls the homepage and up to 2 discovered Contact/About pages.
    Extracts emails, phones, and keeps list of contact links.
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
    
    # 2. Scrape up to 2 contact/about pages if needed
    to_visit = list(all_contact_pages)[:2]
    for page_url in to_visit:
        if delay_sec > 0:
            time.sleep(delay_sec)
        sub_data = scrape_single_page(page_url)
        all_emails.update(sub_data["emails"])
        all_phones.update(sub_data["phones"])
        
    return {
        "scraped_emails": ", ".join(list(all_emails)[:3]),
        "scraped_phones": ", ".join(list(all_phones)[:3]),
        "contact_links": ", ".join(list(all_contact_pages)[:3])
    }
