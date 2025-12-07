from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import json
from functools import wraps
from werkzeug.security import generate_password_hash

db = SQLAlchemy()

# Role-based permissions
ROLE_PERMISSIONS = {
    'field_agent': {
        'can_capture_data': True,
        'can_view_own_submissions': True,
        'can_view_assigned_sites': True,
        'can_sync_data': True,
        'can_view_dashboard': True,
        'can_manage_public_submissions': False,
        'can_view_all_submissions': False,
        'can_manage_users': False,
        'can_manage_sites': False,
        'can_generate_reports': False,
        'can_export_data': False,
        'can_export_data': False,
        'can_view_tamper_detection': False,
        'can_delete_submissions': False
    },
    'supervisor': {
        'can_capture_data': True,
        'can_view_own_submissions': True,
        'can_view_assigned_sites': True,
        'can_sync_data': True,
        'can_view_dashboard': True,
        'can_manage_public_submissions': True,
        'can_view_all_submissions': True,
        'can_manage_users': True,  # Changed to True for field agent management
        'can_manage_sites': True,
        'can_generate_reports': True,
        'can_export_data': True,
        'can_export_data': True,
        'can_view_tamper_detection': True,
        'can_delete_submissions': True
    },
    'central_analyst': {
        'can_capture_data': False,
        'can_view_own_submissions': False,
        'can_view_assigned_sites': False,
        'can_sync_data': False,
        'can_view_dashboard': True,
        'can_manage_public_submissions': False,
        'can_view_all_submissions': True,
        'can_manage_users': False,
        'can_manage_sites': False,
        'can_generate_reports': True,
        'can_export_data': True,
        'can_export_data': True,
        'can_view_tamper_detection': True,
        'can_delete_submissions': True
    },
    'admin': {
        'can_capture_data': True,
        'can_view_own_submissions': True,
        'can_view_assigned_sites': True,
        'can_sync_data': True,
        'can_view_dashboard': True,
        'can_manage_public_submissions': True,
        'can_view_all_submissions': True,
        'can_manage_users': True,
        'can_manage_sites': True,
        'can_generate_reports': True,
        'can_export_data': True,
        'can_export_data': True,
        'can_view_tamper_detection': True,
        'can_delete_submissions': True
    }
}

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), default='field_agent')
    full_name = db.Column(db.String(100))
    email = db.Column(db.String(120))
    phone = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    
    # NEW FIELDS FOR RIVER ASSIGNMENTS AND AGENT MANAGEMENT
    agent_id = db.Column(db.String(10), unique=True)  # ID 001-009 for field agents
    assigned_river = db.Column(db.String(100))  # Specific river assignment
    scale_reading_bank = db.Column(db.String(100))  # Specific scale reading bank
    river_basin = db.Column(db.String(100))  # River basin assignment
    
    # Relationships - FIXED: Removed the problematic assigned_field_agents relationship
    user_sites = db.relationship('UserSite', foreign_keys='UserSite.user_id', lazy=True, cascade='all, delete-orphan')
    water_level_submissions = db.relationship('WaterLevelSubmission', foreign_keys='WaterLevelSubmission.user_id', lazy=True, cascade='all, delete-orphan')
    public_submission_reviews = db.relationship('PublicImageSubmission', foreign_keys='PublicImageSubmission.reviewed_by', lazy=True)
    site_assignments = db.relationship('UserSite', foreign_keys='UserSite.assigned_by', lazy=True)
    tamper_detection_reviews = db.relationship('TamperDetection', foreign_keys='TamperDetection.reviewed_by', lazy=True)
    water_submission_reviews = db.relationship('WaterLevelSubmission', foreign_keys='WaterLevelSubmission.reviewed_by', lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'role': self.role,
            'full_name': self.full_name,
            'email': self.email,
            'phone': self.phone,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'permissions': self.get_permissions(),
            # NEW: River assignment fields
            'agent_id': self.agent_id,
            'assigned_river': self.assigned_river,
            'scale_reading_bank': self.scale_reading_bank,
            'river_basin': self.river_basin,
            'assigned_river_name': self.get_assigned_river_name()
        }

    def get_permissions(self):
        return ROLE_PERMISSIONS.get(self.role, ROLE_PERMISSIONS['field_agent'])

    def has_permission(self, permission):
        return self.get_permissions().get(permission, False)

    def can_manage_user(self, target_user):
        if self.role == 'admin':
            return True
        if self.role == 'supervisor' and target_user.role == 'field_agent':
            # Supervisors can only manage field agents assigned to their rivers
            if self.assigned_river == 'Multiple':
                return True
            return target_user.assigned_river == self.assigned_river
        return False

    def get_assigned_river_name(self):
        """Get human-readable river name"""
        if not self.assigned_river:
            return None
        
        river_map = {
            'GANGA_HARIDWAR_001': 'Ganga River - Haridwar',
            'MUSI_HYDERABAD_001': 'Musi River - Hyderabad',
            'YAMUNA_DELHI_001': 'Yamuna River - Delhi',
            'GODAVARI_NASHIK_001': 'Godavari River - Nashik',
            'KRISHNA_VIJAYAWADA_001': 'Krishna River - Vijayawada',
            'KAVERI_001': 'Kaveri River',
            'BRAHMAPUTRA_001': 'Brahmaputra River',
            'NARMADA_001': 'Narmada River',
            'TRIPTI_001': 'Tripti River'
        }
        return river_map.get(self.assigned_river, self.assigned_river)

    def get_available_agent_ids(self, river_code):
        """Get available agent IDs for a specific river"""
        if not river_code:
            return []
        
        # Get currently assigned agent IDs for this river
        assigned_agents = User.query.filter_by(
            assigned_river=river_code,
            role='field_agent',
            is_active=True
        ).all()
        
        assigned_ids = [agent.agent_id for agent in assigned_agents if agent.agent_id]
        available_ids = []
        
        # Generate available IDs from 001 to 009
        for i in range(1, 10):
            agent_id = f"{i:03d}"
            if agent_id not in assigned_ids:
                available_ids.append(agent_id)
        
        return available_ids

    def can_assign_to_river(self, river_code):
        """Check if user can assign agents to this river"""
        if self.role == 'admin':
            return True
        if self.role == 'supervisor':
            return self.assigned_river in [river_code, 'Multiple']
        return False

    def get_agent_behavior_metrics(self):
        submissions = WaterLevelSubmission.query.filter_by(user_id=self.id).all()
        
        if not submissions:
            return {}
        
        total_submissions = len(submissions)
        
        time_gaps = []
        submissions_sorted = sorted(submissions, key=lambda x: x.timestamp)
        
        for i in range(1, len(submissions_sorted)):
            gap = (submissions_sorted[i].timestamp - submissions_sorted[i-1].timestamp).total_seconds() / 3600
            time_gaps.append(gap)
        
        avg_time_gap = sum(time_gaps) / len(time_gaps) if time_gaps else 0
        
        location_changes = 0
        for i in range(1, len(submissions_sorted)):
            prev = submissions_sorted[i-1]
            curr = submissions_sorted[i]
            
            if prev.site_id != curr.site_id:
                location_changes += 1
        
        location_consistency = 1 - (location_changes / total_submissions) if total_submissions > 1 else 1.0
        
        tamper_scores = [s.tamper_score for s in submissions if s.tamper_score is not None]
        avg_tamper_score = sum(tamper_scores) / len(tamper_scores) if tamper_scores else 0
        
        return {
            'total_submissions': total_submissions,
            'avg_time_gap_hours': avg_time_gap,
            'location_consistency': location_consistency,
            'avg_tamper_score': avg_tamper_score,
            'suspicious_submissions': len([s for s in submissions if s.tamper_score and s.tamper_score > 0.7]),
            'high_quality_ratio': len([s for s in submissions if s.quality_rating and s.quality_rating >= 4]) / total_submissions
        }

    def __repr__(self):
        river_info = f" - {self.assigned_river}" if self.assigned_river else ""
        agent_info = f" ({self.agent_id})" if self.agent_id else ""
        return f'<User {self.username} - {self.role}{agent_info}{river_info}>'

