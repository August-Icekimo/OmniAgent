import os
import gzip
import json
import logging
from lottie.exporters.cairo import export_png
from lottie.objects import Animation

logger = logging.getLogger(__name__)

def tgs_to_png(tgs_path, png_path):
    """
    Converts a .tgs (Gzipped Lottie) file to a static .png image (first frame).
    """
    temp_json = tgs_path + ".json"
    try:
        # 1. Gunzip
        with gzip.open(tgs_path, 'rb') as f_in:
            with open(temp_json, 'wb') as f_out:
                f_out.write(f_in.read())
        
        # 2. Load Lottie
        with open(temp_json, 'r') as f:
            data = json.load(f)
            animation = Animation.load(data)
        
        # 3. Export first frame to PNG
        # Note: frame 0 is the start
        export_png(animation, png_path, frame=0)
        
        return True
    except Exception as e:
        logger.error(f"Failed to convert TGS to PNG: {e}")
        return False
    finally:
        if os.path.exists(temp_json):
            os.remove(temp_json)

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python tgs_converter.py <input.tgs> <output.png>")
        sys.exit(1)
    tgs_to_png(sys.argv[1], sys.argv[2])
