import os
import asyncio
from google import genai
from google.oauth2.credentials import Credentials
from dotenv import load_dotenv

async def list_models():
    # Load environment variables from .env file
    load_dotenv()
    
    refresh_token = os.getenv("GEMINI_REFRESH_TOKEN", "")
    client_id = os.getenv("GEMINI_CLIENT_ID", "")
    client_secret = os.getenv("GEMINI_CLIENT_SECRET", "")
    
    if not all([refresh_token, client_id, client_secret]):
        print("Warning: Some OAuth credentials are missing in .env")
        print("Required: GEMINI_REFRESH_TOKEN, GEMINI_CLIENT_ID, GEMINI_CLIENT_SECRET")
    
    from google.auth.transport.requests import Request
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret
    )
    
    try:
        creds.refresh(Request())
        client = genai.Client(credentials=creds)
        print("Available models for this OAuth credential:")
        for model in client.models.list():
            print(f"- {model.name}")
    except Exception as e:
        print(f"Error listing models: {e}")

if __name__ == "__main__":
    asyncio.run(list_models())

