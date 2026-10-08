"""
Custom Java runtimes for Minecraft servers.

Three ways to get a runtime besides the ones bundled in the base image
(see api.post.server.run.BUNDLED_JAVA_VERSIONS):

  * catalog  — any major version of any major distribution (Temurin, Zulu,
               Corretto, Liberica, Microsoft, GraalVM, SapMachine, ...) via
               the foojay Disco API (https://api.foojay.io), which hands us a
               direct download link for the host's architecture.
  * url      — a direct link to a .tar.gz / .tgz / .zip JDK or JRE archive.
  * upload   — the same kind of archive uploaded through the panel.

Each runtime lives in the shared data volume at ``data/.java/<id>/home``
(the directory that contains ``bin/java``). Server containers get it mounted
read-only at /opt/java/custom and the entrypoint selects it when
``JAVA_VERSION=custom`` (see docker/server-entrypoint.sh).

Download and extraction do NOT run inside the management container: for
every install a short-lived sidecar container (``mc-java-<id>``, running this
same image with ``python -m api.java_runtimes install``) is spawned with the
runtime's volume subpath mounted at /work, exactly like jar downloads and the
mod downloader. The management container only streams its log, tracks the
status and, once the sidecar exits, verifies the result by running
``java -version`` in a throwaway container of the server base image, so a
broken or wrong-arch archive never reaches a server.
"""

import os
import re
import json
import time
import shutil
import tarfile
import zipfile
import threading
import uuid

import requests

import api.db

DISCO_API = "https://api.foojay.io/disco/v3.0"
JAVA_ROOT = os.path.abspath("data/.java")
CUSTOM_MOUNT_PATH = "/opt/java/custom"
ARCHIVE_EXTENSIONS = (".tar.gz", ".tgz", ".tar", ".zip")

_catalog_cache = {}   # key -> (timestamp, payload)
_CACHE_TTL = 3600


# ---------------------------------------------------------------------------
# Paths / helpers
# ---------------------------------------------------------------------------

def runtime_dir(runtime_id):
    return os.path.join(JAVA_ROOT, runtime_id)


def runtime_home(runtime_id):
    return os.path.join(runtime_dir(runtime_id), "home")


def runtime_home_subpath(runtime_id):
    """Subpath inside the data volume (for volume_subpath_mount)."""
    return f".java/{runtime_id}/home"


def runtime_is_ready(runtime_id):
    rt = api.db.get_java_runtime(runtime_id)
    return bool(rt) and rt["status"] == "ready" and os.path.isfile(os.path.join(runtime_home(runtime_id), "bin", "java"))


def host_architecture():
    """Disco API architecture parameter for the Docker host."""
    try:
        import docker
        arch = docker.from_env().info().get("Architecture", "")
    except Exception:
        import platform
        arch = platform.machine()
    arch = (arch or "").lower()
    if arch in ("x86_64", "amd64", "x64"):
        return "x64"
    if arch in ("aarch64", "arm64"):
        return "aarch64"
    if arch.startswith("arm"):
        return "arm"
    return arch or "x64"


def _safe_name(value, fallback="runtime"):
    value = re.sub(r"[^A-Za-z0-9._ ()+-]+", "", str(value or "")).strip()
    return value[:80] or fallback


# ---------------------------------------------------------------------------
# Catalog (foojay Disco API)
# ---------------------------------------------------------------------------

def _cached(key, loader):
    now = time.time()
    hit = _catalog_cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    value = loader()
    _catalog_cache[key] = (now, value)
    return value


def list_distributions():
    """Maintained, available distributions as [{name, api_parameter}]."""
    def load():
        r = requests.get(f"{DISCO_API}/distributions", params={"include_versions": "false", "include_synonyms": "false"}, timeout=20)
        r.raise_for_status()
        out = []
        for d in r.json().get("result", []):
            if not d.get("maintained", True) or not d.get("available", True):
                continue
            out.append({"name": d.get("name"), "api_parameter": d.get("api_parameter")})
        out.sort(key=lambda d: d["name"].lower())
        return out
    return _cached("distributions", load)


