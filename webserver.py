import uvicorn
from api.fastapi_app import app

HOST = "0.0.0.0"
PORT = 8000

if __name__ == "__main__":
    print("--- Starting Webserver (FastAPI + Uvicorn) ---")
    print(f"Access the application via: http://{HOST}:{PORT}/")
    print("-------------------------------------------------------------")
    print("")
    
    # Run uvicorn webserver
    uvicorn.run(app, host=HOST, port=PORT)