class MonitoringSite(db.Model):
    __tablename__ = 'monitoring_sites'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    qr_code = db.Column(db.String(100), unique=True)
    description = db.Column(db.Text)
    river_basin = db.Column(db.String(100))
    district = db.Column(db.String(100))
    state = db.Column(db.String(100))
    is_active = db.Column(db.Boolean, default=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # NEW FIELD FOR RIVER CODE
    river_code = db.Column(db.String(50), unique=True)  # GANGA_HARIDWAR_001, etc.
    flood_threshold = db.Column(db.Float, default=10.0)  # Water level threshold for flood alerts
    
    # Relationships
    site_user_assignments = db.relationship('UserSite', foreign_keys='UserSite.site_id', lazy=True, cascade='all, delete-orphan')
    site_water_submissions = db.relationship('WaterLevelSubmission', foreign_keys='WaterLevelSubmission.site_id', lazy=True, cascade='all, delete-orphan')
    site_public_submissions = db.relationship('PublicImageSubmission', foreign_keys='PublicImageSubmission.site_id', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'qr_code': self.qr_code,
            'river_code': self.river_code,
            'description': self.description,
            'river_basin': self.river_basin,
            'district': self.district,
            'state': self.state,
            'is_active': self.is_active,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'flood_threshold': self.flood_threshold
        }

    def get_field_agents(self):
        """Get field agents assigned to this river"""
        return User.query.filter_by(
            assigned_river=self.river_code,
            role='field_agent',
            is_active=True
        ).all()

    def get_available_agent_slots(self):
        """Get number of available agent slots"""
        assigned_count = User.query.filter_by(
            assigned_river=self.river_code,
            role='field_agent',
            is_active=True
        ).count()
        return 9 - assigned_count

    def __repr__(self):
        return f'<MonitoringSite {self.name} ({self.river_code})>'

class UserSite(db.Model):
    __tablename__ = 'user_sites'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    site_id = db.Column(db.Integer, db.ForeignKey('monitoring_sites.id', ondelete='CASCADE'), nullable=False)
    assigned_at = db.Column(db.DateTime, default=datetime.utcnow)
    assigned_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'site_id': self.site_id,
            'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
            'assigned_by': self.assigned_by
        }

