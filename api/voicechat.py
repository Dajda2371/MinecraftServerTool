import os
import glob

def detect_voicechat(server_name: str) -> dict:
    """
    Detects whether Simple Voice Chat is present on a given server.
    
    Checks:
    1. Presence of voicechat-server.properties config file in standard paths.
    2. Presence of a jar file containing the token "voicechat" in mods/ or plugins/.
    
    Returns a dict:
        {
            "detected": bool,
            "type": "mod" | "plugin" | None,
            "config_path": str | None,
            "current_port": int | None
        }
    """
    server_dir = os.path.abspath(f"data/servers/{server_name}")
    
    # Priority 1: Properties files (strongest signal!)
    # Standard locations for mods and plugins
    config_paths = [
        # Mods: standard modern subfolder config
        os.path.join(server_dir, "config", "voicechat", "voicechat-server.properties"),
        os.path.join(server_dir, "config", "voicechat-server.properties"),
        # Plugins: standard plugin subfolder config
        os.path.join(server_dir, "plugins", "voicechat", "voicechat-server.properties"),
        # Fallbacks
        os.path.join(server_dir, "voicechat-server.properties"),
    ]
    
    found_config_path = None
    current_port = None
    
    for path in config_paths:
        if os.path.exists(path):
            found_config_path = path
            break
            
    if found_config_path:
        # Read the port value from the properties file
        try:
            with open(found_config_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        key, val = line.split("=", 1)
                        if key.strip() == "port":
                            current_port = int(val.strip())
                            break
        except Exception as e:
            print(f"[VoiceChat Detection] Error reading port from {found_config_path}: {e}")
            
        # Determine type based on directory path
        is_plugin = "plugins" in found_config_path
        return {
            "detected": True,
            "type": "plugin" if is_plugin else "mod",
            "config_path": found_config_path,
            "current_port": current_port
        }
        
    # Priority 2: Scan directories for jar files
    # Check mods directory
    mods_dir = os.path.join(server_dir, "mods")
    if os.path.exists(mods_dir):
        try:
            for fname in os.listdir(mods_dir):
                if fname.endswith(".jar") and "voicechat" in fname.lower():
                    # Default config path for next save
                    default_path = os.path.join(server_dir, "config", "voicechat", "voicechat-server.properties")
                    return {
                        "detected": True,
                        "type": "mod",
                        "config_path": default_path,
                        "current_port": None
                    }
        except Exception as e:
            print(f"[VoiceChat Detection] Error listing mods dir: {e}")
            
    # Check plugins directory
    plugins_dir = os.path.join(server_dir, "plugins")
    if os.path.exists(plugins_dir):
        try:
            for fname in os.listdir(plugins_dir):
                if fname.endswith(".jar") and "voicechat" in fname.lower():
                    # Default config path for next save
                    default_path = os.path.join(server_dir, "plugins", "voicechat", "voicechat-server.properties")
                    return {
                        "detected": True,
                        "type": "plugin",
                        "config_path": default_path,
                        "current_port": None
                    }
        except Exception as e:
            print(f"[VoiceChat Detection] Error listing plugins dir: {e}")
            
    return {
        "detected": False,
        "type": None,
        "config_path": None,
        "current_port": None
    }


def write_or_update_voicechat_properties(config_path: str, port: int, voice_host: str):
    """
    Surgically modifies voicechat-server.properties to update 'port' and 'voice_host'
    keys, keeping comments, whitespace, and formatting entirely intact.
    If the file does not exist, creates a clean config with the requested values.
    """
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    
    lines = []
    port_updated = False
    voice_host_updated = False
    
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            print(f"[VoiceChat] Error reading properties from {config_path}: {e}")
            lines = []
            
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key, val = stripped.split("=", 1)
            key = key.strip()
            if key == "port":
                # Find trailing spaces / newlines if any
                suffix = "\n" if not line.endswith("\r\n") else "\r\n"
                new_lines.append(f"port={port}{suffix}")
                port_updated = True
            elif key == "voice_host":
                suffix = "\n" if not line.endswith("\r\n") else "\r\n"
                new_lines.append(f"voice_host={voice_host}{suffix}")
                voice_host_updated = True
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
            
    # Append if not already present
    if not port_updated:
        new_lines.append(f"port={port}\n")
    if not voice_host_updated:
        new_lines.append(f"voice_host={voice_host}\n")
        
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(f"[VoiceChat] Updated properties at {config_path} successfully. (port={port}, voice_host={voice_host})")
    except Exception as e:
        print(f"[VoiceChat] Error writing properties to {config_path}: {e}")


def sync_voicechat_properties_if_needed(server_name: str):
    """
    Looks up the active UDP rule for a server and propagates its ports
    into the voicechat-server.properties config.
    """
    from api.db import get_server_firewall_rules, get_server_info
    
    # 1. Detect voicechat existence
    detection = detect_voicechat(server_name)
    if not detection["detected"]:
        return
        
    config_path = detection["config_path"]
    if not config_path:
        # Default fallback path
        config_path = os.path.abspath(f"data/servers/{server_name}/config/voicechat/voicechat-server.properties")
        
    # 2. Query firewall rules for UDP
    rules = get_server_firewall_rules(server_name)
    vc_rule = None
    
    # First attempt: search by specific voice chat label or standard voice chat port
    for r in rules:
        if r["enabled"] and r["protocol"] == "UDP" and (r["label"].strip().lower() == "simple voice chat" or r["internal_port"] == 24454):
            vc_rule = r
            break
            
    # Second attempt fallback: first enabled UDP rule
    if not vc_rule:
        for r in rules:
            if r["enabled"] and r["protocol"] == "UDP":
                vc_rule = r
                break
                
    if vc_rule:
        info = get_server_info(server_name)
        hostname = info.get("hostname") if info else None
        
        external_port = vc_rule["external_port"]
        internal_port = vc_rule["internal_port"]
        
        # Standard dynamic voice host
        voice_host = f"{hostname}:{external_port}" if hostname else f"<public-host>:{external_port}"
        
        write_or_update_voicechat_properties(config_path, internal_port, voice_host)


def parse_voicechat_properties(server_name: str) -> dict:
    """
    Parses voicechat-server.properties for key properties (values and preceding descriptions).
    """
    detection = detect_voicechat(server_name)
    if not detection["detected"] or not detection["config_path"]:
        return {"detected": False}
        
    config_path = detection["config_path"]
    
    # Defaults in case keys don't exist
    default_values = {
        "port": "24454",
        "max_voice_distance": "48.0",
        "whisper_distance": "24.0",
        "enable_groups": "true",
        "allow_recording": "true",
        "spectator_interaction": "false",
        "spectator_player_possession": "false",
        "broadcast_range": "-1.0"
    }
    
    default_descriptions = {
        "port": "The port number to use for the voice chat communication.",
        "max_voice_distance": "The distance to which the voice can be heard",
        "whisper_distance": "The distance to which the voice can be heard when whispering",
        "enable_groups": "If group chats are allowed",
        "allow_recording": "If players are allowed to record the voice chat audio",
        "spectator_interaction": "If spectators are allowed to talk to other players",
        "spectator_player_possession": "If spectators can talk to players they are spectating",
        "broadcast_range": "The range in which the voice chat should broadcast audio"
    }
    
    properties = {}
    for k in default_values.keys():
        properties[k] = {
            "value": default_values[k],
            "description": default_descriptions[k]
        }
        
    if os.path.exists(config_path):
        try:
            comment_buffer = []
            with open(config_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        comment_buffer = []
                        continue
                    if stripped.startswith("#"):
                        # Extract description line
                        comment_buffer.append(stripped[1:].strip())
                        continue
                    if "=" in stripped:
                        key, val = stripped.split("=", 1)
                        key = key.strip()
                        val = val.strip()
                        if key in properties:
                            properties[key]["value"] = val
                            if comment_buffer:
                                properties[key]["description"] = "\n".join(comment_buffer)
                        comment_buffer = []
        except Exception as e:
            print(f"[VoiceChat Parser Error] {e}")
            
    return {
        "detected": True,
        "properties": properties
    }


def update_voicechat_properties_bulk(server_name: str, updates: dict):
    """
    Surgically updates multiple voicechat properties, keeping formatting/comments.
    """
    detection = detect_voicechat(server_name)
    if not detection["detected"] or not detection["config_path"]:
        raise ValueError("Simple Voice Chat not detected or config path not found")
        
    config_path = detection["config_path"]
    os.makedirs(os.path.dirname(config_path), exist_ok=True)
    
    lines = []
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            print(f"[VoiceChat Bulk Write] Error reading: {e}")
            
    updated_keys = set()
    new_lines = []
    
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key, val = stripped.split("=", 1)
            key = key.strip()
            if key in updates:
                suffix = "\n" if not line.endswith("\r\n") else "\r\n"
                new_lines.append(f"{key}={updates[key]}{suffix}")
                updated_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
            
    # Append any key that wasn't already in the file
    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}\n")
            
    try:
        with open(config_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        print(f"[VoiceChat Bulk Write] Error writing: {e}")
        raise e
