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

def analyze_water_gauge(image_path):
    """
    Analyze the image using Gemini API to read the water level gauge.
    Returns a dictionary:
    {
        "water_level": float or None,
        "confidence": float (0.0 to 1.0),
        "is_valid": bool,
        "reason": str
    }
    """
    import google.generativeai as genai
    import json
    
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        print("GEMINI_API_KEY not found in environment variables.")
        return None
        
    try:
        genai.configure(api_key=api_key)
        
        # Set up the model
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        # Load the image
        img = Image.open(image_path)
        
        # Prompt for the model
        prompt = """
        Analyze this image of a water level gauge. 
        Return a JSON object with the following fields:
        - "water_level": The numeric value in meters (float). If not visible, use null.
        - "confidence": A score from 0.0 to 1.0 indicating how sure you are.
        - "is_valid": Boolean, true if the image clearly shows a water gauge, false if blurry or irrelevant.
        - "reason": A short string explaining the result (e.g., "Clear reading", "Image too blurry", "No gauge found").
        
        Return ONLY the JSON string. No markdown formatting.
        """
        
        response = model.generate_content([prompt, img])
        text = response.text.strip()
        
        # Clean up potential markdown code blocks
        if text.startswith('```json'):
            text = text[7:]
        if text.endswith('```'):
            text = text[:-3]
        text = text.strip()
        
        print(f"Gemini AI Response: {text}")
        
        try:
            result = json.loads(text)
            return result
        except json.JSONDecodeError:
            print(f"Could not parse AI response as JSON: {text}")
            return None
            
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return None