class WaterLevelSubmission(db.Model):
    __tablename__ = 'water_level_submissions'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    site_id = db.Column(db.Integer, db.ForeignKey('monitoring_sites.id', ondelete='CASCADE'), nullable=False)
    water_level = db.Column(db.Float, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    gps_latitude = db.Column(db.Float, nullable=False)
    gps_longitude = db.Column(db.Float, nullable=False)
    photo_filename = db.Column(db.String(255), nullable=False)
    location_verified = db.Column(db.Boolean, default=False)
    verification_method = db.Column(db.String(20))
    qr_code_scanned = db.Column(db.String(100))
    sync_status = db.Column(db.String(20), default='pending')
    sync_attempts = db.Column(db.Integer, default=0)
    last_sync_attempt = db.Column(db.DateTime)
    sync_error = db.Column(db.Text)
    notes = db.Column(db.Text)
    quality_rating = db.Column(db.Integer)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime)
    review_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Tamper detection fields
    tamper_score = db.Column(db.Float, default=0.0)
    tamper_status = db.Column(db.String(20), default='clean')
    last_tamper_check = db.Column(db.DateTime)
    tamper_check_version = db.Column(db.String(20), default='1.0')

    # Relationships
    submission_user = db.relationship('User', foreign_keys=[user_id], lazy=True)
    submission_site = db.relationship('MonitoringSite', foreign_keys=[site_id], lazy=True)
    submission_reviewer = db.relationship('User', foreign_keys=[reviewed_by], lazy=True)
    submission_tamper_detections = db.relationship('TamperDetection', foreign_keys='TamperDetection.submission_id', lazy=True, cascade='all, delete-orphan')

    # Compatibility properties
    @property
    def user(self):
        return self.submission_user
    
    @property
    def site(self):
        return self.submission_site
    
    @property
    def reviewer(self):
        return self.submission_reviewer

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'site_id': self.site_id,
            'water_level': self.water_level,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'gps_latitude': self.gps_latitude,
            'gps_longitude': self.gps_longitude,
            'photo_filename': self.photo_filename,
            'location_verified': self.location_verified,
            'verification_method': self.verification_method,
            'qr_code_scanned': self.qr_code_scanned,
            'sync_status': self.sync_status,
            'sync_attempts': self.sync_attempts,
            'last_sync_attempt': self.last_sync_attempt.isoformat() if self.last_sync_attempt else None,
            'sync_error': self.sync_error,
            'notes': self.notes,
            'quality_rating': self.quality_rating,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_notes': self.review_notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'tamper_score': self.tamper_score,
            'tamper_status': self.tamper_status,
            'last_tamper_check': self.last_tamper_check.isoformat() if self.last_tamper_check else None,
            'user_name': self.submission_user.username if self.submission_user else None,
            'user_agent_id': self.submission_user.agent_id if self.submission_user else None,
            'site_name': self.submission_site.name if self.submission_site else None,
            'site_river_code': self.submission_site.river_code if self.submission_site else None,
            'reviewer_name': self.submission_reviewer.username if self.submission_reviewer else None
        }

    def get_sync_payload(self):
        return {
            'submission_id': self.id,
            'user_id': self.user_id,
            'site_id': self.site_id,
            'water_level': self.water_level,
            'timestamp': self.timestamp.isoformat(),
            'gps_latitude': self.gps_latitude,
            'gps_longitude': self.gps_longitude,
            'photo_filename': self.photo_filename,
            'location_verified': self.location_verified,
            'verification_method': self.verification_method,
            'qr_code_scanned': self.qr_code_scanned,
            'notes': self.notes,
            'quality_rating': self.quality_rating,
            'tamper_score': self.tamper_score,
            'tamper_status': self.tamper_status,
            'created_at': self.created_at.isoformat(),
            'agent_id': self.submission_user.agent_id if self.submission_user else None,
            'river_code': self.submission_site.river_code if self.submission_site else None
        }

    def calculate_tamper_indicators(self):
        indicators = {}
        
        if self.location_verified:
            indicators['location_verified'] = 1.0
        else:
            indicators['location_verified'] = 0.5
        
        if self.submission_site:
            from utils.geofence import calculate_distance
            try:
                distance = calculate_distance(
                    self.gps_latitude, self.gps_longitude,
                    self.submission_site.latitude, self.submission_site.longitude
                )
                indicators['gps_accuracy'] = max(0, 1 - (distance / 500))
            except:
                indicators['gps_accuracy'] = 0.3
        else:
            indicators['gps_accuracy'] = 0.3
        
        recent_submissions = WaterLevelSubmission.query.filter(
            WaterLevelSubmission.user_id == self.user_id,
            WaterLevelSubmission.site_id == self.site_id,
            WaterLevelSubmission.timestamp < self.timestamp
        ).order_by(WaterLevelSubmission.timestamp.desc()).first()
        
        if recent_submissions:
            time_gap = (self.timestamp - recent_submissions.timestamp).total_seconds() / 3600
            if time_gap < 1:
                indicators['time_anomaly'] = 0.3
            elif time_gap > 168:
                indicators['time_anomaly'] = 0.4
            else:
                indicators['time_anomaly'] = 1.0
        else:
            indicators['time_anomaly'] = 1.0
        
        if self.quality_rating:
            indicators['quality_rating'] = self.quality_rating / 5.0
        else:
            indicators['quality_rating'] = 0.5
        
        return indicators

    def get_tamper_score(self):
        indicators = self.calculate_tamper_indicators()
        
        weights = {
            'location_verified': 0.3,
            'gps_accuracy': 0.3,
            'time_anomaly': 0.2,
            'quality_rating': 0.2
        }
        
        score = sum(indicators[key] * weights[key] for key in weights.keys())
        return max(0, min(1, 1 - score))

    def mark_synced(self):
        self.sync_status = 'synced'
        self.sync_error = None
        self.last_sync_attempt = datetime.utcnow()

    def mark_failed(self, error_message):
        self.sync_status = 'failed'
        self.sync_error = error_message
        self.sync_attempts += 1
        self.last_sync_attempt = datetime.utcnow()

    def can_retry_sync(self, max_attempts=3):
        return (self.sync_status in ['pending', 'failed'] and 
                self.sync_attempts < max_attempts and
                (not self.last_sync_attempt or 
                 (datetime.utcnow() - self.last_sync_attempt).total_seconds() > 300))

    def __repr__(self):
        return f'<WaterLevelSubmission {self.id} - User {self.user_id} - Site {self.site_id}>'

