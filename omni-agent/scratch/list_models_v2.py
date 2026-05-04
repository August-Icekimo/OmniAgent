import os
from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

print("Available Models:")
for m in client.models.list():
    print(f"- {m.name}: {m.supported_generation_methods}")
