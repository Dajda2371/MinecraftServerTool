import os
import time
import re
import glob
import threading
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

from api.db import get_server_info
from api.post.server.mounts import SERVER_DATA_VOLUME, write_volume_file

LOADERS = {
    "forge": 1,
    "fabric": 4,
    "neoforge": 6,
}

# Socket.IO log callback hook
log_callback = None

def register_log_callback(cb):
    global log_callback
    log_callback = cb

def log_message(server_name, text):
    # Inside the container, just print raw text to stdout so the parent streams it.
    # We do NOT write to /data/creation.log here to avoid double-write duplication.
    if os.path.exists("/data"):
        print(text)
        return

    # Outside the container (CLI mode / local)
    print(f"[{server_name}] {text}")
    log_path = os.path.join("data", "servers", server_name, "creation.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(text + "\n")
        # Read cumulative creation.log and write to volume
        with open(log_path, "r", encoding="utf-8") as f:
            full_content = f.read()
        write_volume_file(SERVER_DATA_VOLUME, f"servers/{server_name}/creation.log", full_content)
    except Exception as e:
        print(f"[Volume Log Write Error] {e}")

    if log_callback:
        try:
            log_callback(server_name, text + "\n")
        except Exception as e:
            print(f"[LogCallback Error] {e}")

def dismiss_cookie_bar(driver):
    """Click the cookie consent button if it exists."""
    try:
        driver.execute_script("""
            var btn = document.getElementById('cookiebar-ok');
            if (btn) { btn.click(); }
            document.querySelectorAll('button, a').forEach(function(el) {
                if ((el.textContent || '').trim() === 'Got it') el.click();
            });
        """)
    except Exception:
        pass

def wait_for_downloads(mods_dir, timeout=30):
    """Wait until no .crdownload files remain."""
    for _ in range(timeout):
        if not glob.glob(os.path.join(mods_dir, "*.crdownload")):
            return True
        time.sleep(1)
    return False

def download_mod(driver, server_name, mod_name, mod_url, mc_version, loader_id, mods_dir):
    """
    Downloads a single mod by navigating its CurseForge download pages.
    """
    # Step 1: Open filtered files page
    files_url = (
        f"{mod_url.rstrip('/')}/files/all"
        f"?page=1&pageSize=20&version={mc_version}"
        f"&gameVersionTypeId={loader_id}&showAlphaFiles=hide"
    )
    log_message(server_name, f"  Searching releases for MC {mc_version}...")
    try:
        driver.get(files_url)
    except Exception as e:
        log_message(server_name, f"  ⚠ Web request failed for {mod_name}: {e}")
        return False

    dismiss_cookie_bar(driver)
    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a.file-row-details"))
        )
    except Exception:
        time.sleep(4)
        dismiss_cookie_bar(driver)

    file_href = driver.execute_script("""
        var rows = document.querySelectorAll('a.file-row-details');
        if (rows.length > 0) return rows[0].getAttribute('href');

        var all = document.querySelectorAll('a[href]');
        for (var i = 0; i < all.length; i++) {
            var h = all[i].getAttribute('href') || '';
            if (/\\/files\\/\\d+$/.test(h) && h.includes('/mc-mods/')) {
                var rect = all[i].getBoundingClientRect();
                if (rect.width > 100 && rect.top > 200) {
                    return h;
                }
            }
        }
        return null;
    """)

    if not file_href:
        no_results = driver.execute_script("return document.body.innerText.includes('No Results');")
        if no_results:
            log_message(server_name, f"  ⚠ No compatible releases found for Minecraft {mc_version}.")
        else:
            log_message(server_name, f"  ⚠ Could not find mod files listing row.")
        return False

    # Make absolute
    if not file_href.startswith("http"):
        file_page_url = "https://www.curseforge.com" + file_href
    else:
        file_page_url = file_href

    # Step 2: Open file detail page
    try:
        driver.get(file_page_url)
    except Exception as e:
        log_message(server_name, f"  ⚠ Detail page load failed for {mod_name}: {e}")
        return False
    dismiss_cookie_bar(driver)

    try:
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "a.btn-cta"))
        )
    except Exception:
        time.sleep(4)
        dismiss_cookie_bar(driver)

    download_href = driver.execute_script("""
        var btns = document.querySelectorAll('a.btn-cta');
        for (var i = 0; i < btns.length; i++) {
            var h = btns[i].getAttribute('href') || '';
            if (h.includes('/download/') || h.includes('/download')) {
                return h;
            }
        }

        var links = document.querySelectorAll('a[href*="/download/"]');
        for (var i = 0; i < links.length; i++) {
            var h = links[i].getAttribute('href');
            if (/\\/download\\/\\d+/.test(h)) return h;
        }

        var all = document.querySelectorAll('a, button');
        for (var i = 0; i < all.length; i++) {
            var txt = (all[i].textContent || '').trim();
            if (txt === 'Download' && all[i].offsetParent !== null) {
                var h = all[i].getAttribute('href');
                if (h) return h;
                all[i].click();
                return '__clicked__';
            }
        }
        return null;
    """)

    if not download_href:
        log_message(server_name, f"  ⚠ Download trigger not found on detail page.")
        return False

    # Count files before download
    files_before = set(os.listdir(mods_dir))

    if download_href == '__clicked__':
        log_message(server_name, f"  Triggering direct download...")
    else:
        if not download_href.startswith("http"):
            download_url = "https://www.curseforge.com" + download_href
        else:
            download_url = download_href
        try:
            driver.get(download_url)
        except Exception:
            # Direct download links often trigger a download dialog and cause a page load timeout,
            # which is completely normal. We catch it and proceed to wait for the download.
            pass

    # Step 3: Wait for download to start/finish
    time.sleep(8)
    wait_for_downloads(mods_dir, timeout=20)

    # Verify download success
    files_after = set(os.listdir(mods_dir))
    new_files = {f for f in (files_after - files_before) if not f.endswith(".crdownload")}
    if new_files:
        for f in new_files:
            size_mb = os.path.getsize(os.path.join(mods_dir, f)) / (1024 * 1024)
            log_message(server_name, f"  ✓ Saved: {f} ({size_mb:.2f} MB)")
        return True
    else:
        log_message(server_name, f"  ⏳ Mod added to download queue...")
        return True

