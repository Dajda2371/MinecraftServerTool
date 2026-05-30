import urllib.parse
import requests
from html.parser import HTMLParser

def clean_installer_url(url):
    parsed = urllib.parse.urlparse(url)
    query = urllib.parse.parse_qs(parsed.query)
    if "url" in query:
        return query["url"][0]
    return url

class ForgeHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_downloads = False
        self.in_download = False
        self.in_title = False
        self.in_links = False
        
        self.current_download_type = None  # 'latest' or 'recommended'
        self.current_download_version = None
        self.current_download_url = None
        
        # Results from top box (downloads)
        self.latest = None
        self.recommended = None
        
        # Table parsing
        self.in_table = False
        self.in_tbody = False
        self.in_tr = False
        self.in_version_td = False
        self.in_files_td = False
        
        self.current_table_version = None
        self.current_table_url = None
        self.current_table_is_latest = False
        self.current_table_is_recommended = False
        
        # List of all versions in the table
        self.versions = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        tag = tag.lower()
        
        # Check for top downloads div
        if tag == "div" and attrs_dict.get("class") == "downloads":
            self.in_downloads = True
            
        elif self.in_downloads and tag == "div" and attrs_dict.get("class") == "download":
            self.in_download = True
            self.current_download_type = None
            self.current_download_version = None
            self.current_download_url = None
            
        elif self.in_download and tag == "div" and attrs_dict.get("class") == "title":
            self.in_title = True
            
        elif self.in_download and tag == "div" and attrs_dict.get("class") == "links":
            self.in_links = True
            
        elif self.in_links and tag == "a":
            title = attrs_dict.get("title", "").lower()
            href = attrs_dict.get("href", "")
            if "installer" in title or "installer" in href.lower():
                self.current_download_url = clean_installer_url(href)
                
        # Check for table
        elif tag == "table" and "download-list" in attrs_dict.get("class", ""):
            self.in_table = True
            
        elif self.in_table and tag == "tbody":
            self.in_tbody = True
            
        elif self.in_tbody and tag == "tr":
            self.in_tr = True
            self.current_table_version = None
            self.current_table_url = None
            self.current_table_is_latest = False
            self.current_table_is_recommended = False
            
        elif self.in_tr and tag == "td":
            td_class = attrs_dict.get("class", "")
            if "download-version" in td_class:
                self.in_version_td = True
            elif "download-files" in td_class:
                self.in_files_td = True
                
        elif self.in_version_td and tag == "i":
            i_class = attrs_dict.get("class", "")
            if "promo-latest" in i_class:
                self.current_table_is_latest = True
            elif "promo-recommended" in i_class:
                self.current_table_is_recommended = True
                
        elif self.in_files_td and tag == "a":
            href = attrs_dict.get("href", "")
            if "installer" in href.lower():
                self.current_table_url = clean_installer_url(href)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "div":
            if self.in_title:
                self.in_title = False
            elif self.in_links:
                self.in_links = False
            elif self.in_download:
                self.in_download = False
                res = {
                    "version": self.current_download_version,
                    "url": self.current_download_url
                }
                if self.current_download_type == "latest":
                    self.latest = res
                elif self.current_download_type == "recommended":
                    self.recommended = res
            elif self.in_downloads:
                self.in_downloads = False
                
        elif tag == "table":
            self.in_table = False
        elif tag == "tbody":
            self.in_tbody = False
        elif tag == "tr":
            if self.in_tr:
                self.in_tr = False
                if self.current_table_version and self.current_table_url:
                    self.versions.append({
                        "version": self.current_table_version,
                        "url": self.current_table_url,
                        "is_latest": self.current_table_is_latest,
                        "is_recommended": self.current_table_is_recommended
                    })
        elif tag == "td":
            if self.in_version_td:
                self.in_version_td = False
            elif self.in_files_td:
                self.in_files_td = False

    def handle_data(self, data):
        data_clean = data.strip()
        if not data_clean:
            return
            
        if self.in_title:
            if "Download Latest" in data:
                self.current_download_type = "latest"
            elif "Download Recommended" in data:
                self.current_download_type = "recommended"
            if "-" in data_clean:
                parts = data_clean.split("-")
                if len(parts) >= 2:
                    # Minecraft version prefix could be present: e.g. "1.20.1 - 47.4.20" -> "47.4.20"
                    self.current_download_version = parts[1].strip()
                    
        elif self.in_version_td:
            if not self.current_table_version:
                self.current_table_version = data_clean

def get_forge_versions(mc_version):
    """
    Scrapes the official Minecraft Forge download page for a given Minecraft version.
    Returns:
        dict: {
            "recommended": {"version": str, "url": str} or None,
            "latest": {"version": str, "url": str} or None,
            "versions": [{"version": str, "url": str, "is_latest": bool, "is_recommended": bool}]
        }
    """
    url = f"https://files.minecraftforge.net/net/minecraftforge/forge/index_{mc_version}.html"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    response = requests.get(url, headers=headers, timeout=10)
    if response.status_code == 404:
        raise ValueError(f"Minecraft version '{mc_version}' is not supported by Minecraft Forge.")
    response.raise_for_status()
    
    parser = ForgeHTMLParser()
    parser.feed(response.text)
    
    # Post-process versions to ensure is_latest and is_recommended match the main download panel
    recommended_version = parser.recommended["version"] if parser.recommended else None
    latest_version = parser.latest["version"] if parser.latest else None
    
    for v in parser.versions:
        if recommended_version and v["version"] == recommended_version:
            v["is_recommended"] = True
        if latest_version and v["version"] == latest_version:
            v["is_latest"] = True
            
    return {
        "recommended": parser.recommended,
        "latest": parser.latest,
        "versions": parser.versions
    }

if __name__ == "__main__":
    import json
    try:
        res = get_forge_versions("1.20.1")
        print(json.dumps(res, indent=2))
    except Exception as e:
        print(f"Error: {e}")
