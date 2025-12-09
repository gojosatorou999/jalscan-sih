"""
Physics Engine for Flood Prediction
====================================
Implements hydraulic calculations using Manning's Equation
to generate flood masks from terrain elevation data.

Author: JalScan Team
"""

import numpy as np
from typing import Tuple, Optional
import logging

logger = logging.getLogger(__name__)


def calculate_mannings_velocity(
    hydraulic_radius: float,
    slope: float,
    roughness_coefficient: float = 0.035
) -> float:
    """
    Calculate water flow velocity using Manning's Equation.
    
    V = (1/n) * R^(2/3) * S^(1/2)
    
    Where:
        V = velocity (m/s)
        n = Manning's roughness coefficient (dimensionless)
        R = hydraulic radius (m) - cross-sectional area / wetted perimeter
        S = slope of energy grade line (m/m)
    
    Args:
        hydraulic_radius: The hydraulic radius in meters (Area/Wetted Perimeter)
        slope: The slope of the channel/terrain (rise/run)
        roughness_coefficient: Manning's n coefficient (default 0.035 for natural channels)
            - 0.025-0.030: Clean, straight, full stage
            - 0.030-0.040: Main channels with vegetation
            - 0.040-0.070: Floodplains with dense vegetation
    
    Returns:
        Flow velocity in meters per second
    """
    if slope <= 0:
        return 0.0
    if hydraulic_radius <= 0:
        return 0.0
    
    velocity = (1 / roughness_coefficient) * (hydraulic_radius ** (2/3)) * (slope ** 0.5)
    return velocity


def calculate_flood_depth(
    water_level: float,
    terrain_elevation: float
) -> float:
    """
    Calculate flood depth at a point.
    
    Args:
        water_level: Current water level (m above datum)
        terrain_elevation: Ground elevation (m above datum)
    
    Returns:
        Flood depth in meters (0 if not flooded)
    """
    depth = water_level - terrain_elevation
    return max(0.0, depth)