def download_curseforge_mods_background(server_name, html_content):
    """
    Downloads mods listed in a CurseForge HTML modlist export or a manifest.json file inside a background worker.
    """
    log_message(server_name, "\n=== CURSEFORGE MOD DOWNLOADER ===")
    
    info = get_server_info(server_name)
    if not info:
        log_message(server_name, f"Error: Server '{server_name}' not found.")
        return
        
    mc_version = info["version"].split("-")[0]
    loader_name = "forge"
    loader_id = LOADERS[loader_name]
    
    log_message(server_name, f"Target: Minecraft {mc_version} / {loader_name.capitalize()}")
    
    if os.path.exists("/data"):
        mods_dir = "/data/mods"
    else:
        mods_dir = os.path.abspath(f"data/servers/{server_name}/mods")
    os.makedirs(mods_dir, exist_ok=True)
    
    # Try parsing the content as JSON manifest first
    import json
    is_json = False
    manifest = None
    try:
        manifest = json.loads(html_content)
        is_json = True
    except Exception:
        pass
        
    if is_json:
        files = manifest.get("files", [])
        mod_entries = []
        for f in files:
            if f.get("required") is True:
                project_id = f.get("projectID")
                file_id = f.get("fileID")
                if project_id and file_id:
                    mod_entries.append({
                        "project_id": project_id,
                        "file_id": file_id
                    })
        
        log_message(server_name, f"Found {len(mod_entries)} required mod(s) in manifest.json.")
        if not mod_entries:
            log_message(server_name, "No required CurseForge mods found. Completed.")
            return
    else:
        # Parse the HTML content
        soup = BeautifulSoup(html_content, "html.parser")
        mod_html_entries = [
            (a.get_text(strip=True), a["href"])
            for a in soup.find_all("a", href=True)
            if "curseforge.com/minecraft/mc-mods/" in a["href"]
        ]
        
        log_message(server_name, f"Found {len(mod_html_entries)} mod(s) in HTML modlist.")
        if not mod_html_entries:
            log_message(server_name, "No compatible CurseForge mod links found. Completed.")
            return

    # Setup headless Chromium
    log_message(server_name, "Initializing anti-detect browser driver...")
    options = Options()
    prefs = {
        "download.default_directory": mods_dir,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }
    options.add_experimental_option("prefs", prefs)
    options.page_load_strategy = 'eager'
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_argument("--remote-allow-origins=*")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = None
    try:
        # Use Chromium Driver from standard debian path
        service = Service("/usr/bin/chromedriver")
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(30)
        driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        driver.execute_cdp_cmd("Page.setDownloadBehavior", {
            "behavior": "allow",
            "downloadPath": mods_dir,
        })
    except Exception as e:
        log_message(server_name, f"❌ Failed to launch Chromium webdriver: {e}\nMake sure 'chromium' and 'chromium-driver' are installed.")
        return

    # Warm up visit
    log_message(server_name, "Passing Cloudflare security check...")
    try:
        driver.get("https://www.curseforge.com")
        time.sleep(8)
        dismiss_cookie_bar(driver)
    except Exception as e:
        log_message(server_name, f"Warning: Failed to warm up driver: {e}")

    succeeded = 0
    failed = []

    if is_json:
        for idx, mod in enumerate(mod_entries, 1):
            project_id = mod["project_id"]
            file_id = mod["file_id"]
            log_message(server_name, f"\n[{idx}/{len(mod_entries)}] Processing Project ID {project_id}, File ID {file_id}")
            
            # Step 1: go to curseforge.com/projects/ID (redirects to minecraft/mc-mods/slug)
            proj_url = f"https://www.curseforge.com/projects/{project_id}"
            try:
                driver.get(proj_url)
                time.sleep(3)
                dismiss_cookie_bar(driver)
                
                # Step 2: form file detail URL
                redirected_url = driver.current_url.split("?")[0].rstrip("/")
                file_details_url = f"{redirected_url}/files/{file_id}"
                log_message(server_name, f"  Navigating to details: {file_details_url}")
                driver.get(file_details_url)
                time.sleep(3)
                dismiss_cookie_bar(driver)
                
                # Step 3: find the filename.jar in <section class="section-file-name"><h3>File Name</h3><p class="wrap">{file name}.jar</p></section>
                file_name = driver.execute_script("""
                    var p = document.querySelector('section.section-file-name p.wrap');
                    if (p) return p.textContent.trim();
                    var sec = document.querySelector('section.section-file-name');
                    if (sec) return sec.textContent.replace('File Name', '').trim();
                    return null;
                """)
                
                if not file_name:
                    # Fallback to BeautifulSoup
                    soup = BeautifulSoup(driver.page_source, "html.parser")
                    sec = soup.find("section", class_="section-file-name")
                    if sec:
                        p = sec.find("p", class_="wrap")
                        if p:
                            file_name = p.get_text(strip=True)
                        else:
                            file_name = sec.get_text(strip=True).replace("File Name", "").strip()
                            
                if not file_name:
                    log_message(server_name, f"  ⚠ Could not find File Name on details page for Project {project_id}, File {file_id}")
                    failed.append(f"Project {project_id} (File {file_id})")
                    continue
                    
                log_message(server_name, f"  Found file name: {file_name}")
                
                # Step 4: go to edge.forgecdn.net
                file_id_str = str(file_id)
                if len(file_id_str) < 4:
                    rest = "0"
                    last_three = file_id_str.zfill(3)
                else:
                    rest = file_id_str[:-3]
                    last_three = file_id_str[-3:]
                    
                direct_download_url = f"https://edge.forgecdn.net/files/{rest}/{last_three}/{file_name}"
                log_message(server_name, f"  Downloading via CDN: {direct_download_url}")
                
                # Direct download using requests
                try:
                    import requests
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    }
                    dest_path = os.path.join(mods_dir, file_name)
                    response = requests.get(direct_download_url, headers=headers, stream=True, timeout=30)
                    if response.status_code == 200:
                        with open(dest_path, "wb") as f_out:
                            for chunk in response.iter_content(chunk_size=8192):
                                f_out.write(chunk)
                        size_mb = os.path.getsize(dest_path) / (1024 * 1024)
                        log_message(server_name, f"  ✓ Saved: {file_name} ({size_mb:.2f} MB)")
                        succeeded += 1
                    else:
                        raise Exception(f"Direct download failed with status {response.status_code}")
                except Exception as dl_err:
                    log_message(server_name, f"  ⚠ Direct CDN download failed: {dl_err}. Retrying with browser...")
                    try:
                        driver.get(direct_download_url)
                        time.sleep(3)
                        succeeded += 1
                    except Exception as browser_err:
                        log_message(server_name, f"  ❌ Browser download attempt failed: {browser_err}")
                        failed.append(file_name)
            except Exception as e:
                log_message(server_name, f"  ❌ Error processing mod Project {project_id}: {e}")
                failed.append(f"Project {project_id} (File {file_id})")
    else:
        for idx, (mod_name, mod_url) in enumerate(mod_html_entries, 1):
            log_message(server_name, f"\n[{idx}/{len(mod_html_entries)}] {mod_name}")
            ok = download_mod(driver, server_name, mod_name, mod_url, mc_version, loader_id, mods_dir)
            if ok:
                succeeded += 1
            else:
                failed.append(mod_name)

    log_message(server_name, "\nFinalizing active downloads...")
    wait_for_downloads(mods_dir, timeout=20)
    
    try:
        driver.quit()
    except Exception:
        pass

    total_count = len(mod_entries) if is_json else len(mod_html_entries)
    log_message(server_name, "\n=== DOWNLOAD RUN SUMMARY ===")
    log_message(server_name, f"✓ Succeeded: {succeeded}/{total_count}")
    if failed:
        log_message(server_name, f"⚠ Failed ({len(failed)}):")
        for f in failed:
            log_message(server_name, f"  - {f}")
            
    log_message(server_name, "Mod downloads completed.")

