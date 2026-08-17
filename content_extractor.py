import os
import sys
import re
import json
import requests
import trafilatura
from bs4 import BeautifulSoup
import yt_dlp
import pypdf
from ddgs import DDGS

# Force UTF-8 encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

class ContentExtractor:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })

    def extract_url(self, url):
        """Extracts text, metadata, social preview, video details, or search snippets from any URL."""
        url = url.strip()
        print(f"[ContentExtractor] Extracting URL: {url}", flush=True)

        clean_url = url.split("?")[0]

        # 1. Instagram / Threads / YouTube / TikTok / Facebook via yt-dlp
        is_video_site = any(d in url.lower() for d in ["instagram.com", "threads.net", "youtube.com", "youtu.be", "tiktok.com", "facebook.com/watch"])
        if is_video_site:
            try:
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'skip_download': True,
                    'extract_flat': False
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        title = info.get('title') or ''
                        description = info.get('description') or ''
                        uploader = info.get('uploader') or info.get('channel') or ''
                        duration = info.get('duration') or 0
                        out = []
                        if uploader: out.append(f"**Akun / Pengunggah:** {uploader}")
                        if title and title != "Video by " + str(uploader): out.append(f"**Judul:** {title}")
                        if duration: out.append(f"**Durasi:** {duration} detik")
                        if description: out.append(f"**Deskripsi / Caption:**\n{description[:1500]}")
                        if out:
                            return "\n".join(out)
            except Exception as e:
                print(f"[yt-dlp extract error] {e}", flush=True)

        # 2. Articles & Web Blogs via Trafilatura
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                text = trafilatura.extract(downloaded, include_comments=False, include_tables=True, output_format='txt')
                if text and len(text.strip()) > 80:
                    return f"**Konten Web / Artikel:**\n{text[:3500]}"
        except Exception:
            pass

        # 3. OpenGraph HTML Meta Tags
        try:
            resp = self.session.get(url, timeout=7)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                og_title = soup.find("meta", property="og:title") or soup.find("title")
                og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
                
                title_val = og_title.get("content", og_title.text if hasattr(og_title, "text") else "") if og_title else ""
                desc_val = og_desc.get("content", "") if og_desc else ""
                
                # Check if it is a generic login barrier
                if title_val and "login" not in title_val.lower() and "sign in" not in title_val.lower() and len(title_val.strip()) > 5:
                    out = [f"**Judul Halaman:** {title_val.strip()}"]
                    if desc_val: out.append(f"**Ringkasan:** {desc_val.strip()}")
                    return "\n".join(out)
        except Exception:
            pass

        # 4. Search Engine Snippet Fallback
        try:
            clean_host = clean_url.replace('https://', '').replace('http://', '').replace('www.', '')
            query = f"site:{clean_host}" if "/" in clean_host else clean_host
            results = list(DDGS().text(query, max_results=2))
            if results:
                for r in results:
                    b = r.get("body", "").strip()
                    if b and len(b) > 40 and "log in" not in b.lower() and "sign up" not in b.lower():
                        return f"**Snippet Penelusuran Web:**\n{b}"
        except Exception:
            pass

        # Explicit failure signal so AI NEVER hallucinates
        return f"[STATUS: TIDAK DAPAT DIAKSES] Tautan '{url}' dilindungi oleh sistem privasi/autentikasi atau akun bersifat privat sehingga konten spesifiknya tidak dapat diekstrak otomatis. AI WAJIB menyampaikan ini dengan jujur dan meminta Master menyalin teks atau mengirim tangkapan layar (screenshot)."

    def extract_pdf(self, file_path, max_pages=30):
        if not os.path.exists(file_path):
            return "Error: Berkas PDF tidak ditemukan."
        try:
            reader = pypdf.PdfReader(file_path)
            total_pages = len(reader.pages)
            pages_to_read = min(total_pages, max_pages)
            extracted_text = []
            for i in range(pages_to_read):
                text = reader.pages[i].extract_text()
                if text:
                    extracted_text.append(f"--- [Halaman {i+1}] ---\n{text.strip()}")
            full_text = "\n\n".join(extracted_text)
            summary_header = f"**Dokumen PDF:** {os.path.basename(file_path)} (Total {total_pages} Halaman)\n\n"
            return summary_header + (full_text[:8000] if len(full_text) > 8000 else full_text)
        except Exception as e:
            return f"Error membaca berkas PDF: {e}"

extractor = ContentExtractor()

if __name__ == "__main__":
    test_url = "https://www.instagram.com/reel/DcHSo17RmDW/?igsh=d3JqdnNzNDVjOTVq"
    print(extractor.extract_url(test_url))
