import time
import urllib.parse
import pandas as pd
import streamlit as st

from finder import geocode_city_nominatim, query_overpass_mirrors
from search import search_web_companies, search_decision_maker_linkedin
from website_scraper import crawl_company_website, process_emails_and_fallbacks

# Global Apollo-style selectors
GLOBAL_COUNTRIES = [
    "India", "USA", "UK", "Australia", "UAE", "South Africa",
    "Canada", "Germany", "France", "Singapore", "Japan", "Brazil", "Other"
]

COUNTRY_CITIES = {
    "India": ["Hyderabad", "Bengaluru", "Mumbai", "Delhi", "Pune", "Chennai", "Kolkata", "Ahmedabad"],
    "USA": ["New York", "San Francisco", "Austin", "Los Angeles", "Chicago", "Miami", "Seattle"],
    "UK": ["London", "Manchester", "Birmingham", "Edinburgh", "Bristol"],
    "Australia": ["Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide"],
    "UAE": ["Dubai", "Abu Dhabi", "Sharjah"],
    "South Africa": ["Johannesburg", "Cape Town", "Durban", "Pretoria"],
    "Canada": ["Toronto", "Vancouver", "Montreal", "Calgary"],
    "Germany": ["Berlin", "Munich", "Frankfurt", "Hamburg"],
    "France": ["Paris", "Lyon", "Marseille"],
    "Singapore": ["Singapore"],
    "Japan": ["Tokyo", "Osaka"],
    "Brazil": ["São Paulo", "Rio de Janeiro"]
}

BUSINESS_TYPES = [
    "transport", "logistics", "fleet owner", "restaurants", "real estate",
    "IT", "hotels", "clinics", "retail", "travel agencies",
    "marketing agency", "construction", "manufacturing", "consulting", "Custom"
]

DEFAULT_ROLES = ["CEO", "Founder", "Director", "Marketing Head", "Fleet Manager", "Owner"]


def push_to_google_sheet(df: pd.DataFrame) -> bool:
    """
    Placeholder function to connect backend Google Sheet credentials.
    """
    print(f"[Placeholder] push_to_google_sheet called with {len(df)} records.")
    return True


st.set_page_config(
    page_title="Apollo Lead Finder & Quality Enricher",
    page_icon="🎯",
    layout="wide"
)

st.title("🎯 High-Quality Local & Global Lead Finder")
st.markdown(
    """
    *Extracts business leads with pre-crawl junk filtering, deep `/contact` and `/about` crawling, 
    regex telephone and email parsing, MX verification, and LinkedIn decision maker snippet enrichment.*
    """
)

# Sidebar UI
with st.sidebar:
    st.header("🔍 Search Parameters")
    
    chosen_country = st.selectbox("Country", GLOBAL_COUNTRIES, index=0)
    if chosen_country == "Other":
        country = st.text_input("Enter Country", value="India")
    else:
        country = chosen_country
        
    avail_cities = COUNTRY_CITIES.get(chosen_country, ["Custom City"]) + ["Custom City..."]
    city_choice = st.selectbox("City", avail_cities, index=0)
    if city_choice == "Custom City..." or chosen_country == "Other":
        city = st.text_input("Enter City", value="Hyderabad")
    else:
        city = city_choice
        
    bt_choice = st.selectbox("Business Type", BUSINESS_TYPES, index=0)
    if bt_choice == "Custom":
        business_type = st.text_input("Custom Business Type", value="transport")
    else:
        business_type = bt_choice
        
    selected_roles = st.multiselect("Target Decision Maker Roles", DEFAULT_ROLES, default=["Director", "CEO", "Owner"])
    custom_role = st.text_input("Add Custom Role (Optional)", value="")
    if custom_role.strip():
        selected_roles.append(custom_role.strip())
    primary_role = selected_roles[0] if selected_roles else "Director"

    st.markdown("---")
    st.subheader("⚙️ Quality Filters & Settings")
    
    # 3. Sidebar checkbox: 'Only show leads with phone or email' (on by default)
    only_with_contacts = st.checkbox("Only show leads with phone or email", value=True)
    
    max_results = st.slider("Max Search Results", min_value=3, max_value=40, value=10)
    crawl_delay = st.slider("Crawl Delay (seconds)", min_value=0.2, max_value=2.0, value=0.5, step=0.1)
    debug_mode = st.checkbox("Debug Mode (Show raw HTTP responses)", value=False)
    
    with st.expander("🔑 Fallback API Keys (Optional)"):
        st.caption("Optional fallback keys if free web search is rate-limited.")
        brave_key = st.text_input("Brave Search Key", type="password")
        serper_key = st.text_input("Serper.dev Key", type="password")

    st.markdown("---")
    start_btn = st.button("🚀 Find & Enrich Leads", use_container_width=True)


def display_debug_card(step_name: str, logs: Any):
    with st.expander(f"🔍 Debug Log: {step_name}", expanded=False):
        if isinstance(logs, list):
            for i, l in enumerate(logs):
                st.markdown(f"**Item {i+1}:** `{l.get('mirror') or l.get('url') or l.get('engine_used')}`")
                st.write(f"- **HTTP Status:** `{l.get('status')}`")
                if l.get('error'):
                    st.error(f"- **Error:** {l.get('error')}")
                st.code(f"First 200 chars:\n{l.get('response_sample', '')[:200]}", language="text")
        elif isinstance(logs, dict):
            st.write(f"- **Query / URL:** `{logs.get('query') or logs.get('url')}`")
            st.write(f"- **HTTP Status:** `{logs.get('status')}`")
            if logs.get('error'):
                st.error(f"- **Error:** {logs.get('error')}")
            st.code(f"First 200 chars:\n{logs.get('response_sample', '')[:200]}", language="text")


# Main Execution Pipeline
if start_btn:
    if not city.strip() or not business_type.strip():
        st.error("Please provide a valid City and Business Type.")
    else:
        st.info(f"Targeting: **{business_type}** in **{city}, {country}**...")
        raw_candidates = []
        
        # 1. OpenStreetMap Query
        with st.spinner("Source 1: Geocoding & querying OpenStreetMap..."):
            bbox, geo_dbg = geocode_city_nominatim(city, country)
            if debug_mode:
                display_debug_card("Nominatim Geocoding", geo_dbg)
            if bbox:
                osm_leads, osm_dbg = query_overpass_mirrors(bbox, business_type, city, country)
                if debug_mode:
                    display_debug_card("Overpass Mirrors", osm_dbg)
                raw_candidates.extend(osm_leads)
                
        # 2. Web Search Query
        with st.spinner("Source 2: Querying DDGS web search with junk filtering..."):
            web_leads, web_dbg = search_web_companies(
                business_type=business_type,
                city=city,
                country=country,
                max_results=max_results * 2,
                brave_api_key=brave_key,
                serper_api_key=serper_key
            )
            if debug_mode:
                display_debug_card("Web Search", web_dbg)
            raw_candidates.extend(web_leads)
            
        # Deduplicate candidates by root domain / name
        unique_companies = []
        seen_domains = set()
        for cand in raw_candidates:
            site = cand.get("website", "")
            domain = urllib.parse.urlparse(site).netloc.lower() if site else cand["name"].lower()
            if domain not in seen_domains:
                seen_domains.add(domain)
                unique_companies.append(cand)
                
        if not unique_companies:
            st.warning("No companies passed initial filtering. Check parameters or inspect debug logs.")
        else:
            targets = unique_companies[:max_results]
            progress = st.progress(0)
            status_txt = st.empty()
            
            enriched_records = []
            
            for idx, item in enumerate(targets):
                comp_name = item["name"]
                site_url = item.get("website", "")
                status_txt.text(f"Crawling ({idx+1}/{len(targets)}): {comp_name}...")
                
                # Step 2: Contact extraction (homepage, /contact, /contact-us, /about, /about-us)
                crawl_res = {"emails": [], "phones": []}
                if site_url:
                    crawl_res, crawl_dbg = crawl_company_website(site_url, delay=crawl_delay)
                    if debug_mode and crawl_dbg:
                        display_debug_card(f"Crawl: {comp_name}", crawl_dbg[0])
                        
                # Merge phone numbers
                phones_found = crawl_res.get("phones", [])
                if item.get("phone"):
                    phones_found.insert(0, item["phone"])
                clean_phone = ", ".join(list(dict.fromkeys(phones_found))[:2])
                
                # Step 6: Decision Maker search
                decision_maker = ""
                dm_role = ""
                linkedin_url = ""
                dm_res, dm_dbg = search_decision_maker_linkedin(role=primary_role, company=comp_name, city=city)
                if dm_res:
                    decision_maker = dm_res["person_name"]
                    dm_role = dm_res["person_role"]
                    linkedin_url = dm_res["linkedin_url"]
                if debug_mode and dm_dbg:
                    display_debug_card(f"LinkedIn DM: {comp_name}", dm_dbg)
                    
                # Step 4: Process emails & fallbacks (info@, contact@) + MX lookup
                email_items = process_emails_and_fallbacks(
                    found_emails=crawl_res.get("emails", []),
                    domain_or_url=site_url,
                    person_name=decision_maker
                )
                
                primary_email = email_items[0]["email"] if email_items else ""
                email_status = email_items[0]["status"] if email_items else "None"
                
                # Step 3: Exact table column order
                enriched_records.append({
                    "Company": comp_name,
                    "Phone": clean_phone,
                    "Email": primary_email,
                    "Email Status": email_status,
                    "Website": site_url,
                    "City": city,
                    "Country": country,
                    "Decision Maker": decision_maker,
                    "Role": dm_role,
                    "LinkedIn URL": linkedin_url,
                    "Source": item.get("source", "Web")
                })
                
                progress.progress((idx + 1) / len(targets))
                
            status_txt.text("Enrichment complete!")
            st.session_state["leads_table"] = pd.DataFrame(enriched_records)

# Display Table & Statistics
if "leads_table" in st.session_state and not st.session_state["leads_table"].empty:
    raw_df: pd.DataFrame = st.session_state["leads_table"]
    
    # 3. Apply 'Only show leads with phone or email' filter
    if only_with_contacts:
        filtered_df = raw_df[(raw_df["Phone"] != "") | (raw_df["Email"] != "")].copy()
    else:
        filtered_df = raw_df.copy()
        
    # 3. Top counts
    total_count = len(raw_df)
    with_phone_count = (raw_df["Phone"] != "").sum()
    with_email_count = (raw_df["Email"] != "").sum()
    
    st.markdown("---")
    st.subheader("📊 Lead Discovery Summary")
    
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Found", total_count)
    m2.metric("With Phone Number", int(with_phone_count))
    m3.metric("With Verified/Guessed Email", int(with_email_count))
    m4.metric("Displayed in Table", len(filtered_df))
    
    # Dataframe rendering with columns in exact requested order
    st.dataframe(
        filtered_df,
        column_order=[
            "Company", "Phone", "Email", "Email Status", "Website",
            "City", "Country", "Decision Maker", "Role", "LinkedIn URL", "Source"
        ],
        use_container_width=True
    )
    
    col1, col2 = st.columns([1, 1])
    with col1:
        csv_bytes = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Leads as CSV",
            data=csv_bytes,
            file_name=f"leads_{city.lower()}_{business_type.lower()}.csv",
            mime="text/csv",
            use_container_width=True
        )
    with col2:
        if st.button("☁️ Push to Google Sheet (Placeholder)", use_container_width=True):
            push_to_google_sheet(filtered_df)
            st.success("Triggered `push_to_google_sheet()` with all qualified rows.")