class PublicImageSubmission(db.Model):
    __tablename__ = 'public_image_submissions'
    
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('monitoring_sites.id', ondelete='CASCADE'), nullable=False)
    photo_filename = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    gps_latitude = db.Column(db.Float)
    gps_longitude = db.Column(db.Float)
    contact_email = db.Column(db.String(120))
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime)
    review_notes = db.Column(db.Text)
    
    # NEW FIELDS FOR ID VERIFICATION
    id_type = db.Column(db.String(50))  # aadhaar, voter_id, driving_license, pan_card, passport, other
    id_front_filename = db.Column(db.String(255))
    id_back_filename = db.Column(db.String(255))
    live_photo_filename = db.Column(db.String(255))
    verification_status = db.Column(db.String(20), default='pending')  # pending, verified, rejected
    verification_notes = db.Column(db.Text)
    submitted_ip = db.Column(db.String(45))  # Store IP address for security
    user_agent = db.Column(db.Text)  # Store browser info

    # Relationships
    public_submission_site = db.relationship('MonitoringSite', foreign_keys=[site_id], lazy=True)
    public_submission_reviewer = db.relationship('User', foreign_keys=[reviewed_by], lazy=True)

    # Compatibility properties
    @property
    def site(self):
        return self.public_submission_site
    
    @property
    def reviewer(self):
        return self.public_submission_reviewer

    def to_dict(self):
        return {
            'id': self.id,
            'site_id': self.site_id,
            'site_name': self.public_submission_site.name if self.public_submission_site else None,
            'site_river_code': self.public_submission_site.river_code if self.public_submission_site else None,
            'photo_filename': self.photo_filename,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'gps_latitude': self.gps_latitude,
            'gps_longitude': self.gps_longitude,
            'contact_email': self.contact_email,
            'description': self.description,
            'status': self.status,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_notes': self.review_notes,
            'reviewer_name': self.public_submission_reviewer.username if self.public_submission_reviewer else None,
            # NEW: ID Verification fields
            'id_type': self.id_type,
            'id_front_filename': self.id_front_filename,
            'id_back_filename': self.id_back_filename,
            'live_photo_filename': self.live_photo_filename,
            'verification_status': self.verification_status,
            'verification_notes': self.verification_notes,
            'has_id_verification': bool(self.id_front_filename and self.live_photo_filename),
            'id_type_display': self.get_id_type_display()
        }

    def get_id_type_display(self):
        """Get human-readable ID type name"""
        id_type_map = {
            'aadhaar': 'Aadhaar Card',
            'voter_id': 'Voter ID Card',
            'driving_license': 'Driving License',
            'pan_card': 'PAN Card',
            'passport': 'Passport',
            'other': 'Other Government ID'
        }
        return id_type_map.get(self.id_type, self.id_type or 'Not specified')

    def get_verification_status_color(self):
        """Get Bootstrap color class for verification status"""
        status_colors = {
            'pending': 'warning',
            'verified': 'success',
            'rejected': 'danger'
        }
        return status_colors.get(self.verification_status, 'secondary')

    def has_complete_id_documents(self):
        """Check if all required ID documents are present"""
        return bool(self.id_front_filename and self.live_photo_filename)

    def can_be_approved(self):
        """Check if submission can be approved (has complete ID verification)"""
        return (self.status == 'pending' and 
                self.has_complete_id_documents() and 
                self.verification_status == 'verified')

    def mark_verified(self, reviewed_by, notes=None):
        """Mark ID as verified"""
        self.verification_status = 'verified'
        self.verification_notes = notes
        self.reviewed_by = reviewed_by
        self.reviewed_at = datetime.utcnow()

    def mark_rejected(self, reviewed_by, notes=None):
        """Mark ID as rejected"""
        self.verification_status = 'rejected'
        self.verification_notes = notes
        self.reviewed_by = reviewed_by
        self.reviewed_at = datetime.utcnow()

    def get_file_list(self):
        """Get list of all files associated with this submission"""
        files = [
            {'type': 'water_level', 'filename': self.photo_filename, 'label': 'Water Level Photo'},
            {'type': 'id_front', 'filename': self.id_front_filename, 'label': 'ID Front Side'}
        ]
        
        if self.id_back_filename:
            files.append({'type': 'id_back', 'filename': self.id_back_filename, 'label': 'ID Back Side'})
        
        if self.live_photo_filename:
            files.append({'type': 'live_photo', 'filename': self.live_photo_filename, 'label': 'Live Verification Photo'})
        
        return files

    def __repr__(self):
        return f'<PublicImageSubmission {self.id} - Site {self.site_id} - Status {self.status}>'

