# app.py
# Single-file Upload Form Crawler (Streamlit)

import streamlit as st
import asyncio
import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, urldefrag
from collections import deque
import pandas as pd
import json

st.set_page_config(
    page_title="Upload Form Crawler",
    page_icon="🔍",
    layout="wide"
)

st.title("🔍 File Upload Form Crawler")
st.caption("Public website se saari file upload forms automatically dhoondhta hai")

# ====================== SIDEBAR ======================
with st.sidebar:
    st.header("⚙️ Settings")
    start_url = st.text_input("Website URL", value="https://pesquisa-eaesp.fgv.br/")
    max_pages = st.slider("Max Pages to Crawl", 20, 600, 200)
    delay = st.slider("Delay between requests (sec)", 0.4, 1.5, 0.7)
    st.markdown("---")
    st.info("Sirf public pages crawl hote hain. Login wale pages skip ho jate hain.")

# ====================== STATE ======================
if "results" not in st.session_state:
    st.session_state.results = []
if "crawled" not in st.session_state:
    st.session_state.crawled = 0
if "forms_inspected" not in st.session_state:
    st.session_state.forms_inspected = 0

# ====================== HELPERS ======================
FILE_INPUT_SELECTORS = [
    'input[type="file"]',
    'input[name*="file"]',
    'input[id*="file"]',
    '.form-managed-file input',
    '.webform-managed-file input',
    '[data-drupal-selector*="file"]',
    '.dropzone',
    '.file-upload',
]

INTERESTING = [
    "apply", "application", "submit", "submission", "upload", "webform",
    "contact", "career", "jobs", "internship", "scholarship", "admission",
    "event", "registration", "forms", "faculty", "student", "award", "grant"
]

def normalize(url: str, domain: str) -> str:
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    if domain not in parsed.netloc:
        return ""
    return parsed._replace(query="", fragment="").geturl().rstrip("/")

def extract_links(soup, base: str, domain: str):
    links = set()
    for a in soup.find_all("a", href=True):
        full = normalize(urljoin(base, a["href"]), domain)
        if full:
            links.add(full)
    return links

def detect_upload_fields(soup, page_url: str):
    found = []
    forms = soup.find_all("form")
    st.session_state.forms_inspected += len(forms)

    for form in forms:
        file_inputs = []
        for sel in FILE_INPUT_SELECTORS:
            file_inputs.extend(form.select(sel))

        if not file_inputs:
            continue

        form_name = (
            form.get("id")
            or form.get("name")
            or form.get("action")
            or "Unnamed form"
        )

        fields = []
        for inp in file_inputs:
            label = "Not visible"
            if inp.get("id"):
                lab = soup.find("label", {"for": inp["id"]})
                if lab:
                    label = lab.get_text(strip=True)
            if label == "Not visible" and inp.get("aria-label"):
                label = inp["aria-label"]

            accept = inp.get("accept", "Not visible")
            multiple = "multiple" in inp.attrs

            fields.append({
                "label": label,
                "name": inp.get("name", "Not visible"),
                "id": inp.get("id", "Not visible"),
                "accept": accept,
                "multiple": multiple,
                "html_snippet": str(inp)[:320]
            })

        if fields:
            found.append({
                "page_url": page_url,
                "form_name": form_name,
                "login_required": "Possibly" if "login" in page_url.lower() else "No",
                "accepted_extensions": fields[0]["accept"],
                "pdf_supported": "Yes" if "pdf" in str(fields[0]["accept"]).lower() or fields[0]["accept"] == "Not visible" else "Unknown",
                "multiple_files": any(f["multiple"] for f in fields),
                "max_file_size": "Not visible",
                "field_label": fields[0]["label"],
                "field_name": fields[0]["name"],
                "field_id": fields[0]["id"],
                "evidence": fields[0]["html_snippet"]
            })
    return found

# ====================== CRAWLER ======================
async def crawl(start_url: str, max_pages: int, delay: float, progress_bar, status_text):
    domain = urlparse(start_url).netloc
    visited = set()
    to_visit = deque([start_url])
    results = []

    async with httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (compatible; UploadFormCrawler/1.0)"},
        timeout=20.0,
        follow_redirects=True
    ) as client:

        while to_visit and len(visited) < max_pages:
            url = to_visit.popleft()
            if url in visited:
                continue

            visited.add(url)
            st.session_state.crawled = len(visited)
            status_text.text(f"Crawling ({len(visited)}/{max_pages}): {url[:90]}...")
            progress_bar.progress(min(len(visited) / max_pages, 1.0))

            try:
                r = await client.get(url)
                if r.status_code >= 400:
                    continue

                soup = BeautifulSoup(r.text, "html.parser")

                forms = detect_upload_fields(soup, url)
                if forms:
                    results.extend(forms)

                new_links = extract_links(soup, url, domain)
                for link in new_links:
                    if link not in visited:
                        if any(p in link.lower() for p in INTERESTING):
                            to_visit.appendleft(link)
                        else:
                            to_visit.append(link)
            except Exception:
                pass

            await asyncio.sleep(delay)

    return results

# ====================== UI ======================
col1, col2 = st.columns([1, 3])

with col1:
    start_btn = st.button("🚀 Start Crawling", type="primary", use_container_width=True)

if start_btn:
    st.session_state.results = []
    st.session_state.crawled = 0
    st.session_state.forms_inspected = 0

    progress_bar = st.progress(0)
    status_text = st.empty()

    with st.spinner("Crawling shuru ho raha hai..."):
        results = asyncio.run(crawl(start_url, max_pages, delay, progress_bar, status_text))
        st.session_state.results = results

    st.rerun()

# ====================== RESULTS ======================
if st.session_state.results:
    st.success(
        f"✅ **{len(st.session_state.results)}** Upload Forms mili | "
        f"{st.session_state.crawled} pages crawl hue"
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Upload Forms", len(st.session_state.results))
    c2.metric("Pages Crawled", st.session_state.crawled)
    c3.metric("Forms Inspected", st.session_state.forms_inspected)

    df = pd.DataFrame(st.session_state.results)

    st.dataframe(
        df[[
            "page_url", "form_name", "field_label",
            "accepted_extensions", "pdf_supported",
            "multiple_files", "login_required"
        ]],
        use_container_width=True,
        height=400
    )

    st.markdown("### 🔎 Detailed View")
    idx = st.selectbox(
        "Form select karo",
        options=range(len(st.session_state.results)),
        format_func=lambda i: f"{st.session_state.results[i]['page_url']}  →  {st.session_state.results[i]['form_name']}"
    )
    st.json(st.session_state.results[idx])

    st.download_button(
        label="⬇️ Download Full JSON Report",
        data=json.dumps(st.session_state.results, indent=2, ensure_ascii=False),
        file_name="upload_forms_report.json",
        mime="application/json"
    )

else:
    st.info("👈 Left side se URL daalo aur **Start Crawling** button dabao")
