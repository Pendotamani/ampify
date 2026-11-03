import time
import pandas as pd
import streamlit as st

from finder import query_overpass
from website_scraper import scrape_website_info
from search import search_duckduckgo_linkedin


def push_to_google_sheet(df: pd.DataFrame) -> bool:
    """
    Placeholder function to connect and sync scraped leads to a Google Sheet.
    Later implementation can use gspread or Google Sheets API.
    """
    # Example placeholder logic:
    # gc = gspread.service_account(filename='credentials.json')
    # sh = gc.open("My Leads Sheet")
    # sh.sheet1.update([df.columns.values.tolist()] + df.values.tolist())
    print(f"[Placeholder] push_to_google_sheet called with {len(df)} records.")
    return True


st.set_page_config(
    page_title="Lead Finder Agent",
    page_icon="🎯",
    layout="wide"
)

st.title("🎯 Local Business Lead Finder Agent")
st.markdown(
    """
    Find local business leads via **OpenStreetMap (Overpass API)**, scrape company contact details & pages (respecting `robots.txt`), 
    and identify decision-makers on LinkedIn via **DuckDuckGo search snippets** — **100% free, no paid APIs**.
    """
)

# Sidebar configurations
with st.sidebar:
    st.header("Search Parameters")
    city = st.text_input("City", value="Hyderabad")
    business_type = st.text_input("Business Type", value="transport")
    target_role = st.text_input("Target Decision Maker Role", value="Director", help="Used for LinkedIn snippet search")
    
    st.markdown("---")
    st.subheader("Crawling Options")
    max_results = st.slider("Max Overpass Leads to Process", min_value=1, max_value=50, value=10)
    crawl_delay = st.slider("Crawl Delay (seconds)", min_value=0.5, max_value=3.0, value=1.0, step=0.5)
    enrich_linkedin = st.checkbox("Find LinkedIn Profiles (DuckDuckGo)", value=True)
    
    st.markdown("---")
    start_search = st.button("🚀 Find & Enrich Leads", use_container_width=True)

# Main Execution Flow
if start_search:
    if not city.strip() or not business_type.strip():
        st.error("Please provide both City and Business Type.")
    else:
        st.info(f"Step 1: Querying OpenStreetMap Overpass API for **{business_type}** in **{city}**...")
        
        with st.spinner("Fetching listings from OpenStreetMap..."):
            raw_leads = query_overpass(city, business_type)
            
        if not raw_leads:
            st.warning("No businesses found matching criteria. Try broader keywords (e.g. 'transport', 'agency', 'logistics').")
        else:
            st.success(f"Found {len(raw_leads)} initial businesses from OpenStreetMap.")
            
            # Limit results according to user setting
            leads_to_process = raw_leads[:max_results]
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            enriched_records = []
            seen_entries = set()
            
            for idx, lead in enumerate(leads_to_process):
                status_text.text(f"Processing ({idx+1}/{len(leads_to_process)}): {lead['name']}...")
                
                # Step 2: Website scraping
                site_url = lead.get("website", "")
                if site_url:
                    web_data = scrape_website_info(site_url, delay_sec=crawl_delay)
                else:
                    web_data = {"scraped_emails": "", "scraped_phones": "", "contact_links": ""}
                
                # Combine phones
                all_phones = filter(None, [lead.get("phone", ""), web_data.get("scraped_phones", "")])
                combined_phone = ", ".join(list(dict.fromkeys(", ".join(all_phones).split(", "))))
                
                # Step 3: DuckDuckGo LinkedIn Snippet Search
                linkedin_data = {}
                if enrich_linkedin:
                    time.sleep(crawl_delay)  # Respectful pause for search engine
                    linkedin_data = search_duckduckgo_linkedin(role=target_role, company=lead["name"]) or {}
                
                record = {
                    "Company Name": lead["name"],
                    "Category": lead.get("type", business_type),
                    "City": lead.get("city", city),
                    "Address": lead.get("address", ""),
                    "Website": site_url,
                    "Phone": combined_phone,
                    "Email": web_data.get("scraped_emails", ""),
                    "Contact / About Pages": web_data.get("contact_links", ""),
                    "LinkedIn Person": linkedin_data.get("person_name", ""),
                    "LinkedIn Role": linkedin_data.get("person_role", ""),
                    "LinkedIn Profile": linkedin_data.get("linkedin_url", ""),
                    "Search Snippet": linkedin_data.get("search_snippet", "")
                }
                
                # Step 4: Remove Duplicates (key: (Company Name, Address/Website))
                dup_key = (record["Company Name"].strip().lower(), record["Website"].strip().lower())
                if dup_key not in seen_entries:
                    seen_entries.add(dup_key)
                    enriched_records.append(record)
                    
                progress_bar.progress((idx + 1) / len(leads_to_process))
                
            status_text.text("Processing complete!")
            st.session_state["leads_df"] = pd.DataFrame(enriched_records)

# Display Results & Export Options
if "leads_df" in st.session_state and not st.session_state["leads_df"].empty:
    df: pd.DataFrame = st.session_state["leads_df"]
    
    st.subheader(f"📊 Results ({len(df)} Unique Leads)")
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
            success = push_to_google_sheet(df)
            if success:
                st.success("Called placeholder function `push_to_google_sheet()`! Connect your credentials to sync live.")
