#!/bin/bash
# ============================================================================
# setup_velocity.sh — Download Velocity and generate initial configuration
# ============================================================================
# Run this once inside the management container (or locally for testing)
# to download the Velocity proxy JAR and create the initial velocity.toml.
#
# Usage:
#   ./setup_velocity.sh
# ============================================================================

set -e

VELOCITY_DIR="data/velocity"
VELOCITY_JAR="$VELOCITY_DIR/velocity.jar"

mkdir -p "$VELOCITY_DIR"

if [ -f "$VELOCITY_JAR" ]; then
    echo "[Velocity] velocity.jar already exists at $VELOCITY_JAR"
    echo "[Velocity] Delete it manually if you want to re-download."
else
    echo "[Velocity] Fetching latest Velocity version info..."
    
    # Get latest version from PaperMC API
    VERSION=$(curl -s https://api.papermc.io/v2/projects/velocity | python3 -c "import sys,json; print(json.load(sys.stdin)['versions'][-1])")
    echo "[Velocity] Latest version: $VERSION"
    
    # Get latest build number
    BUILD=$(curl -s "https://api.papermc.io/v2/projects/velocity/versions/$VERSION/builds" | python3 -c "import sys,json; print(json.load(sys.stdin)['builds'][-1]['build'])")
    echo "[Velocity] Latest build: $BUILD"
    
    # Download
    URL="https://api.papermc.io/v2/projects/velocity/versions/$VERSION/builds/$BUILD/downloads/velocity-$VERSION-$BUILD.jar"
    echo "[Velocity] Downloading from $URL..."
    wget -q -O "$VELOCITY_JAR" "$URL"
    echo "[Velocity] Downloaded velocity.jar"
fi

# Generate initial config using the Python tool
echo "[Velocity] Generating initial velocity.toml..."
python3 -c "from api.velocity import generate_velocity_toml; generate_velocity_toml()"

echo "[Velocity] Setup complete!"
echo ""
echo "Files created:"
ls -la "$VELOCITY_DIR/"