def list_catalog_versions(distribution):
    """
    Latest GA package per major version for ``distribution`` on this host:
    [{major_version, java_version, package_type, filename, size, id}].
    Prefers JRE packages; falls back to JDK when no JRE build exists.
    """
    arch = host_architecture()

    def load():
        params = {
            "distribution": distribution,
            "operating_system": "linux",
            "architecture": arch,
            "archive_type": "tar.gz",
            "libc_type": "glibc",
            "release_status": "ga",
            "javafx_bundled": "false",
            "latest": "available",
            "directly_downloadable": "true",
        }
        r = requests.get(f"{DISCO_API}/packages", params=params, timeout=30)
        r.raise_for_status()
        by_major = {}
        for pkg in r.json().get("result", []):
            major = pkg.get("major_version")
            if not major:
                continue
            current = by_major.get(major)
            rank = 0 if pkg.get("package_type") == "jre" else 1
            if current is None or rank < current["_rank"] or (rank == current["_rank"] and pkg.get("java_version", "") > current["java_version"]):
                by_major[major] = {
                    "_rank": rank,
                    "major_version": major,
                    "java_version": pkg.get("java_version"),
                    "package_type": pkg.get("package_type"),
                    "filename": pkg.get("filename"),
                    "size": pkg.get("size"),
                    "id": pkg.get("id"),
                    "term_of_support": pkg.get("term_of_support"),
                }
        versions = sorted(by_major.values(), key=lambda v: v["major_version"], reverse=True)
        for v in versions:
            v.pop("_rank", None)
        return versions
    return _cached(f"versions:{distribution}:{arch}", load)


def catalog_package(distribution, major_version):
    for v in list_catalog_versions(distribution):
        if int(v["major_version"]) == int(major_version):
            return v
    return None


def catalog_download_url(package_id):
    """Resolve a Disco package id to its direct download URL."""
    r = requests.get(f"{DISCO_API}/ids/{package_id}", timeout=20)
    r.raise_for_status()
    result = r.json().get("result") or []
    if not result:
        raise RuntimeError("Package not found in the Disco catalog.")
    link = result[0].get("direct_download_uri") or (result[0].get("links") or {}).get("pkg_download_redirect")
    if not link:
        raise RuntimeError("Catalog entry has no download link.")
    return link


# ---------------------------------------------------------------------------
# Install jobs
# ---------------------------------------------------------------------------

def _set(runtime_id, **fields):
    api.db.update_java_runtime(runtime_id, **fields)


def _log(runtime_id, msg):
    print(f"[Java:{runtime_id}] {msg}")


def _archive_ext(name):
    name = name.lower()
    for ext in ARCHIVE_EXTENSIONS:
        if name.endswith(ext):
            return ext
    return None


def _download(url, dest):
    with requests.get(url, stream=True, timeout=60, allow_redirects=True) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1024 * 1024):
                if chunk:
                    f.write(chunk)


def _extract(archive, dest):
    """Extract tar/zip safely (reject members escaping dest)."""
    os.makedirs(dest, exist_ok=True)
    real_dest = os.path.realpath(dest)

    def check(path):
        if not os.path.realpath(os.path.join(dest, path)).startswith(real_dest + os.sep):
            raise RuntimeError(f"Archive member escapes extraction dir: {path}")

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for member in zf.infolist():
                check(member.filename)
                zf.extract(member, dest)
                # zip does not reliably carry exec bits: restore them from external_attr
                mode = (member.external_attr >> 16) & 0o777
                target = os.path.join(dest, member.filename)
                if mode and os.path.isfile(target):
                    os.chmod(target, mode)
        return
    if tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            for member in tf.getmembers():
                check(member.name)
                if member.issym() or member.islnk():
                    link_target = os.path.normpath(os.path.join(os.path.dirname(member.name), member.linkname))
                    check(link_target)
            try:
                tf.extractall(dest, filter="data")
            except TypeError:  # Python < 3.12
                tf.extractall(dest)
        return
    raise RuntimeError("Not a tar or zip archive.")


