import os
import uvicorn

if __name__ == "__main__":
    host = os.getenv("EMBER_HOST", "127.0.0.1")
    port = int(os.getenv("EMBER_PORT", "8000"))
    uvicorn.run("server.main:app", host=host, port=port, reload=False)
