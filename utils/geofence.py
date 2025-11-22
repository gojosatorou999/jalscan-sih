from math import radians, sin, cos, sqrt, atan2

def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great-circle distance between two points 
    on the Earth (specified in decimal degrees)
    Returns distance in meters
    """
    # Earth radius in meters
    R = 6371000
    
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    distance = R * c
    
    return distance

def is_within_geofence(user_lat, user_lon, site_lat, site_lon, radius_meters=50):
    """
    Check if user's current location is within the specified radius of the site
    """
    distance = calculate_distance(user_lat, user_lon, site_lat, site_lon)
    return distance <= radius_meters