def _find_java_home(root, max_depth=4):
    """Locate the directory that contains bin/java (handles nested top-level dirs)."""
    for cur, dirs, files in os.walk(root):
        depth = cur[len(root):].count(os.sep)
        if os.path.isfile(os.path.join(cur, "bin", "java")):
            return cur
        if depth >= max_depth:
            dirs[:] = []
    return None


def _fix_permissions(home):
    """Make sure binaries are executable and everything is world-readable (UID 1000 runs Java)."""
    for cur, dirs, files in os.walk(home):
        for d in dirs:
            try:
                os.chmod(os.path.join(cur, d), 0o755)
            except OSError:
                pass
        for f in files:
            p = os.path.join(cur, f)
            try:
                st = os.stat(p)
                mode = st.st_mode & 0o777
                if "/bin" in cur or cur.endswith("/bin") or f in ("jspawnhelper", "jexec", "java"):
                    mode |= 0o755
                else:
                    mode |= 0o444
                os.chmod(p, mode)
            except OSError:
                pass


def _verify_in_container(runtime_id):
    """Run `java -version` from the base image with the runtime mounted; return the version line."""
    import docker
    from api.post.server.mounts import volume_subpath_mount, SERVER_DATA_VOLUME
    from api.post.server.run import DEFAULT_SERVER_IMAGE, ensure_image

    client = docker.from_env()
    ensure_image(client, DEFAULT_SERVER_IMAGE)
    mount = volume_subpath_mount(CUSTOM_MOUNT_PATH, SERVER_DATA_VOLUME, runtime_home_subpath(runtime_id), read_only=True)
    output = client.containers.run(
        image=DEFAULT_SERVER_IMAGE,
        entrypoint=[f"{CUSTOM_MOUNT_PATH}/bin/java"],
        command=["-version"],
        mounts=[mount],
        user="1000:1000",
        remove=True,
        stderr=True,
        stdout=True,
    ).decode("utf-8", errors="replace")
    for line in output.splitlines():
        if "version" in line.lower():
            return line.strip()
    raise RuntimeError(f"Unexpected java -version output: {output.strip()[:300]}")


def _parse_version(version_line):
    m = re.search(r'"([^"]+)"', version_line or "")
    return m.group(1) if m else (version_line or "").strip()


SIDECAR_WORKDIR = "/work"
_STAGE_PREFIX = "[stage] "


def _own_image(client):
    """Image of the management container (the sidecar runs the same code)."""
    from api.post.server.mounts import get_own_container
    me = get_own_container()
    if me is not None:
        try:
            return me.attrs["Config"]["Image"]
        except Exception:
            pass
    return os.environ.get("MC_TOOL_IMAGE", "ghcr.io/dajda2371/minecraftservertool:latest")


