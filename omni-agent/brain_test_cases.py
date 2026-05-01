import httpx
import json
import uuid

BRAIN_URL = "http://localhost:8000/chat"
USER_ID = "d63031e6-c612-4118-a2ba-97ef13edcad0"

def test_multimodal(message_text, local_path, mime_type, media_type):
    payload = {
        "id": str(uuid.uuid4()),
        "source_message_id": "test_src_id_" + str(uuid.uuid4())[:8],
        "platform": "telegram",
        "user_id": USER_ID,
        "message_type": media_type,
        "text": message_text,
        "attachment": {
            "file_id": "test_file_id",
            "file_name": local_path.split("/")[-1],
            "mime_type": mime_type,
            "size_bytes": 1024, # Dummy
            "local_path": local_path,
            "media_type": media_type
        }
    }
    
    print(f"\n>>> Testing {media_type}: '{message_text}'")
    print(f">>> Attachment: {local_path}")
    
    try:
        response = httpx.post(BRAIN_URL, json=payload, timeout=90.0)
        response.raise_for_status()
        result = response.json()
        print(f"<<< Reply: {result['reply_text']}")
        print(f"<<< Model: {result['model_used']} ({result['provider']})")
    except Exception as e:
        print(f"!!! Error: {e}")

if __name__ == "__main__":
    # Real TGS file from logs
    test_multimodal("這是什麼貼圖？", "/workspace/uploads/d63031e6-c612-4118-a2ba-97ef13edcad0/1777651312_sticker.webp", "image/webp", "tgs_sticker")