class FloodMaskGenerator:
    """
    Generates binary flood masks from terrain elevation data
    using physics-based hydrological modeling.
    """
    
    def __init__(
        self,
        roughness_coefficient: float = 0.035,
        min_flood_depth: float = 0.1  # meters
    ):
        """
        Initialize the flood mask generator.
        
        Args:
            roughness_coefficient: Manning's n for the terrain
            min_flood_depth: Minimum depth to consider as flooded (m)
        """
        self.roughness_coefficient = roughness_coefficient
        self.min_flood_depth = min_flood_depth
    
    def generate_mask_from_dem(
        self,
        dem: np.ndarray,
        water_level: float,
        river_mask: Optional[np.ndarray] = None,
        pixel_size: float = 30.0  # meters per pixel (SRTM resolution)
    ) -> np.ndarray:
        """
        Generate a binary flood mask from Digital Elevation Model (DEM).
        
        Algorithm:
        1. Identify areas below the water level
        2. Apply flood fill from river/water source
        3. Consider hydraulic connectivity
        
        Args:
            dem: 2D numpy array of terrain elevations (meters)
            water_level: Water level in meters above datum
            river_mask: Optional binary mask of river channel locations
            pixel_size: Size of each pixel in meters
        
        Returns:
            Binary flood mask (1 = flooded, 0 = dry)
        """
        # Step 1: Basic inundation - areas below water level
        flood_mask = (dem <= water_level).astype(np.uint8)
        
        # Step 2: Apply minimum depth threshold
        depth_map = water_level - dem
        depth_map = np.maximum(depth_map, 0)
        flood_mask = (depth_map >= self.min_flood_depth).astype(np.uint8)
        
        # Step 3: If river mask provided, use flood fill for connectivity
        if river_mask is not None:
            flood_mask = self._apply_hydraulic_connectivity(
                flood_mask, river_mask, dem, water_level
            )
        
        return flood_mask
    
    def _apply_hydraulic_connectivity(
        self,
        flood_mask: np.ndarray,
        river_mask: np.ndarray,
        dem: np.ndarray,
        water_level: float
    ) -> np.ndarray:
        """
        Ensure flood areas are hydraulically connected to water source.
        Uses a simple flood-fill algorithm from river locations.
        """
        from scipy import ndimage
        
        # Label connected regions in the potential flood area
        labeled, num_features = ndimage.label(flood_mask)
        
        # Find which regions are connected to the river
        connected_mask = np.zeros_like(flood_mask)
        
        for region_id in range(1, num_features + 1):
            region = labeled == region_id
            # Check if this region overlaps with river
            if np.any(region & river_mask):
                connected_mask[region] = 1
        
        return connected_mask
    
    def calculate_flood_extent(
        self,
        dem: np.ndarray,
        base_water_level: float,
        water_level_rise: float,
        pixel_size: float = 30.0
    ) -> Tuple[np.ndarray, dict]:
        """
        Calculate flood extent given a water level rise.
        
        Args:
            dem: Digital Elevation Model array
            base_water_level: Current water level before rise
            water_level_rise: Expected rise in water level (meters)
            pixel_size: Size of each pixel in meters
        
        Returns:
            Tuple of (flood_mask, statistics)
        """
        new_water_level = base_water_level + water_level_rise
        
        # Generate the flood mask
        flood_mask = self.generate_mask_from_dem(
            dem=dem,
            water_level=new_water_level,
            pixel_size=pixel_size
        )
        
        # Calculate depth map
        depth_map = np.maximum(new_water_level - dem, 0) * flood_mask
        
        # Calculate statistics
        flooded_pixels = np.sum(flood_mask)
        total_pixels = dem.size
        flooded_area_km2 = (flooded_pixels * pixel_size * pixel_size) / 1_000_000
        
        stats = {
            'flooded_area_km2': round(flooded_area_km2, 3),
            'flooded_percentage': round(100 * flooded_pixels / total_pixels, 2),
            'max_depth_m': round(float(np.max(depth_map)), 2),
            'mean_depth_m': round(float(np.mean(depth_map[flood_mask == 1])) if flooded_pixels > 0 else 0, 2),
            'water_level_m': round(new_water_level, 2),
            'water_level_rise_m': round(water_level_rise, 2)
        }
        
        logger.info(f"Generated flood mask: {stats}")
        
        return flood_mask, stats
    
    def estimate_flow_velocity_map(
        self,
        dem: np.ndarray,
        flood_mask: np.ndarray,
        water_level: float,
        pixel_size: float = 30.0
    ) -> np.ndarray:
        """
        Estimate flow velocity at each flooded cell.
        
        Uses simplified Manning's equation assuming:
        - Hydraulic radius ≈ flood depth (for wide shallow flows)
        - Slope calculated from DEM gradient
        
        Returns:
            Velocity map in m/s
        """
        # Calculate depth
        depth = np.maximum(water_level - dem, 0.01)  # Avoid division by zero
        
        # Calculate slope from DEM gradient
        grad_y, grad_x = np.gradient(dem, pixel_size)
        slope = np.sqrt(grad_x**2 + grad_y**2)
        slope = np.maximum(slope, 0.0001)  # Minimum slope
        
        # Apply Manning's equation at each cell
        # V = (1/n) * R^(2/3) * S^(1/2)
        # Assuming R ≈ depth for wide shallow flow
        velocity = (1 / self.roughness_coefficient) * (depth ** (2/3)) * (slope ** 0.5)
        
        # Apply flood mask
        velocity = velocity * flood_mask
        
        return velocity