class SyncLog(db.Model):
    __tablename__ = 'sync_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    sync_type = db.Column(db.String(20))
    submissions_synced = db.Column(db.Integer, default=0)
    submissions_failed = db.Column(db.Integer, default=0)
    total_attempts = db.Column(db.Integer, default=0)
    sync_duration = db.Column(db.Float)
    error_message = db.Column(db.Text)
    success = db.Column(db.Boolean, default=False)

    def to_dict(self):
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'sync_type': self.sync_type,
            'submissions_synced': self.submissions_synced,
            'submissions_failed': self.submissions_failed,
            'total_attempts': self.total_attempts,
            'sync_duration': self.sync_duration,
            'error_message': self.error_message,
            'success': self.success
        }

    def mark_success(self, synced_count, failed_count, duration):
        self.submissions_synced = synced_count
        self.submissions_failed = failed_count
        self.total_attempts = synced_count + failed_count
        self.sync_duration = duration
        self.success = True
        self.error_message = None

    def mark_failure(self, error_message, duration):
        self.sync_duration = duration
        self.error_message = error_message
        self.success = False

    def __repr__(self):
        status = "SUCCESS" if self.success else "FAILED"
        return f'<SyncLog {self.id} - {self.sync_type} - {status}>'

class TamperDetection(db.Model):
    __tablename__ = 'tamper_detections'
    
    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('water_level_submissions.id', ondelete='CASCADE'))
    detection_type = db.Column(db.String(50), nullable=False)
    severity = db.Column(db.String(20), default='warning')
    description = db.Column(db.Text, nullable=False)
    confidence_score = db.Column(db.Float, default=0.0)
    detected_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime)
    review_status = db.Column(db.String(20), default='pending')
    review_notes = db.Column(db.Text)
    
    # Relationships
    tamper_submission = db.relationship('WaterLevelSubmission', foreign_keys=[submission_id], lazy=True)
    tamper_reviewer = db.relationship('User', foreign_keys=[reviewed_by], lazy=True)

    def to_dict(self):
        return {
            'id': self.id,
            'submission_id': self.submission_id,
            'detection_type': self.detection_type,
            'severity': self.severity,
            'description': self.description,
            'confidence_score': self.confidence_score,
            'detected_at': self.detected_at.isoformat() if self.detected_at else None,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None,
            'review_status': self.review_status,
            'review_notes': self.review_notes,
            'site_name': self.tamper_submission.submission_site.name if self.tamper_submission and self.tamper_submission.submission_site else None,
            'site_river_code': self.tamper_submission.submission_site.river_code if self.tamper_submission and self.tamper_submission.submission_site else None,
            'agent_name': self.tamper_submission.submission_user.username if self.tamper_submission and self.tamper_submission.submission_user else None,
            'agent_id': self.tamper_submission.submission_user.agent_id if self.tamper_submission and self.tamper_submission.submission_user else None,
            'water_level': self.tamper_submission.water_level if self.tamper_submission else None,
            'timestamp': self.tamper_submission.timestamp.isoformat() if self.tamper_submission and self.tamper_submission.timestamp else None
        }

    def __repr__(self):
        return f'<TamperDetection {self.id} - {self.detection_type} - {self.severity}>'

