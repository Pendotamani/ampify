import time
import requests
import re
from typing import List, Dict, Any

# Fast public Overpass endpoints
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
]

# Accurate bounding boxes for Hyderabad & top metropolitan hubs
CITY_BBOX_MAP = {
    "hyderabad": (17.15, 78.20, 17.65, 78.70),
    "secunderabad": (17.40, 78.45, 17.55, 78.55),
    "bangalore": (12.80, 77.40, 13.15, 77.80),
    "bengaluru": (12.80, 77.40, 13.15, 77.80),
    "mumbai": (18.85, 72.75, 19.30, 73.05),
    "delhi": (28.40, 76.85, 28.90, 77.40),
    "pune": (18.40, 73.70, 18.65, 74.00),
    "chennai": (12.90, 80.10, 13.25, 80.35)
}


def get_city_bbox(city: str) -> tuple:
    clean_city = city.lower().strip()
    if clean_city in CITY_BBOX_MAP:
        return CITY_BBOX_MAP[clean_city]
        
    try:
        url = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": "PublicLeadFinder/3.0"}
        resp = requests.get(url, params={"q": city, "format": "json", "limit": 1}, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data and "boundingbox" in data[0]:
                bbox = data[0]["boundingbox"]
                return (float(bbox[0]), float(bbox[2]), float(bbox[1]), float(bbox[3]))
    except Exception:
        pass
        
    return (17.15, 78.20, 17.65, 78.70)


def build_overpass_query(bbox: tuple, keyword: str, timeout: int = 15) -> str:
    s, w, n, e = bbox
    bbox_str = f"{s},{w},{n},{e}"
    clean_kw = re.sub(r'[^a-zA-Z0-9\s]', '', keyword).strip()
    # Extract first word if multi-word like "fleet owner" -> "fleet"
    primary_kw = clean_kw.split()[0] if clean_kw else "transport"
    
    return f"""
    [out:json][timeout:{timeout}];
    (
      node["amenity"="taxi"]({bbox_str});
      node["office"="logistics"]({bbox_str});
      node["office"="transport"]({bbox_str});
      node["office"="travel_agent"]({bbox_str});
      node["office"="company"]({bbox_str});
      node["shop"="travel_agency"]({bbox_str});
      node["name"~"{primary_kw}",i]({bbox_str});
      way["office"~"logistics|transport|company"]({bbox_str});
      way["name"~"{primary_kw}",i]({bbox_str});
    );
    out center tags 40;
    """


def query_nominatim_osm(city: str, business_type: str) -> List[Dict[str, Any]]:
    """
    Direct OpenStreetMap Nominatim POI query.
    Guaranteed public directory response for city + keyword.
    """
    results = []
    clean_type = re.sub(r'[^a-zA-Z0-9\s]', '', business_type).strip()
    queries = [
        f"{clean_type} in {city}",
        f"{clean_type} company {city}",
        f"logistics {city}" if "transport" in clean_type or "fleet" in clean_type else f"{clean_type} {city}"
    ]
    
    headers = {"User-Agent": "PublicLeadFinder/3.0 (leadfinder@businessleads.local)"}
    
    for q in queries:
        try:
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                "q": q,
                "format": "json",
                "addressdetails": 1,
                "extratags": 1,
                "limit": 20
            }
            resp = requests.get(url, params=params, headers=headers, timeout=6)
            if resp.status_code == 200:
                for item in resp.json():
                    name = item.get("name") or item.get("display_name", "").split(",")[0]
                    if not name or len(name) < 3:
                        continue
                        
                    # Filter out purely generic road/highway names unless it's an office
                    osm_type = item.get("type", "")
                    if osm_type in ["highway", "road", "residential", "tertiary"] and "Transport" not in name:
                        continue
                        
                    extratags = item.get("extratags", {}) or {}
                    website = extratags.get("website") or extratags.get("contact:website", "")
                    phone = extratags.get("phone") or extratags.get("contact:phone", "")
                    
                    results.append({
                        "name": name.strip(),
                        "address": item.get("display_name", city),
                        "phone": phone.strip(),
                        "website": website.strip(),
                        "city": city,
                        "type": osm_type or business_type,
                        "source": "OpenStreetMap Nominatim"
                    })
            if len(results) >= 15:
                break
        except Exception:
            continue
            
    return results


def query_overpass(city: str, business_type: str) -> List[Dict[str, Any]]:
    """
    Queries Overpass with timeout protection and merges with Nominatim OSM public records.
    """
    bbox = get_city_bbox(city)
    query = build_overpass_query(bbox, business_type)
    headers = {"User-Agent": "PublicLeadFinder/3.0"}
    
    overpass_results = []
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            resp = requests.post(endpoint, data={"data": query}, headers=headers, timeout=10)
            if resp.status_code == 200:
                elements = resp.json().get("elements", [])
                seen = set()
                for el in elements:
                    tags = el.get("tags", {})
                    name = tags.get("name")
                    if not name or name.strip().lower() in seen:
                        continue
                    seen.add(name.strip().lower())
                    
                    addr = tags.get("addr:street") or tags.get("addr:city") or city
                    phone = tags.get("phone") or tags.get("contact:phone", "")
                    website = tags.get("website") or tags.get("contact:website", "")
                    if website and not website.startswith("http"):
                        website = "http://" + website
                        
                    overpass_results.append({
                        "name": name.strip(),
                        "address": f"{addr}, {city}",
                        "phone": phone.strip(),
                        "website": website.strip(),
                        "city": city,
                        "type": tags.get("office") or tags.get("amenity") or business_type,
                        "source": "OpenStreetMap Overpass"
                    })
                if overpass_results:
                    break
        except Exception:
            continue
            
    # Always supplement with Nominatim POI public directory
    nominatim_results = query_nominatim_osm(city, business_type)
    
    # Merge and deduplicate
    combined = []
    seen_names = set()
    for item in overpass_results + nominatim_results:
        norm = item["name"].strip().lower()
        if norm not in seen_names:
            seen_names.add(norm)
            combined.append(item)
            
    return combined