def generate_synthetic_dem(
    size: Tuple[int, int] = (256, 256),
    base_elevation: float = 100.0,
    river_depth: float = 5.0,
    terrain_variation: float = 10.0,
    lat: float = None,
    lon: float = None
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Generate a synthetic DEM with a river channel for testing.
    Uses location-based seeding for unique patterns per location.
    
    Args:
        size: (height, width) of the DEM
        base_elevation: Base terrain elevation
        river_depth: Depth of the river channel
        terrain_variation: Random terrain variation
        lat: Latitude for location-based seeding
        lon: Longitude for location-based seeding
    
    Returns:
        Tuple of (dem, river_mask)
    """
    height, width = size
    
    # Use location-based seed for unique patterns per location
    if lat is not None and lon is not None:
        # Create a unique seed from coordinates
        seed = int(abs(lat * 10000 + lon * 100)) % (2**31)
    else:
        seed = 42
    
    np.random.seed(seed)
    
    # Create base terrain with some random variation
    dem = base_elevation + np.random.randn(height, width) * terrain_variation
    
    # Create river pattern based on location
    river_mask = np.zeros((height, width), dtype=np.uint8)
    
    # Vary river characteristics based on location
    river_amplitude = 20 + int((abs(lat or 17) % 10) * 3)  # 20-50 meander amplitude
    river_frequency = 15 + int((abs(lon or 78) % 10) * 2)  # 15-35 frequency
    river_width_base = 15 + int(((lat or 17) + (lon or 78)) % 15)  # 15-30 width
    num_tributaries = 1 + int((seed % 3))  # 1-3 tributaries
    
    # Main river - varies position and shape by location
    center_offset = int((seed % 60) - 30)  # Offset from center
    center_x = width // 2 + center_offset
    
    for y in range(height):
        # Create meandering effect with location-specific pattern
        offset = int(river_amplitude * np.sin(y / river_frequency + seed % 10))
        river_x = center_x + offset
        river_width = river_width_base + int(5 * np.sin(y / 30))
        
        x_start = max(0, river_x - river_width // 2)
        x_end = min(width, river_x + river_width // 2)
        
        river_mask[y, x_start:x_end] = 1
        dem[y, x_start:x_end] = base_elevation - river_depth
    
    # Add tributaries for more realistic pattern
    for t in range(num_tributaries):
        trib_start_y = int(height * (0.2 + 0.6 * np.random.random()))
        trib_start_x = np.random.randint(0, width)
        trib_direction = 1 if trib_start_x < center_x else -1
        trib_width = 5 + np.random.randint(0, 10)
        
        for step in range(50):
            y = trib_start_y + step
            x = trib_start_x + trib_direction * step + int(3 * np.sin(step / 5))
            
            if 0 <= y < height and 0 <= x < width:
                y_start = max(0, y - 2)
                y_end = min(height, y + 2)
                x_start = max(0, x - trib_width // 2)
                x_end = min(width, x + trib_width // 2)
                
                river_mask[y_start:y_end, x_start:x_end] = 1
                dem[y_start:y_end, x_start:x_end] = base_elevation - river_depth * 0.7
    
    # Add low-lying areas (flood plains) near rivers
    from scipy.ndimage import gaussian_filter, binary_dilation
    
    # Expand river area for flood plains
    flood_plain = binary_dilation(river_mask, iterations=10 + seed % 10)
    flood_plain_depth = np.random.rand(height, width) * 3
    flood_plain_depth = gaussian_filter(flood_plain_depth, sigma=5)
    
    # Lower elevation in flood plains
    dem = np.where(
        flood_plain & (river_mask == 0),
        dem - flood_plain_depth - 2,
        dem
    )
    
    # Smooth the DEM
    dem = gaussian_filter(dem, sigma=2)
    
    return dem, river_mask


# Example usage and testing
if __name__ == "__main__":
    # Generate synthetic DEM
    dem, river_mask = generate_synthetic_dem()
    
    # Create flood mask generator
    generator = FloodMaskGenerator(roughness_coefficient=0.035)
    
    # Simulate a flood with 3m water level rise
    base_level = 95.0  # Current water level
    rise = 3.0  # Expected rise
    
    flood_mask, stats = generator.calculate_flood_extent(
        dem=dem,
        base_water_level=base_level,
        water_level_rise=rise
    )
    
    print("Flood Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
