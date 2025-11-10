# app.py — Prospect Scraper (Streamlit) — polished UI for Sure Oak
import re, time
from io import StringIO
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup
import streamlit as st
from pathlib import Path
import os

# ========================
# Brand + Visual Settings
# ========================
APP_TITLE = "Sure Oak's Prospect Finder"
APP_TAGLINE = "Find guest-post & contributor targets fast(ish)"

BASE_DIR = Path(__file__).resolve().parent
LOGO_PATH = BASE_DIR / "assets" / "logo.png"

USER_AGENT = "ProspectScraper/0.6 (+contact: your-email@example.com)"
EMAIL_REGEX = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
CONTACT_KEYWORDS = [
    "contact", "contact us", "about", "editor", "pitch", "media",
    "press", "submit", "guidelines"
]

DEFAULT_EXCLUDES = (
    "facebook.com,pinterest.com,linkedin.com,instagram.com,twitter.com,"
    "t.co,youtube.com,medium.com,reddit.com,quora.com"
)
DEFAULT_INCLUDES = "guest post,write for us,submit an article,contribute"

# ===============
# Page & theming
# ===============
st.set_page_config(page_title=APP_TITLE, page_icon="🔎", layout="wide")

# Hide Streamlit default menu/footer for a cleaner, app-like feel
st.markdown(
    """
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .block-container {padding-top: 2rem; padding-bottom: 3rem;}
    </style>
    """,
    unsafe_allow_html=True,
)

# ===== Header (logo + title) =====
col_logo, col_title = st.columns([1, 5], vertical_alignment="center")
with col_logo:
    try:
        data = LOGO_PATH.read_bytes()
        try:
            # Newer Streamlit
            st.image(data, use_container_width=True)
        except TypeError:
            # Older Streamlit fallback
            st.image(data, use_column_width=True)
    except Exception:
        st.caption(" ")  # no logo yet

with col_title:
    st.title(f"🔎 {APP_TITLE}")
    st.caption(APP_TAGLINE)

# ===============
# Core utilities
# ===============

def extract_emails(text):
    return sorted({m.group(0) for m in EMAIL_REGEX.finditer(text)})

def extract_domain(url):
    try:
        netloc = urlparse(url).netloc.lower()
        parts = netloc.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else netloc
    except Exception:
        return ""

def domain_allowed(domain: str, allowed_tlds_only: bool) -> bool:
    if not domain:
        return False
    if allowed_tlds_only:
        return domain.endswith(".com") or domain.endswith(".org")
    return True

def serpapi_search(query, api_key, num=10, start=0):
    endpoint = "https://serpapi.com/search.json"
    r = requests.get(
        endpoint,
        params={
            "q": query,
            "engine": "google",
            "api_key": api_key,
            "num": max(1, min(int(num), 100)),
            "start": max(0, int(start)),
        },
        headers={"User-Agent": USER_AGENT},
        timeout=25,
    )
    r.raise_for_status()
    data = r.json()
    out = []
    for item in data.get("organic_results", []):
        out.append({
            "title": item.get("title", ""),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", ""),
        })
    return out

def fetch_html(url):
    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=20)
        if r.status_code >= 400:
            return ""
        return r.text
    except Exception:
        return ""

def extract_links(soup, base_url):
    links = []
    for a in soup.find_all("a", href=True):
        full = urljoin(base_url, a["href"])
        txt = (a.get_text() or "").strip().lower()
        links.append((txt, full))
    return links

def find_candidate_contact_links(links):
    seen, out = set(), []
    for txt, url in links:
        if any(kw in txt for kw in CONTACT_KEYWORDS):
            if url not in seen:
                out.append(url); seen.add(url)
    return out[:10]

def search_queries(niche):
    b = niche.strip()
    return [
        f'"write for us" {b}',
        f'"guest post" {b}',
        f'"contribute" {b}',
        f'"submit an article" {b}',
        f'"editorial guidelines" {b}',
    ]

def parse_csv_list(s: str):
    return [t.strip().lower() for t in s.split(",") if t.strip()]

def matches_include_keywords(rec, include_terms):
    if not include_terms:
        return True
    hay = " ".join([rec.get("title",""), rec.get("url",""), rec.get("snippet","")]).lower()
    return any(term in hay for term in include_terms)

