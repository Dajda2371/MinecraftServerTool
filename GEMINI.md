# Project Overview

This project is a Python-based tool for managing Minecraft servers. It provides both a command-line interface (CLI) and a web interface to create, run, and interact with servers.

## Key Technologies

*   **Backend:** Python
*   **CLI:** Python `argparse` (in `cli.py`)
*   **Web Server:** Python's built-in `http.server` and `socketserver` (in `webserver.py`)
*   **API:** A simple REST-like API handled by a custom request handler in `api/handler.py`.
*   **Frontend:** HTML, CSS, and JavaScript (located in `api/get/ui/`)

## Architecture

The project is structured into three main components:

1.  **`cli.py`:** Implements the command-line interface. It parses user commands and calls the appropriate functions in the `api` module.
2.  **`webserver.py`:** Runs a simple web server to serve the web interface and handle API requests.
3.  **`api/` directory:** Contains the core logic of the application. It's further divided into `get` and `post` subdirectories, which hold the handlers for different HTTP methods.

# Building and Running

## Running the CLI

To run the command-line interface, execute the `cli.py` file:

```bash
python3 cli.py
```

## Running the Web Server

To run the web server, execute the `webserver.py` file:

```bash
python3 webserver.py
```

The web interface will be accessible at `http://localhost:8000`.

# Development Conventions

*   **Modularity:** The code is organized into modules based on functionality (CLI, web server, API).
*   **API Structure:** The `api` directory is structured by HTTP method (`get`, `post`) and then by resource (`server`, etc.).
*   **Frontend:** The frontend code is kept separate from the backend code in the `api/get/ui` directory.

# Server Creation

The `api/post/server/create.py` script handles the creation of new Minecraft servers.

## Supported Server Types

*   **Spigot:** Fully supported.
*   **Vanilla:** Not yet implemented.
*   **Paper:** Not yet implemented.

## Dependencies

*   **`wget`:** This tool is required to download the server files. It can be installed on macOS with `brew install wget` or on Debian/Ubuntu with `sudo apt-get install wget`.
*   **Java:** A specific Java version is required to build Spigot servers. The script attempts to handle this by installing the correct version if it's not found.
