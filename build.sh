#!/bin/bash
# ============================================================================
# Minecraft Server Tool — Build & Management Script
# ============================================================================
# This script handles the lifecycle of the Minecraft Server Tool Docker-based
# infrastructure, including the management UI and Velocity proxy.
# ============================================================================

set -e

# --- Configuration ---
PROJECT_NAME="minecraft-server-tool"
DOCKER_COMPOSE_FILE="docker-compose.yml"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# --- Helper Functions ---
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

check_docker() {
    if ! docker info > /dev/null 2>&1; then
        log_error "Docker is not running. Please start Docker Desktop first."
        exit 1
    fi
}

# --- Command Logic ---
case "$1" in
    "build" | "up" | "")
        check_docker
        log_info "Building and starting containers..."
        docker compose -p "$PROJECT_NAME" up -d --build
        log_success "Infrastructure is up and running!"
        log_info "Web UI: http://localhost:8000"
        log_info "Velocity Proxy: localhost:25565"
        ;;

    "stop" | "down")
        check_docker
        log_info "Stopping containers..."
        docker compose -p "$PROJECT_NAME" down
        log_success "Infrastructure stopped."
        ;;

    "restart")
        check_docker
        log_info "Restarting infrastructure..."
        docker compose -p "$PROJECT_NAME" restart
        log_success "Restart complete."
        ;;

    "logs")
        check_docker
        log_info "Displaying logs (Ctrl+C to exit)..."
        docker compose -p "$PROJECT_NAME" logs -f
        ;;

    "ps" | "status")
        check_docker
        docker compose -p "$PROJECT_NAME" ps
        ;;

    "clean")
        check_docker
        log_warn "This will remove all containers and images for this project."
        read -p "Are you sure? (y/N) " confirm
        if [[ $confirm == [yY] ]]; then
            docker compose -p "$PROJECT_NAME" down --rmi all --volumes --remove-orphans
            log_success "Project cleaned."
        else
            log_info "Cleaning cancelled."
        fi
        ;;

    "help" | *)
        echo "Usage: ./build.sh [command]"
        echo ""
        echo "Commands:"
        echo "  up (default)  Build and start the project in Docker"
        echo "  stop          Stop the project containers"
        echo "  restart       Restart the containers"
        echo "  logs          Follow container logs"
        echo "  ps            Show container status"
        echo "  clean         Remove project containers, images, and volumes"
        echo "  help          Show this message"
        ;;
esac
