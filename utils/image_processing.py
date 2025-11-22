from PIL import Image, ImageDraw, ImageFont
import os
from datetime import datetime

def add_timestamp_to_image(image_path, timestamp, latitude, longitude):
    """
    Add timestamp and location metadata overlay to the captured image
    """
    try:
        # Open the image
        with Image.open(image_path) as img:
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            draw = ImageDraw.Draw(img)
            
            # Try to use a font, fallback to default if not available
            try:
                font = ImageFont.truetype("arial.ttf", 30)
            except:
                font = ImageFont.load_default()
            
            # Format the text
            timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            location_str = f"Lat: {latitude:.6f}, Lon: {longitude:.6f}"
            
            # Add text background for better readability
            text = f"{timestamp_str}\n{location_str}"
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            # Draw background rectangle
            margin = 10
            draw.rectangle([
                margin, 
                margin, 
                margin + text_width + 10, 
                margin + text_height + 10
            ], fill='black')
            
            # Draw text
            draw.text((margin + 5, margin + 5), text, fill='white', font=font)
            
            # Save the modified image
            img.save(image_path)
            return True
            
    except Exception as e:
        print(f"Error adding timestamp to image: {e}")
        return False