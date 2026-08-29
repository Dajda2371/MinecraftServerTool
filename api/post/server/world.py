"""
Single-player world import / export helpers.

Import: take a zipped single-player save (the folder that contains
``level.dat``) and extract it into ``data/servers/<name>/world`` using the
vanilla layout (``DIM-1`` / ``DIM1`` nested inside ``world``). CraftBukkit-based
servers (Spigot/Paper) migrate that layout into ``world_nether`` /
``world_the_end`` themselves on first boot, so we never pre-split it.

Export: zip a server's world back into a single-player compatible archive.
For Bukkit-style servers the nether/end dimension folders are merged back
under the overworld folder so the client finds them.

All helpers are plain stdlib; no FastAPI or Docker imports here.
"""

import os
import shutil
import stat
import time
import zipfile

BUKKIT_TYPES = {"spigot", "paper"}
EXPORTS_DIRNAME = ".exports"
IMPORT_ARCHIVE_NAME = ".world-import.zip"


class WorldImportError(Exception):
    """Raised when an uploaded archive is not a usable Minecraft world."""


def server_dir(server_name):
    return os.path.realpath(os.path.join("data", "servers", server_name))


def get_level_name(server_name):
    """Read ``level-name`` from server.properties, defaulting to ``world``."""
    props_path = os.path.join(server_dir(server_name), "server.properties")
    if not os.path.exists(props_path):
        return "world"
    try:
        with open(props_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                stripped = line.strip()
                if "=" in stripped and not stripped.startswith("#"):
                    key, value = stripped.split("=", 1)
                    if key.strip() == "level-name":
                        value = value.strip()
                        return value or "world"
    except Exception:
        pass
    return "world"


def _normalize_entry_name(name):
    """Return a forward-slash entry name, or None if the entry must be skipped."""
    name = name.replace("\\", "/")
    if not name or name.startswith("__MACOSX/") or name.startswith("/"):
        return None
    # Windows drive letters ("C:/...") and parent references are never valid.
    if len(name) > 1 and name[1] == ":":
        return None
    if any(part == ".." for part in name.split("/")):
        return None
    return name


def find_world_root(zf):
    """
    Locate the world folder inside the archive.

    Returns the prefix of the shallowest ``level.dat`` (``""`` when the world
    files sit at the archive root, ``"MyWorld/"`` when nested).
    """
    candidates = []
    for info in zf.infolist():
        name = _normalize_entry_name(info.filename)
        if not name or info.is_dir():
            continue
        if name.rsplit("/", 1)[-1] == "level.dat":
            candidates.append(name)

    if not candidates:
        raise WorldImportError(
            "Archive does not contain a Minecraft world (no level.dat found)."
        )

    min_depth = min(name.count("/") for name in candidates)
    roots = {
        name[: -len("level.dat")]
        for name in candidates
        if name.count("/") == min_depth
    }
    if len(roots) > 1:
        raise WorldImportError(
            "Archive contains more than one world; zip a single save folder."
        )
    return roots.pop()


def _is_symlink_entry(info):
    return stat.S_ISLNK(info.external_attr >> 16)


def import_world_archive(server_name, zip_path, log=None):
    """
    Extract the uploaded archive into ``data/servers/<name>/world``.

    The archive is deleted afterwards regardless of the outcome. Raises
    ``WorldImportError`` / ``zipfile.BadZipFile`` on failure.
    """
    def _log(line):
        if log:
            try:
                log(line)
            except Exception:
                pass

    base = server_dir(server_name)
    world_dir = os.path.join(base, "world")

    try:
        _log("[World] Importing uploaded world...")

        for folder in ("world", "world_nether", "world_the_end"):
            stale = os.path.join(base, folder)
            if os.path.isdir(stale):
                _log(f"[World] Removing existing '{folder}' folder before import.")
                shutil.rmtree(stale, ignore_errors=True)

        with zipfile.ZipFile(zip_path) as zf:
            prefix = find_world_root(zf)
            file_count = 0
            for info in zf.infolist():
                name = _normalize_entry_name(info.filename)
                if not name or not name.startswith(prefix):
                    continue
                if _is_symlink_entry(info):
                    continue
                rel = name[len(prefix):]
                if not rel:
                    continue
                if rel.rsplit("/", 1)[-1] == "session.lock":
                    continue

                dest = os.path.realpath(os.path.join(world_dir, rel))
                if dest != world_dir and not dest.startswith(world_dir + os.sep):
                    raise WorldImportError(f"Unsafe path in archive: {info.filename}")

                if info.is_dir():
                    os.makedirs(dest, exist_ok=True)
                    continue

                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(info) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)
                file_count += 1
                if file_count % 500 == 0:
                    _log(f"[World] Extracted {file_count} files...")

        if not os.path.isfile(os.path.join(world_dir, "level.dat")):
            raise WorldImportError("Extraction finished but world/level.dat is missing.")

        _log(f"[World] World import complete: {file_count} files.")
    except Exception as e:
        _log(f"[World] Import failed: {e}")
        raise
    finally:
        try:
            os.remove(zip_path)
        except OSError:
            pass