class AppConfig(db.Model):
    __tablename__ = 'app_config'
    
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'value': self.value,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def __repr__(self):
        return f'<AppConfig {self.key}={self.value}>'

class WhatsAppSubscriber(db.Model):
    __tablename__ = 'whatsapp_subscribers'
    
    id = db.Column(db.Integer, primary_key=True)
    phone_number = db.Column(db.String(20), unique=True, nullable=False)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    subscribed_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'phone_number': self.phone_number,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'subscribed_at': self.subscribed_at.isoformat() if self.subscribed_at else None,
            'is_active': self.is_active
        }

class FloodAlert(db.Model):
    __tablename__ = 'flood_alerts'
    
    id = db.Column(db.Integer, primary_key=True)
    site_id = db.Column(db.Integer, db.ForeignKey('monitoring_sites.id'), nullable=False)
    alert_level = db.Column(db.String(20)) # warning, critical, severe
    water_level = db.Column(db.Float)
    message = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    subscribers_notified_count = db.Column(db.Integer, default=0)
    
    # Relationships
    site = db.relationship('MonitoringSite', foreign_keys=[site_id], lazy=True)
    
    def to_dict(self):
        return {
            'id': self.id,
            'site_id': self.site_id,
            'site_name': self.site.name if self.site else None,
            'alert_level': self.alert_level,
            'water_level': self.water_level,
            'message': self.message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'subscribers_notified_count': self.subscribers_notified_count
        }

# Database utility functions
def get_pending_submissions(user_id=None, max_retries=3):
    query = WaterLevelSubmission.query.filter(
        WaterLevelSubmission.sync_status.in_(['pending', 'failed']),
        WaterLevelSubmission.sync_attempts < max_retries
    )
    
    if user_id:
        query = query.filter(WaterLevelSubmission.user_id == user_id)
    
    return query.all()

