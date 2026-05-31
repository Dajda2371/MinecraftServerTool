import requests

def get_mc_version_from_neoforge_version(neoforge_version):
    # Check if legacy format e.g. "1.20.1-47.1.5"
    if "-" in neoforge_version:
        parts = neoforge_version.split("-")
        # Ensure it looks like a Minecraft version on the left
        if parts[0].startswith("1."):
            return parts[0]
            
    spl = neoforge_version.split('.')
    if not spl:
        return None
    try:
        major = int(spl[0])
    except ValueError:
        return None
        
    if major >= 26:
        if len(spl) >= 2:
            mc_version = f"{spl[0]}.{spl[1]}"
        else:
            mc_version = spl[0]
            
        if len(spl) >= 3 and spl[2] != '0':
            mc_version += f".{spl[2]}"
            
        # check for snapshot identifier
        split_snapshot = neoforge_version.split('+')
        if len(split_snapshot) == 2:
            mc_version += f"-{split_snapshot[1]}"
        return mc_version
    else:
        if len(spl) >= 2:
            return f"1.{spl[0]}.{spl[1]}"
        return f"1.{spl[0]}"

def get_neoforge_versions(mc_version):
    mc_version = mc_version.strip()
    
    # If the user requested a 1.x.0 version, explicitly return no versions
    # as it is not a valid Minecraft version (the valid one is 1.x).
    parts = mc_version.split('.')
    if len(parts) == 3 and parts[0] == "1" and parts[2] == "0":
        return {
            "recommended": None,
            "latest": None,
            "versions": []
        }

    # 1. Fetch neoforged.net to verify and locate section_block
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        res_page = requests.get("https://neoforged.net/", headers=headers, timeout=10)
        res_page.raise_for_status()
        if "section_block" not in res_page.text and "selection_block" not in res_page.text:
            print("[Warning] Neither 'section_block' nor 'selection_block' class found in neoforged.net HTML, but continuing anyway.")
    except Exception as e:
        print(f"[Warning] Failed to fetch or verify neoforged.net: {e}")

    # 2. Fetch all releases from Maven API (try both new and legacy GAVs)
    gavs = ["net/neoforged/neoforge", "net/neoforged/forge"]
    all_versions = []
    
    for gav in gavs:
        url = f"https://maven.neoforged.net/api/maven/versions/releases/{gav}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()
            all_versions.extend(data.get("versions", []))
        except Exception as e:
            print(f"[NeoForge] Main maven offline or failed for {gav}. Using CreeperHost fallback. Error: {e}")
            fallback_url = f"https://maven.creeperhost.net/api/maven/versions/releases/{gav}"
            try:
                response = requests.get(fallback_url, timeout=10)
                response.raise_for_status()
                data = response.json()
                all_versions.extend(data.get("versions", []))
            except Exception as fe:
                print(f"[NeoForge] Fallback failed for {gav}: {fe}")

    # If the version is of the old "1.x" format, we match it against parsed "1.x.0"
    # e.g., normalized "1.20" matches parsed "1.20.0"
    if len(parts) == 2 and parts[0] == "1":
        target_mc = f"{mc_version}.0"
    else:
        target_mc = mc_version

    # Filter versions that match the requested target_mc
    matching_versions = []
    for v in all_versions:
        parsed_mc = get_mc_version_from_neoforge_version(v)
        if parsed_mc == target_mc:
            matching_versions.append(v)

    # Sort matching versions newest first.
    # We reverse them since they are returned chronologically by the Maven API.
    matching_versions.reverse()

    if not matching_versions:
        return {
            "recommended": None,
            "latest": None,
            "versions": []
        }

    latest_ver = matching_versions[0]
    
    # Format the results
    versions_list = []
    for i, v in enumerate(matching_versions):
        is_latest = (i == 0)
        # Determine the correct GAV and filename for this version
        is_legacy = "-" in v
        gav = "net/neoforged/forge" if is_legacy else "net/neoforged/neoforge"
        file_prefix = "forge" if is_legacy else "neoforge"
        installer_url = f"https://maven.neoforged.net/releases/{gav}/{v}/{file_prefix}-{v}-installer.jar"
        versions_list.append({
            "version": v,
            "url": installer_url,
            "is_latest": is_latest,
            "is_recommended": is_latest
        })

    is_legacy_latest = "-" in latest_ver
    gav_latest = "net/neoforged/forge" if is_legacy_latest else "net/neoforged/neoforge"
    file_prefix_latest = "forge" if is_legacy_latest else "neoforge"
    recommended_info = {
        "version": latest_ver,
        "url": f"https://maven.neoforged.net/releases/{gav_latest}/{latest_ver}/{file_prefix_latest}-{latest_ver}-installer.jar"
    }

    return {
        "recommended": recommended_info,
        "latest": recommended_info,
        "versions": versions_list
    }

if __name__ == "__main__":
    import json
    try:
        # Test 1.20 (should fetch 1.20.0 versions)
        res = get_neoforge_versions("1.20")
        print("1.20 Recommended:", res["recommended"]["version"] if res["recommended"] else None)

        # Test 1.20.0 (should explicitly return None / no versions)
        res_zero = get_neoforge_versions("1.20.0")
        print("1.20.0 Recommended:", res_zero["recommended"]["version"] if res_zero["recommended"] else None)

        # Test 1.21 (should fetch 1.21.0 versions)
        res_twentyone = get_neoforge_versions("1.21")
        print("1.21 Recommended:", res_twentyone["recommended"]["version"] if res_twentyone["recommended"] else None)

        # Test 1.21.0 (should explicitly return None / no versions)
        res_twentyone_zero = get_neoforge_versions("1.21.0")
        print("1.21.0 Recommended:", res_twentyone_zero["recommended"]["version"] if res_twentyone_zero["recommended"] else None)
        
        # Test 1.21.1
        res2 = get_neoforge_versions("1.21.1")
        print("1.21.1 Recommended:", res2["recommended"]["version"] if res2["recommended"] else None)
    except Exception as e:
        print(f"Error: {e}")
