let stream = null;
let capturedPhoto = null;

// Initialize camera
async function initCamera() {
    try {
        stream = await navigator.mediaDevices.getUserMedia({ 
            video: { facingMode: 'environment' } 
        });
        const video = document.getElementById('video');
        video.srcObject = stream;
    } catch (err) {
        console.error('Error accessing camera:', err);
        alert('Error accessing camera. Please ensure you have granted camera permissions.');
    }
}

// Capture photo
document.getElementById('capture-btn').addEventListener('click', function() {
    const video = document.getElementById('video');
    const canvas = document.getElementById('canvas');
    const context = canvas.getContext('2d');
    
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    
    capturedPhoto = canvas.toDataURL('image/jpeg');
    
    // Show preview
    document.getElementById('preview-img').src = capturedPhoto;
    document.getElementById('photo-preview').style.display = 'block';
    document.getElementById('capture-btn').disabled = true;
});

// Retake photo
document.getElementById('retake-btn').addEventListener('click', function() {
    capturedPhoto = null;
    document.getElementById('photo-preview').style.display = 'none';
    document.getElementById('capture-btn').disabled = false;
});

// Get current location and verify
function getLocation() {
    if (!navigator.geolocation) {
        updateLocationStatus('Geolocation is not supported by this browser.', false);
        return;
    }

    navigator.geolocation.getCurrentPosition(
        async (position) => {
            const lat = position.coords.latitude;
            const lon = position.coords.longitude;
            
            document.getElementById('latitude').value = lat;
            document.getElementById('longitude').value = lon;
            
            // Verify location with server
            try {
                const response = await fetch('/api/verify-location', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        site_id: document.querySelector('input[name="site_id"]').value,
                        latitude: lat,
                        longitude: lon
                    })
                });
                
                const data = await response.json();
                
                if (data.verified) {
                    updateLocationStatus('Location verified! You can now capture photos.', true);
                    document.getElementById('capture-btn').disabled = false;
                } else {
                    updateLocationStatus('You are outside the permitted zone. Please move closer to the monitoring site.', false);
                }
                
            } catch (error) {
                console.error('Error verifying location:', error);
                updateLocationStatus('Error verifying location. Please try again.', false);
            }
        },
        (error) => {
            console.error('Error getting location:', error);
            let message = 'Error getting your location. ';
            switch(error.code) {
                case error.PERMISSION_DENIED:
                    message += 'Location access was denied. Please enable location services.';
                    break;
                case error.POSITION_UNAVAILABLE:
                    message += 'Location information is unavailable.';
                    break;
                case error.TIMEOUT:
                    message += 'Location request timed out.';
                    break;
                default:
                    message += 'An unknown error occurred.';
                    break;
            }
            updateLocationStatus(message, false);
        },
        {
            enableHighAccuracy: true,
            timeout: 10000,
            maximumAge: 0
        }
    );
}

function updateLocationStatus(message, isSuccess) {
    const statusDiv = document.getElementById('location-status');
    statusDiv.innerHTML = isSuccess ? 
        `<span class="text-success">✓ ${message}</span>` :
        `<span class="text-danger">✗ ${message}</span>`;
    statusDiv.className = `alert alert-${isSuccess ? 'success' : 'danger'}`;
}

// Form submission
document.getElementById('reading-form').addEventListener('submit', async function(e) {
    e.preventDefault();
    
    if (!capturedPhoto) {
        alert('Please capture a photo before submitting.');
        return;
    }
    
    const submitBtn = document.getElementById('submit-btn');
    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Submitting...';
    
    try {
        // Convert base64 to blob
        const response = await fetch(capturedPhoto);
        const blob = await response.blob();
        
        const formData = new FormData();
        formData.append('site_id', document.querySelector('input[name="site_id"]').value);
        formData.append('water_level', document.getElementById('water_level').value);
        formData.append('latitude', document.getElementById('latitude').value);
        formData.append('longitude', document.getElementById('longitude').value);
        formData.append('photo', blob, 'photo.jpg');
        
        const submitResponse = await fetch('/api/submit-reading', {
            method: 'POST',
            body: formData
        });
        
        const result = await submitResponse.json();
        
        if (result.success) {
            alert('Reading submitted successfully!');
            window.location.href = '/dashboard';
        } else {
            throw new Error(result.error || 'Submission failed');
        }
        
    } catch (error) {
        console.error('Error submitting reading:', error);
        alert('Error submitting reading. Please try again.');
        submitBtn.disabled = false;
        submitBtn.innerHTML = 'Submit Reading';
    }
});


// Initialize page
document.addEventListener('DOMContentLoaded', function() {
    initCamera();
    getLocation();
});