def start_mod_download_container(server_name, html_content):
    """
    Spawns an ephemeral Docker container using the same image as the management container
    to parse and download mods listed in a CurseForge HTML modlist export.
    Streams the container's standard output in real-time to Socket.IO and saves it to creation.log.
    """
    import socket
    import docker
    from api.post.server.mounts import server_data_mount, get_compose_labels, SERVER_DATA_VOLUME, write_volume_file

    log_message(server_name, "Spawning isolated mod downloader container...")
    
    # 1. Write the modlist HTML to the server directory in named volume
    write_volume_file(SERVER_DATA_VOLUME, f"servers/{server_name}/modlist.html", html_content)
    
    client = docker.from_env()
    
    # 2. Get the management container's own image
    hostname = socket.gethostname()
    try:
        me = client.containers.get(hostname)
        image = me.attrs['Config']['Image']
    except Exception:
        image = "minecraft-server-tool:latest"
        
    container_name = f"mc-mod-downloader-{server_name}"
    
    # Clean up existing container if it exists
    try:
        existing = client.containers.get(container_name)
        existing.stop(timeout=2)
        existing.remove()
    except Exception:
        pass
        
    # Use -u for unbuffered output so print statements stream immediately
    command = f"python3 -u -m api.post.server.mods --server {server_name} --html-file /data/modlist.html"
    
    # Pass along PG environment variables
    env = {
        "POSTGRES_HOST": os.environ.get("POSTGRES_HOST", "postgres"),
        "POSTGRES_PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "POSTGRES_DB": os.environ.get("POSTGRES_DB", "mcserver"),
        "POSTGRES_USER": os.environ.get("POSTGRES_USER", "mcserver"),
        "POSTGRES_PASSWORD": os.environ.get("POSTGRES_PASSWORD", "mcserver"),
    }
    
    container = client.containers.run(
        image=image,
        command=command,
        name=container_name,
        detach=True,
        mounts=[server_data_mount(server_name)],
        network="mc-net",
        environment=env,
        working_dir="/app",
        labels=get_compose_labels(f"mod-downloader-{server_name}"),
    )
    
    # 3. Monitor container stdout logs stream in real-time and cleanup
    def monitor_and_cleanup():
        # Clear/initialize creation.log on host so it starts clean
        log_path = os.path.join("data", "servers", server_name, "creation.log")
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(f"Initiated mod list download from CurseForge Modlist uploader\n")
        except Exception:
            pass

        try:
            # Stream logs directly from the docker engine stdout/stderr
            for line in container.logs(stream=True, follow=True):
                decoded = line.decode("utf-8", errors="replace")
                
                # Append to creation.log on host
                try:
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(decoded)
                except Exception as write_err:
                    print(f"[Log Write Error] {write_err}")
                
                # Push in real-time to Socket.IO
                if log_callback:
                    try:
                        log_callback(server_name, decoded)
                    except Exception as e:
                        print(f"[LogCallback Error] {e}")
        except Exception as stream_err:
            print(f"[Log Stream Error] {stream_err}")
            
        try:
            container.wait()
        except Exception:
            pass
            
        time.sleep(2)
        
        # Remove completed container
        try:
            container.remove()
        except Exception:
            pass
            
        # Also clean up the temporary modlist.html file
        try:
            os.remove(os.path.join("data", "servers", server_name, "modlist.html"))
        except Exception:
            pass
            
    threading.Thread(target=monitor_and_cleanup, daemon=True).start()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Mods Downloader Ephemeral Container CLI Entrypoint")
    parser.add_argument("--server", required=True, help="Minecraft server name")
    parser.add_argument("--html-file", required=True, help="Path to the CurseForge modlist .html file")
    
    args = parser.parse_args()
    
    # Read the html list file
    try:
        with open(args.html_file, "r", encoding="utf-8") as f:
            html = f.read()
        download_curseforge_mods_background(args.server, html)
    except Exception as e:
        log_message(args.server, f"❌ Ephemeral downloader failed: {e}")
