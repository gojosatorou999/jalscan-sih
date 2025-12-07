# tamper_detection.py
import logging
from datetime import datetime, timedelta
from models import db, WaterLevelSubmission, TamperDetection, User
from utils.geofence import calculate_distance

from sqlalchemy import func

class TamperDetectionEngine:
    def __init__(self, app):
        self.app = app
        self.detection_rules = {
            'location_mismatch': self.detect_location_mismatch,
            'time_anomaly': self.detect_time_anomaly,
            'duplicate_submission': self.detect_duplicate_submission,
            'pattern_anomaly': self.detect_pattern_anomaly,
            'quality_anomaly': self.detect_quality_anomaly
        }
    
    def analyze_submission(self, submission):
        """Run all tamper detection rules on a submission"""
        detections = []
        
        with self.app.app_context():
            for rule_name, rule_func in self.detection_rules.items():
                try:
                    detection = rule_func(submission)
                    if detection:
                        detections.append(detection)
                except Exception as e:
                    logging.error(f"Error in tamper detection rule {rule_name}: {e}")
            
            # Update submission tamper score
            if detections:
                max_severity = max(detections, key=lambda x: self._severity_to_score(x['severity']))
                submission.tamper_score = max(detection['confidence_score'] for detection in detections)
                submission.tamper_status = 'suspicious' if submission.tamper_score > 0.5 else 'clean'
            else:
                submission.tamper_score = 0.0
                submission.tamper_status = 'clean'
            
            submission.last_tamper_check = datetime.utcnow()
            db.session.commit()
            
            # Create tamper detection records
            for detection in detections:
                tamper_detection = TamperDetection(
                    submission_id=submission.id,
                    detection_type=detection['type'],
                    severity=detection['severity'],
                    description=detection['description'],
                    confidence_score=detection['confidence_score']
                )
                db.session.add(tamper_detection)
            
            db.session.commit()
        
        return detections
    
    def detect_location_mismatch(self, submission):
        """Detect if submission location doesn't match site location"""
        if not submission.site:
            return None
        
        distance = calculate_distance(
            submission.gps_latitude, submission.gps_longitude,
            submission.site.latitude, submission.site.longitude
        )
        
        # Critical if > 1km from site
        if distance > 1000:
            return {
                'type': 'location_mismatch',
                'severity': 'critical',
                'description': f'Submission location is {distance:.0f}m from designated site',
                'confidence_score': 0.9
            }
        # High if > 500m
        elif distance > 500:
            return {
                'type': 'location_mismatch',
                'severity': 'high',
                'description': f'Submission location is {distance:.0f}m from designated site',
                'confidence_score': 0.7
            }
        # Medium if > 200m but verification failed
        elif distance > 200 and not submission.location_verified:
            return {
                'type': 'location_mismatch',
                'severity': 'medium',
                'description': f'Location verification failed for submission {distance:.0f}m from site',
                'confidence_score': 0.5
            }
        
        return None
    
    def detect_time_anomaly(self, submission):
        """Detect unusual timing patterns"""
        # Check for submissions in quick succession
        recent_submissions = WaterLevelSubmission.query.filter(
            WaterLevelSubmission.user_id == submission.user_id,
            WaterLevelSubmission.site_id == submission.site_id,
            WaterLevelSubmission.timestamp > submission.timestamp - timedelta(hours=1),
            WaterLevelSubmission.id != submission.id
        ).count()
        
        if recent_submissions > 2:
            return {
                'type': 'time_anomaly',
                'severity': 'high',
                'description': f'Multiple submissions ({recent_submissions + 1}) in quick succession',
                'confidence_score': 0.8
            }
        
        # Check for submissions outside normal hours (10PM - 5AM)
        submission_hour = submission.timestamp.hour
        if submission_hour >= 22 or submission_hour <= 5:
            return {
                'type': 'time_anomaly',
                'severity': 'medium',
                'description': f'Submission made during unusual hours ({submission_hour:02d}:00)',
                'confidence_score': 0.4
            }
        
        return None
    
    def detect_duplicate_submission(self, submission):
        """Detect potential duplicate submissions"""
        # Check for similar submissions from same user at same location within short time
        similar_submissions = WaterLevelSubmission.query.filter(
            WaterLevelSubmission.user_id == submission.user_id,
            WaterLevelSubmission.site_id == submission.site_id,
            WaterLevelSubmission.timestamp > submission.timestamp - timedelta(minutes=30),
            WaterLevelSubmission.id != submission.id,
            func.abs(WaterLevelSubmission.water_level - submission.water_level) < 0.1  # Similar water level
        ).first()
        
        if similar_submissions:
            return {
                'type': 'duplicate_submission',
                'severity': 'medium',
                'description': 'Potential duplicate submission detected',
                'confidence_score': 0.6
            }
        
        return None
    
    def detect_pattern_anomaly(self, submission):
        """Detect anomalies in submission patterns"""
        user_submissions = WaterLevelSubmission.query.filter_by(
            user_id=submission.user_id
        ).order_by(WaterLevelSubmission.timestamp.desc()).limit(10).all()
        
        if len(user_submissions) < 3:
            return None
        
        # Check for sudden changes in water level
        recent_levels = [s.water_level for s in user_submissions[:3]]
        if len(recent_levels) >= 2:
            avg_recent = sum(recent_levels) / len(recent_levels)
            current_diff = abs(submission.water_level - avg_recent)
            
            if current_diff > 2.0:  # More than 2m difference
                return {
                    'type': 'pattern_anomaly',
                    'severity': 'high',
                    'description': f'Unusual water level change: {current_diff:.1f}m from recent average',
                    'confidence_score': 0.7
                }
        
        return None
    
    def detect_quality_anomaly(self, submission):
        """Detect anomalies in data quality"""
        # Check for missing or poor quality data
        issues = []
        
        if not submission.quality_rating or submission.quality_rating < 3:
            issues.append("Low quality rating")
        
        if not submission.notes or len(submission.notes.strip()) < 10:
            issues.append("Minimal or missing notes")
        
        if not submission.location_verified:
            issues.append("Location not verified")
        
        if issues:
            return {
                'type': 'quality_anomaly',
                'severity': 'medium',
                'description': f'Quality issues: {", ".join(issues)}',
                'confidence_score': 0.5
            }
        
        return None
    
    def _severity_to_score(self, severity):
        """Convert severity string to numeric score for comparison"""
        severity_scores = {
            'low': 1,
            'medium': 2,
            'high': 3,
            'critical': 4
        }
        return severity_scores.get(severity, 0)
    
    def run_batch_analysis(self, days=30):
        """Run tamper detection on recent submissions"""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        submissions = WaterLevelSubmission.query.filter(
            WaterLevelSubmission.timestamp >= cutoff_date,
            WaterLevelSubmission.tamper_status != 'confirmed_tamper'
        ).all()
        
        results = {
            'total_analyzed': len(submissions),
            'suspicious_found': 0,
            'detections_by_type': {},
            'detections_by_severity': {}
        }
        
        for submission in submissions:
            detections = self.analyze_submission(submission)
            
            if detections:
                results['suspicious_found'] += 1
            
            for detection in detections:
                # Count by type
                results['detections_by_type'][detection['type']] = \
                    results['detections_by_type'].get(detection['type'], 0) + 1
                
                # Count by severity
                results['detections_by_severity'][detection['severity']] = \
                    results['detections_by_severity'].get(detection['severity'], 0) + 1
        
        return results