def _install_job(runtime_id, archive_path=None, url=None):
    """
    Management-container side: spawn the download/extract sidecar, follow its
    log, then verify the extracted runtime.
    """
    import docker
    from api.post.server.mounts import volume_subpath_mount, SERVER_DATA_VOLUME, get_compose_labels
    from api.post.server.run import DOCKER_NETWORK

    rdir = runtime_dir(runtime_id)
    container_name = f"mc-java-{runtime_id}"
    client = docker.from_env()
    try:
        os.makedirs(rdir, exist_ok=True)

        cmd = ["python3", "-u", "-m", "api.java_runtimes", "install", "--work", SIDECAR_WORKDIR]
        if url:
            cmd += ["--url", url]
            _set(runtime_id, status="downloading")
        else:
            cmd += ["--archive", os.path.join(SIDECAR_WORKDIR, os.path.basename(archive_path))]
            _set(runtime_id, status="extracting")

        try:
            client.containers.get(container_name).remove(force=True)
        except docker.errors.NotFound:
            pass

        _log(runtime_id, f"Starting sidecar '{container_name}'")
        container = client.containers.run(
            image=_own_image(client),
            command=cmd,
            name=container_name,
            detach=True,
            mounts=[volume_subpath_mount(SIDECAR_WORKDIR, SERVER_DATA_VOLUME, f".java/{runtime_id}")],
            network=DOCKER_NETWORK,
            working_dir="/app",
            environment={"PYTHONUNBUFFERED": "1"},
            labels=get_compose_labels(f"java-{runtime_id}"),
        )

        tail = []
        for raw in container.logs(stream=True, follow=True):
            line = raw.decode("utf-8", errors="replace").rstrip()
            if not line:
                continue
            tail.append(line)
            tail = tail[-15:]
            _log(runtime_id, f"sidecar: {line}")
            if line.startswith(_STAGE_PREFIX):
                _set(runtime_id, status=line[len(_STAGE_PREFIX):].strip())

        exit_code = container.wait().get("StatusCode", -1)
        try:
            container.remove()
        except Exception:
            pass
        if exit_code != 0:
            raise RuntimeError("Install failed in sidecar: " + " | ".join(tail[-5:]))

        if not os.path.isfile(os.path.join(runtime_home(runtime_id), "bin", "java")):
            raise RuntimeError("Sidecar finished but no bin/java was produced.")

        _set(runtime_id, status="verifying")
        _log(runtime_id, "Verifying with java -version in a container")
        version_line = _verify_in_container(runtime_id)
        rt = api.db.get_java_runtime(runtime_id) or {}
        fields = {"status": "ready", "error": "", "version": _parse_version(version_line)}
        if not rt.get("vendor"):
            fields["vendor"] = version_line
        _set(runtime_id, **fields)
        _log(runtime_id, f"Ready: {version_line}")
    except Exception as e:
        _log(runtime_id, f"FAILED: {e}")
        _set(runtime_id, status="failed", error=str(e)[:1000])
        try:
            client.containers.get(container_name).remove(force=True)
        except Exception:
            pass


def install_in_sidecar(work, url=None, archive=None):
    """
    Sidecar side (runs inside mc-java-<id> with the runtime dir at ``work``):
    download (optional), extract, locate bin/java, move it to <work>/home and
    fix permissions. Progress is reported as "[stage] <status>" lines that the
    management container turns into runtime status updates.
    """
    os.makedirs(work, exist_ok=True)
    if url:
        print(f"{_STAGE_PREFIX}downloading", flush=True)
        ext = _archive_ext(url.split("?")[0]) or ".tar.gz"
        archive = os.path.join(work, f"archive{ext}")
        print(f"Downloading {url}", flush=True)
        _download(url, archive)
        print(f"Downloaded {os.path.getsize(archive)} bytes", flush=True)

    print(f"{_STAGE_PREFIX}extracting", flush=True)
    extract_dir = os.path.join(work, "extract")
    shutil.rmtree(extract_dir, ignore_errors=True)
    _extract(archive, extract_dir)
    home_src = _find_java_home(extract_dir)
    if not home_src:
        raise RuntimeError("No bin/java found in the archive (is it a Linux JDK/JRE?).")
    home = os.path.join(work, "home")
    shutil.rmtree(home, ignore_errors=True)
    shutil.move(home_src, home)
    shutil.rmtree(extract_dir, ignore_errors=True)
    try:
        os.remove(archive)
    except OSError:
        pass
    _fix_permissions(home)
    print(f"Runtime extracted to {home}", flush=True)


def _start(runtime_id, **kwargs):
    threading.Thread(target=_install_job, args=(runtime_id,), kwargs=kwargs, daemon=True).start()


