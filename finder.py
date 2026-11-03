import requests
import re
from typing import List, Dict, Any, Tuple, Optional

# Overpass mirrors to query in sequence
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter"
]

# Business type to OSM tags mapping
TAG_MAPPINGS = {
    "transport": [
        ('amenity', 'bus_station'), ('amenity', 'taxi'),
        ('office', 'transport'), ('office', 'logistics')
    ],
    "logistics": [
        ('office', 'logistics'), ('industrial', 'logistics'),
        ('amenity', 'loading_dock')
    ],
    "restaurants": [
        ('amenity', 'restaurant'), ('amenity', 'fast_food'),
        ('amenity', 'cafe')
    ],
    "real estate": [
        ('office', 'estate_agent'), ('shop', 'estate_agent')
    ],
    "it": [
        ('office', 'it'), ('office', 'telecommunication'),
        ('office', 'software')
    ],
    "hotels": [
        ('tourism', 'hotel'), ('tourism', 'motel'),
        ('tourism', 'guest_house')
    ],
    "clinics": [
        ('amenity', 'clinic'), ('amenity', 'doctors'),
        ('amenity', 'hospital'), ('amenity', 'dentist')
    ],
    "retail": [
        ('shop', 'supermarket'), ('shop', 'department_store'),
        ('shop', 'convenience'), ('shop', 'mall')
    ],
    "travel agencies": [
        ('office', 'travel_agent'), ('shop', 'travel_agency')
    ]
}

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ApolloLeadFinder/3.0 (leadfinder@apollo-global.org)"


def geocode_city_nominatim(city: str, country: str = "") -> Tuple[Optional[tuple], Dict[str, Any]]:
    """
    Geocode the city with Nominatim using a proper User-Agent to extract bounding box.
    Returns (bbox_tuple, debug_info).
    bbox_tuple: (south, west, north, east)
    """
    query = f"{city}, {country}".strip(", ")
    url = "https://nominatim.openstreetmap.org/search"
    headers = {"User-Agent": USER_AGENT}
    params = {"q": query, "format": "json", "limit": 1}
    
    debug = {"url": url, "query": query, "status": 0, "response_sample": "", "error": None}
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=8)
        debug["status"] = resp.status_code
        debug["response_sample"] = resp.text[:200]
        
        if resp.status_code == 200:
            data = resp.json()
            if data and "boundingbox" in data[0]:
                bbox = data[0]["boundingbox"] # [s, n, w, e]
                s, n, w, e = float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3])
                return (s, w, n, e), debug
            else:
                debug["error"] = "Nominatim returned empty results array."
        else:
            debug["error"] = f"HTTP error {resp.status_code}"
    except Exception as e:
        debug["error"] = str(e)
        
    return None, debug


def build_overpass_ql(bbox: tuple, business_type: str, timeout: int = 15) -> str:
    """
    Constructs an Overpass QL query mapping the business type to multiple OSM tags,
    plus regex search on name within bounding box.
    """
    s, w, n, e = bbox
    bbox_str = f"{s},{w},{n},{e}"
    
    bt_lower = business_type.lower().strip()
    tag_pairs = []
    for key, pairs in TAG_MAPPINGS.items():
        if key in bt_lower or bt_lower in key:
            tag_pairs.extend(pairs)
            
    # Default fallback tags if no specific mapping
    if not tag_pairs:
        tag_pairs = [('office', 'company'), ('office', 'commercial')]
        
    tag_queries = ""
    for k, v in set(tag_pairs):
        tag_queries += f'node["{k}"="{v}"]({bbox_str});\n'
        tag_queries += f'way["{k}"="{v}"]({bbox_str});\n'
        
    clean_kw = re.sub(r'[^a-zA-Z0-9]', '', bt_lower)
    if clean_kw:
        tag_queries += f'node["name"~"{clean_kw}",i]({bbox_str});\n'
        tag_queries += f'way["name"~"{clean_kw}",i]({bbox_str});\n'

    ql = f"""[out:json][timeout:{timeout}];
(
{tag_queries}
);
out center tags 30;
"""
    return ql


def query_overpass_mirrors(bbox: tuple, business_type: str, city: str, country: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Queries Overpass mirrors in sequence with timeout and collects detailed debug logs.
    Returns (leads, mirror_debug_logs).
    """
    ql = build_overpass_ql(bbox, business_type)
    headers = {"User-Agent": USER_AGENT}
    
    mirror_logs = []
    
    for mirror in OVERPASS_MIRRORS:
        log = {"mirror": mirror, "status": None, "error": None, "response_sample": ""}
        try:
            resp = requests.post(mirror, data={"data": ql}, headers=headers, timeout=12)
            log["status"] = resp.status_code
            log["response_sample"] = resp.text[:200]
            
            if resp.status_code == 200:
                data = resp.json()
                elements = data.get("elements", [])
                leads = []
                seen = set()
                
                for el in elements:
                    tags = el.get("tags", {})
                    name = tags.get("name")
                    if not name or name.strip().lower() in seen:
                        continue
                    seen.add(name.strip().lower())
                    
                    addr_parts = [
                        tags.get("addr:housenumber"),
                        tags.get("addr:street"),
                        tags.get("addr:suburb") or tags.get("addr:city") or city,
                        country
                    ]
                    address = ", ".join([p for p in addr_parts if p]) or f"{city}, {country}"
                    phone = tags.get("phone") or tags.get("contact:phone") or ""
                    website = tags.get("website") or tags.get("contact:website") or ""
                    
                    if website and not website.startswith("http"):
                        website = "http://" + website
                        
                    leads.append({
                        "name": name.strip(),
                        "address": address,
                        "phone": phone.strip(),
                        "website": website.strip(),
                        "city": city,
                        "country": country,
                        "business_type": tags.get("office") or tags.get("amenity") or tags.get("shop") or business_type,
                        "source": f"OpenStreetMap ({mirror.split('/')[2]})"
                    })
                    
                mirror_logs.append(log)
                if leads:
                    return leads, mirror_logs
            else:
                log["error"] = f"HTTP {resp.status_code}: {resp.reason}"
        except Exception as e:
            log["error"] = str(e)
            
        mirror_logs.append(log)
        
    return [], mirror_logs
