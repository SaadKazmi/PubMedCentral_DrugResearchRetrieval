import streamlit as st
import os
import requests
import urllib.request
import xml.etree.ElementTree as ET
import gzip
import shutil
import tarfile
import time
from datetime import datetime
import base64

# ----------------------------
# PDF VALIDATION
# ----------------------------
def is_valid_pdf(file_path):
    try:
        if not os.path.exists(file_path):
            return False
        if os.path.getsize(file_path) < 5000:
            return False
        with open(file_path, "rb") as f:
            header = f.read(5)
            f.seek(-10, 2)
            footer = f.read(10)
        return header == b"%PDF-" and b"%%EOF" in footer
    except:
        return False

# ----------------------------
# PMC SEARCH
# ----------------------------
def search_pmc_articles(query, max_results=50):
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {
        "db": "pmc",
        "term": query,
        "retmode": "json",
        "retmax": max_results,
        "sort": "relevance"
    }
    response = requests.get(url, params=params, timeout=15)
    data = response.json()
    pmc_ids = data.get("esearchresult", {}).get("idlist", [])
    links = [f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{id}/" for id in pmc_ids]
    return pmc_ids, links

# ----------------------------
# GET PDF LINK FROM PMC
# ----------------------------
def get_pdf_link_from_pmcid(pmcid):
    api_url = f"https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id=PMC{pmcid}"
    try:
        r = requests.get(api_url, timeout=10)
        root = ET.fromstring(r.text)
        for link in root.findall(".//link"):
            if link.attrib.get("format") == "pdf":
                return link.attrib["href"]
    except:
        return None

# ----------------------------
# DOWNLOAD PDF
# ----------------------------
def download_stream(url, destination, timeout=20):
    if url.startswith("ftp://"):
        with urllib.request.urlopen(url, timeout=timeout) as response, open(destination, "wb") as out:
            shutil.copyfileobj(response, out)
    else:
        headers = {"User-Agent": "Mozilla/5.0"}
        with requests.get(url, stream=True, timeout=timeout, headers=headers) as r:
            r.raise_for_status()
            with open(destination, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

def extract_pdf_from_tar_gz(tar_path, output_path):
    try:
        with tarfile.open(tar_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith(".pdf"):
                    tar.extract(member, path=".")
                    os.rename(member.name, output_path)
                    return True
    except:
        return False

def safe_gunzip(data):
    try:
        return gzip.decompress(data)
    except:
        return None

def download_pdf(pdf_url, save_path, retries=3):
    for attempt in range(1, retries+1):
        temp_file = save_path + ".tmp"
        try:
            download_stream(pdf_url, temp_file)
            with open(temp_file, "rb") as f:
                raw = f.read()

            if pdf_url.endswith(".tar.gz") or raw[:2] == b"\x1f\x8b":
                if pdf_url.endswith(".tar.gz") and extract_pdf_from_tar_gz(temp_file, save_path):
                    os.remove(temp_file)
                    if is_valid_pdf(save_path):
                        return True
                elif raw[:2] == b"\x1f\x8b":
                    decompressed = safe_gunzip(raw)
                    if decompressed:
                        raw = decompressed
                    else:
                        if os.path.exists(temp_file):
                            os.remove(temp_file)
                        return False

            with open(save_path, "wb") as f:
                f.write(raw)
            if os.path.exists(temp_file):
                os.remove(temp_file)
            if is_valid_pdf(save_path):
                return True
        except:
            if os.path.exists(temp_file):
                os.remove(temp_file)
        time.sleep(1)
    return False

# ----------------------------
# STREAMLIT UI
# ----------------------------
st.title("PMC Drug Repurposing PDF Retriever")

# Initialize session state
if "downloads_folder" not in st.session_state:
    downloads_folder = os.path.join("pmc_downloads", datetime.now().strftime("%Y%m%d_%H%M%S"))
    os.makedirs(downloads_folder, exist_ok=True)
    st.session_state.downloads_folder = downloads_folder
    st.session_state.downloaded_files = []

drug = st.text_input("Enter drug name:", "insulin")
max_links = st.number_input("Max links to check:", min_value=1, max_value=100, value=10)
max_pdfs = st.number_input("Max PDFs to download:", min_value=1, max_value=10, value=3)
start = st.button("Search and Download")

if start and drug.strip():
    st.session_state.downloaded_files = []
    full_query = f"{drug} repurposing"
    output_folder = os.path.join(st.session_state.downloads_folder, full_query.replace(" ", "_"))
    os.makedirs(output_folder, exist_ok=True)

    st.info(f"Searching PMC for '{full_query}'...")
    pmc_ids, article_links = search_pmc_articles(full_query, max_results=max_links)
    st.write("Found PMC articles:", article_links)

    download_count = 0
    progress_text = st.empty()
    for i, pmcid in enumerate(pmc_ids):
        if download_count >= max_pdfs:
            break
        pdf_url = get_pdf_link_from_pmcid(pmcid)
        if not pdf_url:
            continue
        save_path = os.path.join(output_folder, f"{drug}_repurposing_PMC{pmcid}.pdf")
        progress_text.text(f"Downloading PMC{pmcid}...")
        if download_pdf(pdf_url, save_path):
            download_count += 1
            st.session_state.downloaded_files.append(save_path)
            st.success(f"Downloaded: {save_path}")
        else:
            st.warning(f"Failed to download PMC{pmcid}")
    
    if download_count == 0:
        st.error("No valid PDFs downloaded.")
    else:
        st.success(f"Downloaded {download_count} PDFs to '{output_folder}'")

# Display downloaded PDFs in collapsible sections with embedded view
if st.session_state.downloaded_files:
    st.subheader("Downloaded PDFs")
    for pdf_path in st.session_state.downloaded_files:
        pdf_name = os.path.basename(pdf_path)
        with st.expander(f"📄 {pdf_name}"):
            st.write(f"**Path:** `{pdf_path}`")
            
            # Download button
            try:
                with open(pdf_path, "rb") as pdf_file:
                    st.download_button(
                        label="Download PDF",
                        data=pdf_file,
                        file_name=pdf_name,
                        mime="application/pdf"
                    )
            except:
                st.error(f"Could not read {pdf_name}")
            
            # Embed PDF in expander using Streamlit's built-in st.pdf
            try:
                with open(pdf_path, "rb") as f:
                    sanitized_key = pdf_path.replace("_", "-").replace("/", "-").replace("\\", "-")
                    st.pdf(f, height=600, key=sanitized_key)
            except Exception as e:
                st.error(f"Could not display {pdf_name}: {e}")