def add_from_catalog(distribution, major_version):
    pkg = catalog_package(distribution, major_version)
    if not pkg:
        raise ValueError(f"No Linux/{host_architecture()} package for {distribution} {major_version}.")
    dist_name = next((d["name"] for d in list_distributions() if d["api_parameter"] == distribution), distribution)
    url = catalog_download_url(pkg["id"])
    runtime_id = uuid.uuid4().hex[:12]
    name = _safe_name(f"{dist_name} {pkg['java_version']} ({pkg['package_type'].upper()})")
    api.db.insert_java_runtime(runtime_id, name, dist_name, pkg["java_version"], f"catalog:{distribution}:{major_version}")
    _start(runtime_id, url=url)
    return runtime_id


def add_from_url(url, name=None):
    url = (url or "").strip()
    if not re.match(r"^https?://", url, re.I):
        raise ValueError("URL must start with http:// or https://")
    runtime_id = uuid.uuid4().hex[:12]
    display = _safe_name(name) if name else _safe_name(os.path.basename(url.split("?")[0]), "Custom runtime")
    api.db.insert_java_runtime(runtime_id, display, None, None, f"url:{url[:500]}")
    _start(runtime_id, url=url)
    return runtime_id


def add_from_upload(upload_file, filename, name=None):
    """``upload_file`` is a file-like object positioned at 0."""
    ext = _archive_ext(filename or "")
    if not ext:
        raise ValueError("Upload a .tar.gz, .tgz, .tar or .zip archive.")
    runtime_id = uuid.uuid4().hex[:12]
    rdir = runtime_dir(runtime_id)
    os.makedirs(rdir, exist_ok=True)
    archive_path = os.path.join(rdir, f"archive{ext}")
    with open(archive_path, "wb") as out:
        shutil.copyfileobj(upload_file, out, 1024 * 1024)
    display = _safe_name(name) if name else _safe_name(os.path.basename(filename), "Uploaded runtime")
    api.db.insert_java_runtime(runtime_id, display, None, None, f"upload:{os.path.basename(filename)[:200]}")
    _start(runtime_id, archive_path=archive_path)
    return runtime_id


def remove_runtime(runtime_id):
    users = api.db.servers_using_java_runtime(runtime_id)
    if users:
        raise ValueError(f"Runtime is selected by server(s): {', '.join(users)}. Change their Java runtime first.")
    # Stop a still-running install sidecar before deleting its working dir.
    try:
        import docker
        docker.from_env().containers.get(f"mc-java-{runtime_id}").remove(force=True)
    except Exception:
        pass
    api.db.delete_java_runtime(runtime_id)
    shutil.rmtree(runtime_dir(runtime_id), ignore_errors=True)


def list_runtimes():
    rts = api.db.get_java_runtimes()
    for rt in rts:
        rt["servers"] = api.db.servers_using_java_runtime(rt["id"])
    return rts


def resume_unfinished():
    """Mark jobs interrupted by a restart as failed so the UI does not spin forever."""
    for rt in api.db.get_java_runtimes():
        if rt["status"] in ("pending", "downloading", "extracting", "verifying"):
            if os.path.isfile(os.path.join(runtime_home(rt["id"]), "bin", "java")):
                _set(rt["id"], status="ready", error="")
            else:
                _set(rt["id"], status="failed", error="Interrupted by a management container restart. Add it again.")


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Java runtime install worker (runs inside the mc-java-<id> sidecar).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_install = sub.add_parser("install")
    p_install.add_argument("--work", required=True, help="Runtime directory (volume subpath mounted here)")
    p_install.add_argument("--url", help="Archive URL to download")
    p_install.add_argument("--archive", help="Already-present archive path inside --work")
    args = parser.parse_args()

    if args.cmd == "install":
        if not args.url and not args.archive:
            parser.error("--url or --archive is required")
        try:
            install_in_sidecar(args.work, url=args.url, archive=args.archive)
        except Exception as e:
            print(f"ERROR: {e}", flush=True)
            sys.exit(1)