def _add_tree(zf, src_root, arc_root, skip_names=(), skip_top_dirs=()):
    """Add every file under ``src_root`` to ``zf`` as ``arc_root/<relpath>``."""
    count = 0
    if not os.path.isdir(src_root):
        return count
    for dirpath, dirnames, filenames in os.walk(src_root):
        rel_dir = os.path.relpath(dirpath, src_root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
        if rel_dir == "":
            dirnames[:] = [d for d in dirnames if d not in skip_top_dirs]
        for filename in filenames:
            if filename in skip_names:
                continue
            full = os.path.join(dirpath, filename)
            if not os.path.isfile(full):
                continue
            arcname = f"{arc_root}/{rel_dir}/{filename}" if rel_dir else f"{arc_root}/{filename}"
            zf.write(full, arcname)
            count += 1
    return count


def export_world_archive(server_name, server_type, dest_zip_path):
    """
    Zip the server's world as ``<server_name>/...`` so it can be dropped into
    ``.minecraft/saves``. Returns the number of files written.
    """
    base = server_dir(server_name)
    level = get_level_name(server_name)
    overworld = os.path.join(base, level)
    if not os.path.isfile(os.path.join(overworld, "level.dat")):
        raise FileNotFoundError(f"World folder '{level}' has no level.dat.")

    top = server_name
    part_path = dest_zip_path + ".part"
    os.makedirs(os.path.dirname(dest_zip_path), exist_ok=True)

    count = 0
    try:
        with zipfile.ZipFile(part_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
            count += _add_tree(zf, overworld, top, skip_names=("session.lock",))

            if (server_type or "").lower() in BUKKIT_TYPES:
                # Bukkit keeps DIM-1 / DIM1 in sibling worlds; fold them back
                # under the overworld the way the vanilla client expects.
                # Only include a dimension from the sibling folder when the
                # overworld doesn't already carry it (e.g. an imported world
                # the server never migrated yet).
                for sibling, dim in ((f"{level}_nether", "DIM-1"), (f"{level}_the_end", "DIM1")):
                    if os.path.isdir(os.path.join(overworld, dim)):
                        continue
                    dim_src = os.path.join(base, sibling, dim)
                    count += _add_tree(zf, dim_src, f"{top}/{dim}", skip_names=("session.lock",))
        os.replace(part_path, dest_zip_path)
    except Exception:
        try:
            os.remove(part_path)
        except OSError:
            pass
        raise
    return count


def sweep_stale_exports(server_name, max_age_s=3600):
    """Delete leftover export archives (e.g. downloads that were never fetched)."""
    exports_dir = os.path.join(server_dir(server_name), EXPORTS_DIRNAME)
    if not os.path.isdir(exports_dir):
        return
    now = time.time()
    for entry in os.listdir(exports_dir):
        if not (entry.endswith(".zip") or entry.endswith(".part")):
            continue
        path = os.path.join(exports_dir, entry)
        try:
            if now - os.path.getmtime(path) > max_age_s:
                os.remove(path)
        except OSError:
            pass
