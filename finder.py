import requests
import time
from typing import List, Dict, Any

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Common OSM tag mappings for keywords
KEYWORD_TAG_MAP = {
    "transport": [
        ('amenity', 'bus_station'),
        ('amenity', 'taxi'),
        ('office', 'logistics'),
        ('office', 'transport'),
        ('industrial', 'logistics'),
    ],
    "fleet": [
        ('office', 'logistics'),
        ('office', 'transport'),
        ('amenity', 'car_rental'),
        ('industrial', 'logistics'),
    ],
    "logistics": [
        ('office', 'logistics'),
        ('industrial', 'logistics'),
        ('amenity', 'loading_dock')
    ],
    "marketing": [
        ('office', 'advertising_agency'),
        ('office', 'marketing'),
        ('office', 'company')
    ],
    "agency": [
        ('office', 'advertising_agency'),
        ('office', 'company'),
        ('office', 'employment_agency')
    ]
}

def build_overpass_query(city: str, business_type: str, timeout: int = 25) -> str:
    """
    Constructs an Overpass QL query targeting the specified city and business type.
    """
    cleaned_type = business_type.lower().strip()
    
    # Check if keyword maps to specific OSM tags, else search name regex or office=company
    tags_to_check = []
    for key, tags in KEYWORD_TAG_MAP.items():
        if key in cleaned_type:
            tags_to_check.extend(tags)
            
    # Always include a fallback name search and broad office/commercial match
    query_body = ""
    if tags_to_check:
        for k, v in set(tags_to_check):
            query_body += f"""
            node["{k}"="{v}"](area.searchArea);
            way["{k}"="{v}"](area.searchArea);
            relation["{k}"="{v}"](area.searchArea);
            """
    
    # Also add case-insensitive regex match on name or generic commercial/office
    query_body += f"""
    node["name"~"{business_type}",i](area.searchArea);
    way["name"~"{business_type}",i](area.searchArea);
    node["office"]["name"](area.searchArea);
    way["office"]["name"](area.searchArea);
    """

    overpass_ql = f"""
    [out:json][timeout:{timeout}];
    area["name"="{city}"]->.searchArea;
    (
        {query_body}
    );
    out center tags;
    """
    return overpass_ql


def query_overpass(city: str, business_type: str) -> List[Dict[str, Any]]:
    """
    Queries Overpass API and returns extracted business listings:
    name, address, phone, website, coordinates.
    """
    headers = {
        "User-Agent": "LeadFinderAgent/1.0 (Educational/LeadFinder Research Tool)"
    }
    
    query = build_overpass_query(city, business_type)
    
    try:
        response = requests.post(
            OVERPASS_URL, 
            data={"data": query}, 
            headers=headers, 
            timeout=35
        )
        response.raise_for_warning = True
        if response.status_code != 200:
            return []
        
        data = response.json()
        elements = data.get("elements", [])
        
        results = []
        seen_names = set()
        
        for el in elements:
            tags = el.get("tags", {})
            name = tags.get("name")
            if not name:
                continue
                
            norm_name = name.strip().lower()
            if norm_name in seen_names:
                continue
            seen_names.add(norm_name)
            
            # Format address from OSM tags
            addr_parts = [
                tags.get("addr:housenumber"),
                tags.get("addr:street"),
                tags.get("addr:suburb") or tags.get("addr:district"),
                tags.get("addr:city") or city,
                tags.get("addr:postcode")
            ]
            address = ", ".join([p for p in addr_parts if p])
            if not address:
                address = tags.get("address", city)
                
            phone = tags.get("phone") or tags.get("contact:phone") or tags.get("telephone", "")
            website = tags.get("website") or tags.get("contact:website") or tags.get("url", "")
            
            # Ensure website starts with http/https
            if website and not website.startswith("http"):
                website = "http://" + website
                
            results.append({
                "name": name.strip(),
                "address": address,
                "phone": phone.strip(),
                "website": website.strip(),
                "city": city,
                "type": tags.get("office") or tags.get("amenity") or business_type
            })
            
        return results

    except Exception as e:
        print(f"Error querying Overpass API: {e}")
        return []

if __name__ == "__main__":
    test_leads = query_overpass("Hyderabad", "transport")
    print(f"Found {len(test_leads)} leads.")
    if test_leads:
        print("Sample:", test_leads[0])
