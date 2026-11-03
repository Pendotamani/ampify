import time
import urllib.parse
import pandas as pd
import streamlit as st

from finder import query_overpass
from website_scraper import scrape_website_info, guess_emails, check_mx_record
from search import search_duckduckgo_websites, search_duckduckgo_linkedin


def push_to_google_sheet(df: pd.DataFrame) -> bool:
    """
    Placeholder function to connect and sync scraped leads to a Google Sheet.
    Later implementation can use gspread or Google Sheets API.
    """
    print(f"[Placeholder] push_to_google_sheet called with {len(df)} records.")
    return True


st.set_page_config(
    page_title="AI Lead Finder Agent",
    page_icon="🎯",
    layout="wide"
)

st.title("🎯 Local Business Lead Finder Agent")
st.markdown(
    """
    Multi-source lead generation agent without paid APIs:
    - **Step 1:** OpenStreetMap Bounding Box query (`amenity=taxi`, `office=logistics/transport`, `shop=travel_agency`, keyword regex).
    - **Step 2:** DuckDuckGo Web Search (`[keyword] [city] contact email`) to extract active business websites.
    - **Step 3:** Deep crawler extracting emails, phones, `/contact` & `/about` pages (respects `robots.txt`).
    - **Step 4:** Decision-maker search on LinkedIn via DuckDuckGo snippets.
    - **Step 5:** Email guessing & **Free MX record verification** (no SMTP connection).
    """
)

# Sidebar configurations
with st.sidebar:
    st.header("Search Parameters")
    city = st.text_input("City", value="Hyderabad")
    business_type = st.text_input("Business Type", value="transport")
    target_role = st.text_input("Target Decision Maker Role", value="Director", help="Used for LinkedIn snippet search")
    
    st.markdown("---")
    st.subheader("Crawl Settings")
    max_osm = st.slider("Max OSM Leads", min_value=0, max_value=25, value=10)
    max_ddg = st.slider("Max Web Search Leads", min_value=1, max_value=25, value=10)
    crawl_delay = st.slider("Crawl Delay (seconds)", min_value=0.2, max_value=2.0, value=0.5, step=0.1)
    enrich_linkedin = st.checkbox("Find LinkedIn Decision Makers", value=True)
    guess_emails_flag = st.checkbox("Guess & Verify Emails via MX", value=True)
    
    st.markdown("---")
    start_search = st.button("🚀 Find & Enrich Leads", use_container_width=True)

# Main Execution Flow
if start_search:
    if not city.strip() or not business_type.strip():
        st.error("Please provide both City and Business Type.")
    else:
        all_raw_leads = []
        
        # --- Step 1: OpenStreetMap Query ---
        osm_leads = []
        if max_osm > 0:
            with st.spinner(f"Step 1: Querying OpenStreetMap for '{business_type}' in {city} (bounding box & tags)..."):
                osm_leads = query_overpass(city, business_type)[:max_osm]
            st.info(f"📍 **Step 1 (OpenStreetMap):** Found **{len(osm_leads)}** businesses.")
            all_raw_leads.extend(osm_leads)
            
        # --- Step 2: DuckDuckGo Web Search ---
        ddg_leads = []
        if max_ddg > 0:
            with st.spinner(f"Step 2: Searching DuckDuckGo for '{business_type} {city} contact email'..."):
                ddg_leads = search_duckduckgo_websites(business_type, city, max_results=max_ddg)
            st.info(f"🌐 **Step 2 (DuckDuckGo Search):** Extracted **{len(ddg_leads)}** candidate company websites.")
            all_raw_leads.extend(ddg_leads)
            
        # Deduplicate initial leads by name or domain
        unique_leads = []
        seen_identifiers = set()
        for l in all_raw_leads:
            name_key = l["name"].strip().lower()
            site_key = urllib.parse.urlparse(l.get("website", "")).netloc.lower() if l.get("website") else ""
            key = site_key if site_key else name_key
            if key not in seen_identifiers:
                seen_identifiers.add(key)
                unique_leads.append(l)
                
        st.success(f"Combined **{len(unique_leads)}** unique business candidates across sources.")
        
        if not unique_leads:
            st.warning("No businesses found matching criteria. Try different keywords or check spelling.")
        else:
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            enriched_records = []
            
            for idx, lead in enumerate(unique_leads):
                status_text.text(f"Crawling & Enriching ({idx+1}/{len(unique_leads)}): {lead['name']}...")
                
                # --- Step 3: Website Deep Crawling ---
                site_url = lead.get("website", "")
                if site_url:
                    web_data = scrape_website_info(site_url, delay_sec=crawl_delay)
                else:
                    web_data = {"scraped_emails": lead.get("initial_email", ""), "scraped_phones": "", "contact_links": ""}
                
                # Combine phones
                all_phones = [p.strip() for p in [lead.get("phone", ""), web_data.get("scraped_phones", "")] if p.strip()]
                combined_phone = ", ".join(list(dict.fromkeys(all_phones)))
                
                # --- Step 4: LinkedIn Snippet Search ---
                linkedin_data = {}
                if enrich_linkedin:
                    time.sleep(crawl_delay)
                    linkedin_data = search_duckduckgo_linkedin(role=target_role, company=lead["name"]) or {}
                
                person_name = linkedin_data.get("person_name", "")
                
                # --- Step 5: Email Guessing + MX Verification ---
                guessed_list = []
                if guess_emails_flag and site_url:
                    guessed_list = guess_emails(person_name, site_url)
                
                record = {
                    "Company Name": lead["name"],
                    "Source": lead.get("source", "Web"),
                    "Category": lead.get("type", business_type),
                    "City": lead.get("city", city),
                    "Address": lead.get("address", ""),
                    "Website": site_url,
                    "Phone": combined_phone,
                    "Scraped Emails (MX Checked)": web_data.get("scraped_emails", ""),
                    "Guessed Emails (MX Checked)": ", ".join(guessed_list),
                    "Contact / About Pages": web_data.get("contact_links", ""),
                    "Decision Maker": person_name,
                    "Role": linkedin_data.get("person_role", ""),
                    "LinkedIn Profile": linkedin_data.get("linkedin_url", ""),
                    "Search Snippet": linkedin_data.get("search_snippet", "")
                }
                
                enriched_records.append(record)
                progress_bar.progress((idx + 1) / len(unique_leads))
                
            status_text.text(f"Enrichment complete! Processed {len(enriched_records)} leads.")
            st.session_state["leads_df"] = pd.DataFrame(enriched_records)

# Display Results & Export Options
if "leads_df" in st.session_state and not st.session_state["leads_df"].empty:
    df: pd.DataFrame = st.session_state["leads_df"]
    
    st.markdown("---")
    st.subheader(f"📊 Results Table ({len(df)} Leads)")
    st.dataframe(df, use_container_width=True)
    
    col1, col2 = st.columns([1, 1])
    
    with col1:
        csv_data = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Leads as CSV",
            data=csv_data,
            file_name=f"leads_{city.lower()}_{business_type.lower()}.csv",
            mime="text/csv",
            use_container_width=True
        )
        
    with col2:
        if st.button("☁️ Push to Google Sheet (Placeholder)", use_container_width=True):
            push_to_google_sheet(df)
            st.success("Successfully triggered `push_to_google_sheet()` with all current leads!")