# ===============
# Sidebar (minimal by default)
# ===============
with st.sidebar:
    st.subheader("Search setup")
    serp_key = st.text_input("SerpAPI key", type="password", help="Not stored; used only for this session.")
    niche = st.text_input("Niche / Topic", value="digital marketing")
    results_per_page = st.slider("Results per page", 10, 100, 20, 10)

    # Advanced stuff most users don't need every time
    with st.expander("Advanced options", expanded=False):
        pages = st.slider("Pages per query", 1, 5, 2, 1)
        delay = st.slider("Delay between requests (sec)", 0.0, 5.0, 1.0, 0.5)
        excludes_str = st.text_input("Exclude domains (CSV)", DEFAULT_EXCLUDES)
        only_com_org = st.checkbox("Only include .com or .org", value=True)
        include_str = st.text_input(
            "Include-only keywords (CSV)", DEFAULT_INCLUDES,
            help="Must match title, URL, or snippet."
        )
        max_per_domain = st.number_input(
            "Max results per domain", min_value=1, max_value=10, value=1, step=1
        )

    st.markdown("\n")
    run = st.button("Run search", use_container_width=True)

# Optional toggles in main area
show_snippets = st.checkbox("Show snippets", value=False)

# ===============
# Main workflow
# ===============
if run:
    if not serp_key:
        st.error("Please enter your SerpAPI key in the sidebar.")
        st.stop()
    if not niche.strip():
        st.error("Please enter a niche/topic.")
        st.stop()

    # Read advanced settings (with defaults if expander untouched)
    pages = locals().get("pages", 2)
    delay = locals().get("delay", 1.0)
    excludes_str = locals().get("excludes_str", DEFAULT_EXCLUDES)
    only_com_org = locals().get("only_com_org", True)
    include_str = locals().get("include_str", DEFAULT_INCLUDES)
    max_per_domain = locals().get("max_per_domain", 1)

    exclude_set = set(parse_csv_list(excludes_str))
    include_terms = parse_csv_list(include_str)

    progress = st.progress(0, text="Preparing search…")
    all_results = []
    queries = search_queries(niche)

    total_loops = len(queries) * pages
    loop_index = 0

    # Search
    for q in queries:
        for p in range(pages):
            start = p * results_per_page
            progress.progress(
                min(100, int((loop_index / max(1, total_loops)) * 30)),
                text=f"Searching {q} (page {p+1}/{pages})"
            )
            try:
                all_results += serpapi_search(q, serp_key, num=results_per_page, start=start)
            except Exception as e:
                st.warning(f"Search failed for '{q}' page {p+1}: {e}")
            loop_index += 1
            time.sleep(delay)

    # Dedupe URLs
    seen_urls, deduped = set(), []
    for r in all_results:
        url = r.get("url")
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped.append(r)

    # Filter
    filtered = []
    for r in deduped:
        d = extract_domain(r["url"]) or ""
        if not d:
            continue
        if exclude_set and any(ex in d for ex in exclude_set):
            continue
        if not domain_allowed(d, only_com_org):
            continue
        if not matches_include_keywords(r, include_terms):
            continue
        filtered.append(r)

    # Cap per-domain
    domain_counts = {}
    per_domain = []
    for r in filtered:
        d = extract_domain(r["url"]) or ""
        c = domain_counts.get(d, 0)
        if c < max_per_domain:
            per_domain.append(r)
            domain_counts[d] = c + 1

    # Visit pages and extract signals
    rows = []
    total = len(per_domain)
    for i, item in enumerate(per_domain, 1):
        url = item["url"]
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        progress.progress(
            min(100, 30 + int(i / max(1, total) * 70)),
            text=f"Visiting {i}/{total}"
        )
        html = fetch_html(url)
        emails = extract_emails(html) if html else []
        contacts = []
        if html:
            soup = BeautifulSoup(html, "html.parser")
            contacts = find_candidate_contact_links(extract_links(soup, url))
        rows.append({
            "domain": extract_domain(url),
            "url": url,
            "title": title,
            "snippet": snippet,
            "emails": ";".join(emails[:5]),
            "contact_links": ";".join(contacts),
        })
        time.sleep(delay)

    progress.empty()

    # Results table
    if not rows:
        st.info("No results after filtering. Try widening your filters in Advanced options.")
    else:
        st.success(f"Done! Collected {len(rows)} prospects after filtering & pagination.")

        # Choose visible columns to keep UI uncluttered
        base_cols = ["domain", "url", "emails", "contact_links"]
        if show_snippets:
            base_cols += ["title", "snippet"]

        # Convert to DataFrame implicitly via st.dataframe(list_of_dicts)
        st.dataframe(
            [{k: r.get(k, "") for k in base_cols} for r in rows],
            use_container_width=True,
            hide_index=True,
        )

        # CSV download
        import csv
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=["domain","url","title","snippet","emails","contact_links"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
        try:
            st.download_button(
                "Download CSV",
                output.getvalue().encode("utf-8"),
                file_name="prospects.csv",
                mime="text/csv",
                use_container_width=True,
            )
        except TypeError:
            # Older Streamlit
            st.download_button(
                "Download CSV",
                output.getvalue().encode("utf-8"),
                file_name="prospects.csv",
                mime="text/csv",
            )
