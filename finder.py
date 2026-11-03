import time
import requests
from typing import List, Dict, Any, Optional

# Public Overpass mirrors
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter"
]

# Hyderabad & major cities bounding boxes (south, west, north, east)
CITY_BBOX_MAP = {
    "hyderabad": (17.15, 78.20, 17.65, 78.70),
    "bangalore": (12.80, 77.40, 13.15, 77.80),
    "bengaluru": (12.80, 77.40, 13.15, 77.80),
    "mumbai": (18.85, 72.75, 19.30, 73.05),
    "delhi": (28.40, 76.85, 28.90, 77.40),
    "pune": (18.40, 73.70, 18.65, 74.00),
    "chennai": (12.90, 80.10, 13.25, 80.35)
}


def get_city_bbox(city: str) -> tuple:
    """Returns (south, west, north, east) bounding box for city."""
    clean_city = city.lower().strip()
    if clean_city in CITY_BBOX_MAP:
        return CITY_BBOX_MAP[clean_city]
        
    try:
        url = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": "LeadFinderAgentApp/2.0 (contact@leadfinder.local)"}
        resp = requests.get(url, params={"q": city, "format": "json", "limit": 1}, headers=headers, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if data:
                bbox = data[0].get("boundingbox", [])
                if len(bbox) == 4:
                    return (float(bbox[0]), float(bbox[2]), float(bbox[1]), float(bbox[3]))
    except Exception:
        pass
        
    return (17.15, 78.20, 17.65, 78.70)


def build_overpass_query(bbox: tuple, keyword: str, timeout: int = 25) -> str:
    """
    Overpass query using bounding box and targeted OSM tags:
    amenity=taxi, office=logistics, office=transport, office=travel_agent, shop=travel_agency,
    plus a case-insensitive regex on the keyword.
    """
    s, w, n, e = bbox
    bbox_str = f"{s},{w},{n},{e}"
    clean_kw = keyword.replace('"', '').strip()
    
    return f"""
    [out:json][timeout:{timeout}];
    (
      node["amenity"="taxi"]({bbox_str});
      way["amenity"="taxi"]({bbox_str});
      relation["amenity"="taxi"]({bbox_str});

      node["office"="logistics"]({bbox_str});
      way["office"="logistics"]({bbox_str});
      relation["office"="logistics"]({bbox_str});

      node["office"="transport"]({bbox_str});
      way["office"="transport"]({bbox_str});
      relation["office"="transport"]({bbox_str});

      node["office"="travel_agent"]({bbox_str});
      way["office"="travel_agent"]({bbox_str});
      relation["office"="travel_agent"]({bbox_str});

      node["shop"="travel_agency"]({bbox_str});
      way["shop"="travel_agency"]({bbox_str});
      relation["shop"="travel_agency"]({bbox_str});

      node["name"~"{clean_kw}",i]({bbox_str});
      way["name"~"{clean_kw}",i]({bbox_str});
      relation["name"~"{clean_kw}",i]({bbox_str});
    );
    out center tags;
    """


def query_nominatim_fallback(city: str, business_type: str) -> List[Dict[str, Any]]:
    """
    Direct OpenStreetMap Nominatim search fallback when Overpass public mirrors are rate-limited.
    """
    results = []
    try:
        url = "https://nominatim.openstreetmap.org/search"
        headers = {"User-Agent": "LeadFinderAgentApp/2.0 (leadfinder@businessleads.local)"}
        params = {
            "q": f"{business_type} in {city}",
            "format": "json",
            "addressdetails": 1,
            "extratags": 1,
            "limit": 25
        }
        resp = requests.get(url, params=params, headers=headers, timeout=8)
        if resp.status_code == 200:
            for item in resp.json():
                name = item.get("name") or item.get("display_name", "").split(",")[0]
                if not name:
                    continue
                extratags = item.get("extratags", {}) or {}
                results.append({
                    "name": name.strip(),
                    "address": item.get("display_name", city),
                    "phone": extratags.get("phone") or extratags.get("contact:phone", ""),
                    "website": extratags.get("website") or extratags.get("contact:website", ""),
                    "city": city,
                    "type": item.get("type") or business_type,
                    "source": "OpenStreetMap (Nominatim)"
                })
    except Exception as e:
        print(f"Nominatim fallback error: {e}")
    return results


def query_overpass(city: str, business_type: str) -> List[Dict[str, Any]]:
    """
    Queries Overpass API using bounding box and targeted tags + keyword regex.
    Falls back gracefully to Nominatim POI if public Overpass servers are congested.
    """
    bbox = get_city_bbox(city)
    query = build_overpass_query(bbox, business_type)
    
    headers = {
        "User-Agent": "LeadFinderAgentApp/2.0 (contact@leadfinder.local)"
    }
    
    for endpoint in OVERPASS_URLS:
        try:
            resp = requests.post(endpoint, data={"data": query}, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                elements = data.get("elements", [])
                
                results = []
                seen_names = set()
                
                for el in elements:
                    tags = el.get("tags", {})
                    name = tags.get("name")
                    if not name:
                        continue
                        
                    norm = name.strip().lower()
                    if norm in seen_names:
                        continue
                    seen_names.add(norm)
                    
                    addr_parts = [
                        tags.get("addr:housenumber"),
                        tags.get("addr:street"),
                        tags.get("addr:suburb") or tags.get("addr:district"),
                        tags.get("addr:city") or city,
                        tags.get("addr:postcode")
                    ]
                    address = ", ".join([p for p in addr_parts if p]) or tags.get("address", city)
                    phone = tags.get("phone") or tags.get("contact:phone") or tags.get("telephone", "")
                    website = tags.get("website") or tags.get("contact:website") or tags.get("url", "")
                    
                    if website and not website.startswith("http"):
                        website = "http://" + website
                        
                    results.append({
                        "name": name.strip(),
                        "address": address,
                        "phone": phone.strip(),
                        "website": website.strip(),
                        "city": city,
                        "type": tags.get("office") or tags.get("amenity") or tags.get("shop") or business_type,
                        "source": "OpenStreetMap (Overpass BBox)"
                    })
                if results:
                    return results
        except Exception:
            continue
            
    # If Overpass mirrors timed out or gave 406/429, fall back to Nominatim OSM search
    return query_nominatim_fallback(city, business_type)