# Utility function for real-time monitoring
def monitor_agent_behavior(user_id, window_hours=24):
    """Monitor agent behavior for anomalies"""
    cutoff_time = datetime.utcnow() - timedelta(hours=window_hours)
    
    recent_submissions = WaterLevelSubmission.query.filter(
        WaterLevelSubmission.user_id == user_id,
        WaterLevelSubmission.timestamp >= cutoff_time
    ).all()
    
    if not recent_submissions:
        return {'status': 'normal', 'message': 'No recent activity'}
    
    # Calculate metrics
    total_submissions = len(recent_submissions)
    avg_tamper_score = sum(s.tamper_score for s in recent_submissions) / total_submissions
    suspicious_count = len([s for s in recent_submissions if s.tamper_score > 0.7])
    
    # Determine status
    if suspicious_count > total_submissions * 0.5:  # More than 50% suspicious
        status = 'critical'
    elif suspicious_count > total_submissions * 0.3:  # More than 30% suspicious
        status = 'high'
    elif suspicious_count > 0:
        status = 'medium'
    else:
        status = 'normal'
    
    return {
        'status': status,
        'total_submissions': total_submissions,
        'avg_tamper_score': avg_tamper_score,
        'suspicious_count': suspicious_count,
        'suspicious_ratio': suspicious_count / total_submissions
    }