def get_sync_stats(user_id=None):
    query = WaterLevelSubmission.query
    
    if user_id:
        query = query.filter(WaterLevelSubmission.user_id == user_id)
    
    total = query.count()
    pending = query.filter(WaterLevelSubmission.sync_status == 'pending').count()
    synced = query.filter(WaterLevelSubmission.sync_status == 'synced').count()
    failed = query.filter(WaterLevelSubmission.sync_status == 'failed').count()
    
    return {
        'total': total,
        'pending': pending,
        'synced': synced,
        'failed': failed
    }

def get_recent_sync_logs(limit=10):
    return SyncLog.query.order_by(SyncLog.timestamp.desc()).limit(10).all()

def reset_failed_submissions(user_id=None):
    query = WaterLevelSubmission.query.filter(WaterLevelSubmission.sync_status == 'failed')
    
    if user_id:
        query = query.filter(WaterLevelSubmission.user_id == user_id)
    
    count = 0
    for submission in query.all():
        submission.sync_status = 'pending'
        submission.sync_attempts = 0
        submission.sync_error = None
        count += 1
    
    return count

def get_tamper_detection_stats():
    total_detections = TamperDetection.query.count()
    pending_review = TamperDetection.query.filter_by(review_status='pending').count()
    confirmed_tamper = TamperDetection.query.filter_by(review_status='confirmed').count()
    false_positives = TamperDetection.query.filter_by(review_status='false_positive').count()
    
    detection_types = db.session.query(
        TamperDetection.detection_type,
        db.func.count(TamperDetection.id).label('count')
    ).group_by(TamperDetection.detection_type).all()
    
    severity_counts = db.session.query(
        TamperDetection.severity,
        db.func.count(TamperDetection.id).label('count')
    ).group_by(TamperDetection.severity).all()
    
    return {
        'total_detections': total_detections,
        'pending_review': pending_review,
        'confirmed_tamper': confirmed_tamper,
        'false_positives': false_positives,
        'detection_types': {dt.detection_type: dt.count for dt in detection_types},
        'severity_counts': {sc.severity: sc.count for sc in severity_counts}
    }

def get_suspicious_submissions(threshold=0.7, limit=50):
    return WaterLevelSubmission.query.filter(
        WaterLevelSubmission.tamper_score >= threshold
    ).order_by(
        WaterLevelSubmission.tamper_score.desc()
    ).limit(limit).all()

def get_recent_tamper_detections(limit=20):
    return TamperDetection.query.order_by(
        TamperDetection.detected_at.desc()
    ).limit(limit).all()

# NEW: River and Agent Management Functions
def get_river_stats():
    """Get statistics for all rivers"""
    rivers = MonitoringSite.query.filter(
        MonitoringSite.river_code.isnot(None)
    ).distinct(MonitoringSite.river_code).all()
    
    river_stats = []
    for river in rivers:
        # Count field agents for this river
        agent_count = User.query.filter_by(
            assigned_river=river.river_code,
            role='field_agent',
            is_active=True
        ).count()
        
        # Count submissions for this river
        submission_count = WaterLevelSubmission.query.join(
            MonitoringSite
        ).filter(
            MonitoringSite.river_code == river.river_code
        ).count()
        
        river_stats.append({
            'river_code': river.river_code,
            'river_name': river.name,
            'agent_count': agent_count,
            'available_slots': 9 - agent_count,
            'submission_count': submission_count,
            'basin': river.river_basin
        })
    
    return river_stats

def get_available_rivers_for_supervisor(supervisor):
    """Get rivers that a supervisor can manage"""
    if supervisor.role == 'admin':
        return MonitoringSite.query.filter(
            MonitoringSite.river_code.isnot(None)
        ).distinct(MonitoringSite.river_code).all()
    elif supervisor.role == 'supervisor':
        if supervisor.assigned_river == 'Multiple':
            return MonitoringSite.query.filter(
                MonitoringSite.river_code.isnot(None)
            ).distinct(MonitoringSite.river_code).all()
        else:
            return MonitoringSite.query.filter_by(
                river_code=supervisor.assigned_river
            ).all()
    return []

