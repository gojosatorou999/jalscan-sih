"""
Flask API for Flood Prediction and Visualization
=================================================
Provides endpoints for flood prediction using physics engine
and GAN-based visualization.

Author: JalScan Team
"""

import os
import base64
import json
import logging
import random
from io import BytesIO
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

import numpy as np
from flask import Blueprint, request, jsonify, current_app, url_for, send_file
from PIL import Image

from .physics_engine import FloodMaskGenerator, generate_synthetic_dem
from .model import create_simple_flood_overlay

logger = logging.getLogger(__name__)

# Create Blueprint
flood_bp = Blueprint('flood', __name__, url_prefix='/api/flood')

# ============================================================================
# CONFIGURATION
# ============================================================================

# Demo mode flag - set to True for hackathon demo
DEMO_MODE = True

# Demo images directory
DEMO_IMAGES_DIR = os.path.join(os.path.dirname(__file__), 'demo_images')

# Google Maps Static API Key (set via environment variable)
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')

# SRTM Data directory (if available)
SRTM_DATA_DIR = os.environ.get('SRTM_DATA_DIR', '')


# ============================================================================
# DEMO MODE DATA
# ============================================================================

DEMO_SCENARIOS = [
    {
        'id': 'hyderabad_musi',
        'name': 'Musi River, Hyderabad',
        'lat': 17.3850,
        'lon': 78.4867,
        'description': 'Flood simulation showing Musi River overflow in Hyderabad city',
        'stats': {
            'flooded_area_km2': 12.5,
            'flooded_percentage': 18.3,
            'max_depth_m': 3.2,
            'mean_depth_m': 1.4
        }
    },
    {
        'id': 'mumbai_mithi',
        'name': 'Mithi River, Mumbai',
        'lat': 19.0760,
        'lon': 72.8777,
        'description': 'Flash flood scenario in Mumbai urban area',
        'stats': {
            'flooded_area_km2': 8.7,
            'flooded_percentage': 15.2,
            'max_depth_m': 2.8,
            'mean_depth_m': 1.1
        }
    },
    {
        'id': 'chennai_adyar',
        'name': 'Adyar River, Chennai',
        'lat': 13.0827,
        'lon': 80.2707,
        'description': 'Monsoon flood simulation for Chennai coastal areas',
        'stats': {
            'flooded_area_km2': 15.3,
            'flooded_percentage': 22.1,
            'max_depth_m': 4.1,
            'mean_depth_m': 1.8
        }
    }
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def fetch_satellite_image(
    lat: float,
    lon: float,
    zoom: int = 15,
    size: Tuple[int, int] = (512, 512)
) -> Optional[np.ndarray]:
    """
    Fetch satellite image from Google Maps Static API.
    
    Args:
        lat: Latitude
        lon: Longitude
        zoom: Zoom level (1-21)
        size: Image size (width, height)
    
    Returns:
        RGB image as numpy array or None if failed
    """
    if not GOOGLE_MAPS_API_KEY:
        logger.warning("Google Maps API key not configured")
        return None
    
    try:
        import requests
        
        url = (
            f"https://maps.googleapis.com/maps/api/staticmap?"
            f"center={lat},{lon}&zoom={zoom}&size={size[0]}x{size[1]}"
            f"&maptype=satellite&key={GOOGLE_MAPS_API_KEY}"
        )
        
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        image = Image.open(BytesIO(response.content))
        return np.array(image.convert('RGB'))
    
    except Exception as e:
        logger.error(f"Failed to fetch satellite image: {e}")
        return None


def fetch_srtm_elevation(
    lat: float,
    lon: float,
    radius_km: float = 5.0
) -> Optional[np.ndarray]:
    """
    Fetch SRTM elevation data for the specified region.
    
    Args:
        lat: Center latitude
        lon: Center longitude
        radius_km: Radius in kilometers
    
    Returns:
        DEM as numpy array or None if not available
    """
    # In production, this would load actual SRTM GeoTIFF data
    # For now, we generate synthetic data with location-based patterns
    logger.info(f"Generating synthetic DEM for ({lat}, {lon})")
    
    dem, river_mask = generate_synthetic_dem(
        size=(256, 256),
        base_elevation=100.0,
        river_depth=5.0,
        terrain_variation=10.0,
        lat=lat,
        lon=lon
    )
    
    return dem


def generate_demo_flood_image(
    lat: float,
    lon: float,
    water_level_rise: float = 2.0
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    Generate a demo flood image for hackathon presentation.
    Uses location coordinates to generate unique flood patterns.
    
    Args:
        lat: Latitude for location-based pattern generation
        lon: Longitude for location-based pattern generation
        water_level_rise: Simulated water level rise in meters
    
    Returns:
        Tuple of (flood_image, statistics)
    """
    # Find scenario info for stats
    scenario_index = find_closest_scenario(lat, lon)
    scenario = DEMO_SCENARIOS[scenario_index % len(DEMO_SCENARIOS)]
    
    # Generate location-specific DEM and river pattern
    dem, river_mask = generate_synthetic_dem(
        lat=lat,
        lon=lon,
        terrain_variation=8.0 + (abs(lat) % 5)  # Vary terrain roughness by location
    )
    
    # Create a gradient satellite-like image with location-based colors
    height, width = dem.shape
    satellite = np.zeros((height, width, 3), dtype=np.uint8)
    
    # Use location to vary base colors (simulating different terrain types)
    color_seed = int(abs(lat * 100 + lon * 10)) % 50
    base_r = 70 + color_seed // 2
    base_g = 110 + color_seed
    base_b = 50 + color_seed // 3
    
    # Green/brown base (land) with terrain shading
    dem_norm = (dem - dem.min()) / (dem.max() - dem.min() + 0.01)
    satellite[:, :, 0] = np.clip(base_r + dem_norm * 40, 0, 255).astype(np.uint8)
    satellite[:, :, 1] = np.clip(base_g + dem_norm * 50, 0, 255).astype(np.uint8)
    satellite[:, :, 2] = np.clip(base_b + dem_norm * 30, 0, 255).astype(np.uint8)
    
    # Add river (blue variations based on location)
    river_blue = 140 + int(lat % 20)
    satellite[river_mask == 1, 0] = 35 + int(lon % 15)
    satellite[river_mask == 1, 1] = 70 + int(lat % 20)
    satellite[river_mask == 1, 2] = river_blue
    
    # Generate flood mask using physics engine
    generator = FloodMaskGenerator(roughness_coefficient=0.035)
    base_level = 95.0
    
    # Scale water level rise by user input
    actual_rise = water_level_rise * 1.5
    
    flood_mask, stats = generator.calculate_flood_extent(
        dem=dem,
        base_water_level=base_level,
        water_level_rise=actual_rise
    )
    
    # Create flood overlay with location-based color variations
    flood_r = 60 + int(abs(lat) % 20)
    flood_g = 100 + int(abs(lon) % 20)
    flood_b = 210 + int((abs(lat) + abs(lon)) % 30)
    
    flood_image = create_simple_flood_overlay(
        satellite_image=satellite,
        flood_mask=flood_mask,
        flood_color=(flood_r, flood_g, min(flood_b, 255)),
        opacity=0.55
    )
    
    # Add scenario info to stats
    stats['scenario'] = scenario
    stats['generated_at'] = datetime.utcnow().isoformat()
    
    return flood_image, stats


def image_to_base64(image: np.ndarray) -> str:
    """Convert numpy image to base64 string."""
    pil_image = Image.fromarray(image)
    buffer = BytesIO()
    pil_image.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


def save_generated_image(image: np.ndarray, filename: str) -> str:
    """Save generated image and return its URL path."""
    output_dir = os.path.join(current_app.static_folder, 'flood_outputs')
    os.makedirs(output_dir, exist_ok=True)
    
    filepath = os.path.join(output_dir, filename)
    Image.fromarray(image).save(filepath)
    
    return f'/static/flood_outputs/{filename}'


# ============================================================================
# API ROUTES
# ============================================================================

@flood_bp.route('/predict', methods=['POST'])
def predict_flood():
    """
    Main flood prediction endpoint.
    
    Request JSON:
    {
        "lat": float,          # Latitude
        "lon": float,          # Longitude
        "water_level_rise": float  # Expected water level rise in meters
    }
    
    Response JSON:
    {
        "success": true,
        "demo_mode": true/false,
        "image_url": "/static/flood_outputs/flood_xxx.png",
        "image_base64": "...",
        "statistics": {
            "flooded_area_km2": float,
            "flooded_percentage": float,
            "max_depth_m": float,
            "mean_depth_m": float,
            "water_level_m": float
        },
        "overlay_bounds": {
            "north": float,
            "south": float,
            "east": float,
            "west": float
        }
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'No JSON data provided'}), 400
        
        lat = data.get('lat')
        lon = data.get('lon')
        water_level_rise = data.get('water_level_rise', 2.0)
        
        if lat is None or lon is None:
            return jsonify({'success': False, 'error': 'lat and lon are required'}), 400
        
        # Validate coordinates
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return jsonify({'success': False, 'error': 'Invalid coordinates'}), 400
        
        if not (0 < water_level_rise <= 20):
            return jsonify({'success': False, 'error': 'water_level_rise must be between 0 and 20 meters'}), 400
        
        logger.info(f"Flood prediction request: lat={lat}, lon={lon}, rise={water_level_rise}m")
        
        # ================================================================
        # DEMO MODE - Use pre-generated images for smooth hackathon demo
        # ================================================================
        if DEMO_MODE:
            # Generate flood image with location-based unique patterns
            flood_image, stats = generate_demo_flood_image(lat, lon, water_level_rise)
            
            # Save and get URL
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'flood_demo_{timestamp}.png'
            image_url = save_generated_image(flood_image, filename)
            
            # Calculate overlay bounds (approximate 5km radius)
            delta = 0.045  # ~5km at equator
            overlay_bounds = {
                'north': lat + delta,
                'south': lat - delta,
                'east': lon + delta,
                'west': lon - delta
            }
            
            return jsonify({
                'success': True,
                'demo_mode': True,
                'image_url': image_url,
                'image_base64': image_to_base64(flood_image),
                'statistics': stats,
                'overlay_bounds': overlay_bounds,
                'message': 'Demo mode: Using synthetic data for visualization'
            })
        
        # ================================================================
        # PRODUCTION MODE - Full pipeline
        # ================================================================
        
        # Step 1: Fetch satellite image
        satellite_image = fetch_satellite_image(lat, lon)
        if satellite_image is None:
            # Use synthetic image if API not available
            satellite_image = np.zeros((256, 256, 3), dtype=np.uint8)
            satellite_image[:, :, 1] = 100  # Green background
        
        # Step 2: Fetch SRTM elevation data
        dem = fetch_srtm_elevation(lat, lon)
        
        # Step 3: Run physics engine to generate flood mask
        generator = FloodMaskGenerator()
        flood_mask, stats = generator.calculate_flood_extent(
            dem=dem,
            base_water_level=95.0,  # Assumed base level
            water_level_rise=water_level_rise
        )
        
        # Step 4: Generate flood visualization
        # In production, this would use the trained FloodGAN
        # For now, use simple overlay
        flood_image = create_simple_flood_overlay(
            satellite_image=satellite_image,
            flood_mask=flood_mask,
            opacity=0.6
        )
        
        # Save and return
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'flood_{lat:.4f}_{lon:.4f}_{timestamp}.png'
        image_url = save_generated_image(flood_image, filename)
        
        # Calculate overlay bounds
        delta = 0.045
        overlay_bounds = {
            'north': lat + delta,
            'south': lat - delta,
            'east': lon + delta,
            'west': lon - delta
        }
        
        return jsonify({
            'success': True,
            'demo_mode': False,
            'image_url': image_url,
            'image_base64': image_to_base64(flood_image),
            'statistics': stats,
            'overlay_bounds': overlay_bounds
        })
    
    except Exception as e:
        logger.exception(f"Error in flood prediction: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@flood_bp.route('/demo', methods=['GET'])
def get_demo_scenarios():
    """
    Get available demo scenarios.
    
    Response JSON:
    {
        "success": true,
        "demo_mode": true/false,
        "scenarios": [...]
    }
    """
    return jsonify({
        'success': True,
        'demo_mode': DEMO_MODE,
        'scenarios': DEMO_SCENARIOS
    })


@flood_bp.route('/demo/<scenario_id>', methods=['GET'])
def get_demo_scenario(scenario_id: str):
    """
    Get a specific demo scenario with pre-generated flood image.
    
    Args:
        scenario_id: ID of the demo scenario
    
    Query Parameters:
        water_level_rise: Optional water level rise in meters (default: 2.0)
    """
    # Find scenario
    scenario = None
    scenario_index = 0
    for i, s in enumerate(DEMO_SCENARIOS):
        if s['id'] == scenario_id:
            scenario = s
            scenario_index = i
            break
    
    if not scenario:
        return jsonify({'success': False, 'error': 'Scenario not found'}), 404
    
    water_level_rise = request.args.get('water_level_rise', 2.0, type=float)
    
    # Generate flood image with location-specific patterns
    flood_image, stats = generate_demo_flood_image(scenario['lat'], scenario['lon'], water_level_rise)
    
    # Save image
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f'flood_{scenario_id}_{timestamp}.png'
    image_url = save_generated_image(flood_image, filename)
    
    # Calculate overlay bounds
    delta = 0.045
    overlay_bounds = {
        'north': scenario['lat'] + delta,
        'south': scenario['lat'] - delta,
        'east': scenario['lon'] + delta,
        'west': scenario['lon'] - delta
    }
    
    return jsonify({
        'success': True,
        'scenario': scenario,
        'image_url': image_url,
        'image_base64': image_to_base64(flood_image),
        'statistics': stats,
        'overlay_bounds': overlay_bounds
    })


@flood_bp.route('/toggle-demo', methods=['POST'])
def toggle_demo_mode():
    """Toggle demo mode on/off (admin only)."""
    global DEMO_MODE
    
    data = request.get_json() or {}
    
    if 'enabled' in data:
        DEMO_MODE = bool(data['enabled'])
    else:
        DEMO_MODE = not DEMO_MODE
    
    logger.info(f"Demo mode {'enabled' if DEMO_MODE else 'disabled'}")
    
    return jsonify({
        'success': True,
        'demo_mode': DEMO_MODE
    })


@flood_bp.route('/status', methods=['GET'])
def get_status():
    """Get the status of the flood prediction service."""
    return jsonify({
        'success': True,
        'service': 'Flood Synthesis API',
        'version': '1.0.0',
        'demo_mode': DEMO_MODE,
        'google_maps_configured': bool(GOOGLE_MAPS_API_KEY),
        'srtm_data_available': bool(SRTM_DATA_DIR) and os.path.isdir(SRTM_DATA_DIR),
        'available_scenarios': len(DEMO_SCENARIOS)
    })


def find_closest_scenario(lat: float, lon: float) -> int:
    """Find the closest demo scenario to the given coordinates."""
    min_distance = float('inf')
    closest_index = 0
    
    for i, scenario in enumerate(DEMO_SCENARIOS):
        # Simple Euclidean distance (good enough for demo)
        distance = ((lat - scenario['lat'])**2 + (lon - scenario['lon'])**2)**0.5
        if distance < min_distance:
            min_distance = distance
            closest_index = i
    
    return closest_index


# ============================================================================
# INITIALIZATION
# ============================================================================

def init_app(app):
    """
    Initialize the flood synthesis module with the Flask app.
    
    Args:
        app: Flask application instance
    """
    # Register blueprint
    app.register_blueprint(flood_bp)
    
    # Create output directory
    output_dir = os.path.join(app.static_folder, 'flood_outputs')
    os.makedirs(output_dir, exist_ok=True)
    
    # Create demo images directory
    os.makedirs(DEMO_IMAGES_DIR, exist_ok=True)
    
    logger.info("Flood Synthesis module initialized")
    logger.info(f"Demo mode: {'ON' if DEMO_MODE else 'OFF'}")
