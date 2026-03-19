import os
import logging
from logging.handlers import RotatingFileHandler
import http.server
import socketserver
from pathlib import Path
import datetime
import functools
import sys # For logging console output

from api.handler import Handler  # Add this import

HOST = "0.0.0.0"
PORT = 8000

# # --- Logger Setup ---
# LOGS_DIR = Path(__file__).parent.resolve() / 'data' / 'logs'
# LOGS_DIR.mkdir(parents=True, exist_ok=True)

# # Daily log filename (e.g., 2025-06-28.log)
# log_filename = datetime.datetime.now().strftime("%Y-%m-%d.log")
# log_path = LOGS_DIR / log_filename

# # Configure logger
# logger = logging.getLogger('Logger')
# logger.setLevel(logging.DEBUG)

# # Formatter
# formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# # File handler (log to file)
# file_handler = logging.FileHandler(log_path, encoding='utf-8')
# file_handler.setLevel(logging.DEBUG)
# file_handler.setFormatter(formatter)
# logger.addHandler(file_handler)

# # Console handler (log to terminal)
# console_handler = logging.StreamHandler()
# console_handler.setLevel(logging.DEBUG)
# console_handler.setFormatter(formatter)
# logger.addHandler(console_handler)

# # --- Redirect all print() output to logger ---
# class StreamToLogger:
#     def __init__(self, logger, level):
#         self.logger = logger
#         self.level = level
#         self.buffer = ''

#     def write(self, message):
#         message = message.rstrip()
#         if message:
#             self.logger.log(self.level, message)

#     def flush(self):
#         pass  # No need to flush anything here

# # Redirect print and errors to logger
# sys.stdout = StreamToLogger(logger, logging.INFO)
# sys.stderr = StreamToLogger(logger, logging.ERROR)
# # Example log
# logger.info("Logging directly to dated file: %s", log_filename)

# --- Main Execution ---

if __name__ == "__main__":
    print("--- Starting Webserver ---")

    # Initialize database on startup
    from api.db import init_db
    init_db()

    # Generate Velocity config (so supervisor can start Velocity with up-to-date config)
    try:
        from api.velocity import generate_velocity_toml, download_velocity
        download_velocity()
        generate_velocity_toml()
        print("[Startup] Velocity configuration generated.")
    except Exception as e:
        print(f"[Startup] Warning: Could not generate Velocity config: {e}")

    class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    # Define the directory to serve files from
    frontend_dir = Path(__file__).parent.resolve() / 'api' / 'get' / 'ui'

    # Create a handler that serves files from the specified directory.
    # We use functools.partial to pre-set the 'directory' argument for our Handler
    # before it's used by the server.
    handler_factory = functools.partial(Handler, directory=str(frontend_dir))

    httpd = ThreadingHTTPServer((HOST, PORT), handler_factory)

    print(f"\nServing HTTP on {HOST}:{PORT} from '{frontend_dir}'...")
    print(f"\nAccess the application via: http://{HOST}:{PORT}/")
    print("-------------------------------------------------------------")
    print("")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n--- KeyboardInterrupt received, shutting down server ---")
    finally:
        # Ensure server is properly shut down
        httpd.shutdown()
        httpd.server_close()
        print("--- Server stopped ---")