def create_field_agent(username, password, full_name, river_code, agent_id, scale_reading_bank=None, email=None, phone=None, assigned_by=None):
    """Create a new field agent with river assignment"""
    # Validate agent ID
    if not (1 <= int(agent_id) <= 9):
        raise ValueError("Agent ID must be between 001 and 009")
    
    # Format agent ID
    agent_id = agent_id.zfill(3)
    
    # Check if agent ID is available for this river
    existing_agent = User.query.filter_by(
        assigned_river=river_code,
        agent_id=agent_id,
        is_active=True
    ).first()
    
    if existing_agent:
        raise ValueError(f"Agent ID {agent_id} is already assigned to this river")
    
    # Get river basin from the river site
    river_site = MonitoringSite.query.filter_by(river_code=river_code).first()
    if not river_site:
        raise ValueError(f"River with code {river_code} not found")
    
    # Create the field agent
    field_agent = User(
        username=username,
        password_hash=generate_password_hash(password),
        role='field_agent',
        full_name=full_name,
        email=email,
        phone=phone,
        is_active=True,
        agent_id=agent_id,
        assigned_river=river_code,
        scale_reading_bank=scale_reading_bank,
        river_basin=river_site.river_basin
    )
    
    db.session.add(field_agent)
    db.session.flush()  # Get the agent ID
    
    # Assign all sites for this river to the agent
    river_sites = MonitoringSite.query.filter_by(river_code=river_code).all()
    for site in river_sites:
        user_site = UserSite(
            user_id=field_agent.id,
            site_id=site.id,
            assigned_by=assigned_by
        )
        db.session.add(user_site)
    
    return field_agent

def get_river_agents(river_code):
    """Get all field agents assigned to a specific river"""
    return User.query.filter_by(
        assigned_river=river_code,
        role='field_agent',
        is_active=True
    ).order_by(User.agent_id).all()

# NEW: Public submission utility functions
def get_public_submission_stats():
    """Get statistics for public submissions"""
    total = PublicImageSubmission.query.count()
    pending = PublicImageSubmission.query.filter_by(status='pending').count()
    approved = PublicImageSubmission.query.filter_by(status='approved').count()
    rejected = PublicImageSubmission.query.filter_by(status='rejected').count()
    
    # ID verification stats
    with_id = PublicImageSubmission.query.filter(
        PublicImageSubmission.id_front_filename.isnot(None),
        PublicImageSubmission.live_photo_filename.isnot(None)
    ).count()
    
    verified = PublicImageSubmission.query.filter_by(verification_status='verified').count()
    
    return {
        'total_public_submissions': total,
        'pending_review': pending,
        'approved': approved,
        'rejected': rejected,
        'with_id_verification': with_id,
        'verified_identity': verified
    }

def get_public_submissions_with_pending_verification(limit=50):
    """Get public submissions that need ID verification"""
    return PublicImageSubmission.query.filter(
        PublicImageSubmission.status == 'pending',
        PublicImageSubmission.id_front_filename.isnot(None)
    ).order_by(
        PublicImageSubmission.timestamp.desc()
    ).limit(limit).all()

def get_id_type_stats():
    """Get statistics by ID type"""
    id_type_counts = db.session.query(
        PublicImageSubmission.id_type,
        db.func.count(PublicImageSubmission.id).label('count')
    ).filter(
        PublicImageSubmission.id_type.isnot(None)
    ).group_by(
        PublicImageSubmission.id_type
    ).all()
    
    return {result.id_type: result.count for result in id_type_counts}

# NEW: AppConfig utility functions
def get_app_config(key, default=None):
    """Get application configuration value"""
    config = AppConfig.query.filter_by(key=key).first()
    return config.value if config else default

def set_app_config(key, value):
    """Set application configuration value"""
    config = AppConfig.query.filter_by(key=key).first()
    if config:
        config.value = value
        config.updated_at = datetime.utcnow()
    else:
        config = AppConfig(key=key, value=value)
        db.session.add(config)
    db.session.commit()
    return config

def get_all_app_config():
    """Get all application configuration as dictionary"""
    configs = AppConfig.query.all()
    return {config.key: config.value for config in configs}

# Permission decorators
def require_permission(permission):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from flask import redirect, url_for, flash
            from flask_login import current_user
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if not current_user.has_permission(permission):
                flash('You do not have permission to access this page.', 'error')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def require_role(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from flask import redirect, url_for, flash
            from flask_login import current_user
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if current_user.role != role:
                flash('You do not have the required role to access this page.', 'error')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator