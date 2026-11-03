import time
import urllib.parse
import pandas as pd
import streamlit as st

from finder import geocode_city_nominatim, query_overpass_mirrors
from search import search_web_companies, search_decision_maker_linkedin
from website_scraper import crawl_company_website, generate_and_verify_emails


# Data dictionaries for Global Apollo-style selectors
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
    Placeholder function so you can connect backend Google Sheet credentials later.
    """
    print(f"[Placeholder] push_to_google_sheet called with {len(df)} rows.")
    return True


st.set_page_config(
    page_title="Apollo-Style Global Lead Finder Agent",
    page_icon="🚀",
    layout="wide"
)

st.title("🚀 Apollo-Style Global Lead Finder Agent")
st.markdown(
    """
    Search businesses worldwide via **OpenStreetMap Overpass Mirrors** and **DDGS Public Web Search**, 
    deep-crawl company pages (`/contact`, `/about`, `/team`), enrich decision-makers via LinkedIn snippets, 
    and verify domain MX records with email guessing.
    """
)

# Sidebar UI
with st.sidebar:
    st.header("🌍 Search Parameters")
    
    # 1. Country Selection
    chosen_country = st.selectbox("Country", GLOBAL_COUNTRIES, index=0)
    if chosen_country == "Other":
        country = st.text_input("Enter Country Name", value="India")
    else:
        country = chosen_country
        
    # 2. City Selection
    avail_cities = COUNTRY_CITIES.get(chosen_country, ["Custom City"]) + ["Custom City..."]
    city_choice = st.selectbox("City", avail_cities, index=0)
    if city_choice == "Custom City..." or chosen_country == "Other":
        city = st.text_input("Enter City Name", value="Hyderabad")
    else:
        city = city_choice
        
    # 3. Business Type
    bt_choice = st.selectbox("Business Type", BUSINESS_TYPES, index=0)
    if bt_choice == "Custom":
        business_type = st.text_input("Enter Custom Business Type", value="transport")
    else:
        business_type = bt_choice
        
    # 4. Target Roles
    selected_roles = st.multiselect("Target Roles (LinkedIn Snippets)", DEFAULT_ROLES, default=["Director", "CEO", "Owner"])
    custom_role = st.text_input("Add Custom Role (Optional)", value="")
    if custom_role.strip():
        selected_roles.append(custom_role.strip())
    primary_role = selected_roles[0] if selected_roles else "Director"

    st.markdown("---")
    st.subheader("⚙️ Execution & Limits")
    max_results = st.slider("Max Results Limit", min_value=2, max_value=50, value=10)
    crawl_delay = st.slider("Crawl Delay (seconds)", min_value=0.2, max_value=2.0, value=0.5, step=0.1)
    
    # 5. Debug Mode Checkbox
    debug_mode = st.checkbox("🐞 Debug Mode (Show raw HTTP responses)", value=True)
    
    # Optional Fallback API Keys
    with st.expander("🔑 Fallback Search API Keys (Optional)"):
        st.caption("Used if free ddgs search is rate-limited.")
        brave_key = st.text_input("Brave Search API Key", type="password")
        serper_key = st.text_input("Serper.dev API Key", type="password")

    st.markdown("---")
    start_btn = st.button("🚀 Launch Global Lead Search", use_container_width=True)


def display_debug_card(step_name: str, logs: Any):
    """Renders HTTP status, errors, and first 200 characters of response."""
    with st.expander(f"🔍 Debug Log: {step_name}", expanded=False):
        if isinstance(logs, list):
            for i, l in enumerate(logs):
                st.markdown(f"**Item {i+1}:** `{l.get('mirror') or l.get('url') or l.get('engine_used')}`")
                st.write(f"- **HTTP Status:** `{l.get('status')}`")
                if l.get('error'):
                    st.error(f"- **Error Message:** {l.get('error')}")
                st.code(f"First 200 chars:\n{l.get('response_sample', '')[:200]}", language="text")
        elif isinstance(logs, dict):
            st.write(f"- **Query / URL:** `{logs.get('query') or logs.get('url')}`")
            st.write(f"- **HTTP Status:** `{logs.get('status')}`")
            if logs.get('error'):
                st.error(f"- **Error Message:** {logs.get('error')}")
            st.code(f"First 200 chars:\n{logs.get('response_sample', '')[:200]}", language="text")


# Main Process
if start_btn:
    if not city.strip() or not business_type.strip():
        st.error("Please enter a valid City and Business Type.")
    else:
        st.info(f"Initiating search for **{business_type}** in **{city}, {country}**...")
        
        all_companies = []
        
        # --- STEP 1: OpenStreetMap Nominatim + Overpass Mirrors ---
        st.subheader("Step 1: OpenStreetMap Discovery")
        with st.spinner("Geocoding city with Nominatim and querying Overpass mirrors..."):
            bbox, geo_debug = geocode_city_nominatim(city, country)
            if debug_mode:
                display_debug_card("Nominatim Geocoding", geo_debug)
                
            osm_leads = []
            if bbox:
                osm_leads, osm_debug = query_overpass_mirrors(bbox, business_type, city, country)
                if debug_mode:
                    display_debug_card("Overpass Mirrors Query", osm_debug)
            else:
                st.warning(f"Could not determine bounding box for {city}. Overpass query skipped.")

        st.write(f"📍 **OpenStreetMap Result:** Found **{len(osm_leads)}** businesses.")
        all_companies.extend(osm_leads)
        
        # --- STEP 2: Web Search via ddgs with Fallback ---
        st.subheader("Step 2: DDGS Web Company Search")
        with st.spinner("Executing DDGS search for active company websites..."):
            web_leads, web_debug = search_web_companies(
                business_type=business_type,
                city=city,
                country=country,
                max_results=max_results,
                brave_api_key=brave_key,
                serper_api_key=serper_key
            )
            if debug_mode:
                display_debug_card("Web Search (DDGS)", web_debug)
                
        st.write(f"🌐 **Web Search Result:** Found **{len(web_leads)}** candidate company websites.")
        all_companies.extend(web_leads)
        
        # Deduplication
        unique_targets = []
        seen_keys = set()
        for c in all_companies:
            site_key = urllib.parse.urlparse(c.get("website", "")).netloc.lower() if c.get("website") else ""
            name_key = c["name"].strip().lower()
            key = site_key if site_key else name_key
            if key not in seen_keys:
                seen_keys.add(key)
                unique_targets.append(c)
                
        st.success(f"Aggregated **{len(unique_targets)}** unique companies across public sources.")
        
        if not unique_targets:
            st.error("Both Step 1 and Step 2 returned 0 leads. Inspect the Debug Logs above to view exact HTTP status codes and responses.")
        else:
            # Process up to max_results
            targets_to_crawl = unique_targets[:max_results]
            
            progress = st.progress(0)
            status_placeholder = st.empty()
            final_rows = []
            
            for idx, item in enumerate(targets_to_crawl):
                comp_name = item["name"]
                site_url = item.get("website", "")
                status_placeholder.text(f"Processing ({idx+1}/{len(targets_to_crawl)}): {comp_name}...")
                
                # --- Step 5: Website Crawler ---
                crawl_res = {"emails": [], "phones": [], "socials": [], "pages_visited": []}
                if site_url:
                    crawl_res, crawl_debug = crawl_company_website(site_url, delay=crawl_delay)
                    if debug_mode and crawl_debug:
                        # Show first page debug for brevity
                        display_debug_card(f"Website Crawl: {comp_name}", crawl_debug[0])
                elif item.get("initial_email"):
                    crawl_res["emails"].append(item["initial_email"])
                    
                combined_phone = item.get("phone") or (crawl_res["phones"][0] if crawl_res["phones"] else "")
                
                # --- Step 6: Decision Makers Search ---
                decision_maker_name = ""
                decision_maker_role = ""
                linkedin_url = ""
                
                dm_res, dm_debug = search_decision_maker_linkedin(role=primary_role, company=comp_name, city=city)
                if dm_res:
                    decision_maker_name = dm_res["person_name"]
                    decision_maker_role = dm_res["person_role"]
                    linkedin_url = dm_res["linkedin_url"]
                    
                if debug_mode and dm_debug:
                    display_debug_card(f"LinkedIn Search: {comp_name}", dm_debug)
                    
                # --- Step 7: Email Guessing + MX Validation ---
                email_records = generate_and_verify_emails(
                    person_name=decision_maker_name,
                    domain_or_url=site_url,
                    found_on_site=crawl_res["emails"]
                )
                
                # Pick top primary email & status, or format full lists
                primary_email = email_records[0]["email"] if email_records else ""
                primary_email_status = email_records[0]["status"] if email_records else "None"
                all_emails_str = ", ".join([f"{e['email']} ({e['status']})" for e in email_records[:3]])
                
                final_rows.append({
                    "Company": comp_name,
                    "Business type": item.get("business_type", business_type),
                    "City": city,
                    "Country": country,
                    "Website": site_url,
                    "Phone": combined_phone,
                    "Email": primary_email or all_emails_str,
                    "Email status": primary_email_status,
                    "Decision maker": decision_maker_name,
                    "Role": decision_maker_role,
                    "LinkedIn URL": linkedin_url
                })
                
                progress.progress((idx + 1) / len(targets_to_crawl))
                
            status_placeholder.text("Lead discovery and enrichment complete!")
            st.session_state["apollo_leads_df"] = pd.DataFrame(final_rows)

# Step 8: Output Table, CSV Download & Push to Google Sheet
if "apollo_leads_df" in st.session_state and not st.session_state["apollo_leads_df"].empty:
    leads_df: pd.DataFrame = st.session_state["apollo_leads_df"]
    
    st.markdown("---")
    st.subheader(f"📊 Qualified Leads ({len(leads_df)} Companies)")
    st.dataframe(leads_df, use_container_width=True)
    
    col1, col2 = st.columns([1, 1])
    with col1:
        csv_bytes = leads_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Leads as CSV",
            data=csv_bytes,
            file_name=f"apollo_leads_{city.lower()}_{business_type.lower()}.csv",
            mime="text/csv",
            use_container_width=True
        )
    with col2:
        if st.button("☁️ Push to Google Sheet (Placeholder)", use_container_width=True):
            push_to_google_sheet(leads_df)
            st.success("Called `push_to_google_sheet()` with the current table data.")
