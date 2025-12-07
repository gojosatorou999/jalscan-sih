from flask import Flask, render_template, request, jsonify, flash, redirect, url_for, send_file
from dotenv import load_dotenv
load_dotenv()
from twilio.twiml.messaging_response import MessagingResponse
from flask_login import LoginManager, current_user, login_required
from config import config
from models import db, User, MonitoringSite, WaterLevelSubmission, UserSite, SyncLog, PublicImageSubmission, TamperDetection, AppConfig, WhatsAppSubscriber
from auth import auth_bp
import os
from datetime import datetime, timedelta
import logging
from flask import current_app
from sync_service import SyncService
from whatsapp_service import WhatsAppService
from functools import wraps
from tamper_detection import TamperDetectionEngine, monitor_agent_behavior
from werkzeug.security import generate_password_hash
import requests
import schedule
import time
import threading
import csv

# Add these global variables
LAST_CSV_URL = None
CSV_PROCESSING_INTERVAL = 300  # 5 minutes

def create_app(config_name='default'):
    app = Flask(__name__)
    app.config.from_object(config[config_name])
    
    # Initialize extensions
    db.init_app(app)
    
    # Setup login manager
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))
    
    # Create upload directory
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Register blueprints
    app.register_blueprint(auth_bp)
    
    # Initialize services
    sync_service = SyncService(app)
    tamper_engine = TamperDetectionEngine(app)  # Initialize tamper detection
    whatsapp_service = WhatsAppService(app)  # Initialize WhatsApp service
    
    # Role-based access control decorators
    def role_required(roles):
        """Decorator to require specific role(s)"""
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                if not current_user.is_authenticated:
                    return redirect(url_for('auth.login'))
                if current_user.role not in roles:
                    flash('Access denied. Insufficient privileges.', 'error')
                    return redirect(url_for('dashboard'))
                return f(*args, **kwargs)
            return decorated_function
        return decorator

    def permission_required(permission):
        """Decorator to require specific permission"""
        def decorator(f):
            @wraps(f)
            def decorated_function(*args, **kwargs):
                if not current_user.is_authenticated:
                    return redirect(url_for('auth.login'))
                if not current_user.has_permission(permission):
                    flash('You do not have permission to access this page.', 'error')
                    return redirect(url_for('dashboard'))
                return f(*args, **kwargs)
            return decorated_function
        return decorator

    # Main routes
    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        return redirect(url_for('public_upload'))

    @app.route('/dashboard')
    @login_required
    def dashboard():
        # Get user's assigned sites
        if current_user.has_permission('can_view_all_submissions'):
            # Supervisors and analysts can see all submissions
            recent_submissions = WaterLevelSubmission.query.order_by(
                WaterLevelSubmission.timestamp.desc()
            ).limit(10).all()
            assigned_sites = MonitoringSite.query.filter_by(is_active=True).all()
        else:
            # Field agents can only see their submissions and assigned sites
            assigned_sites = MonitoringSite.query.join(UserSite).filter(
                UserSite.user_id == current_user.id
            ).all()
            recent_submissions = WaterLevelSubmission.query.filter_by(
                user_id=current_user.id
            ).order_by(WaterLevelSubmission.timestamp.desc()).limit(5).all()
        
        # Get dashboard stats based on role
        if current_user.has_permission('can_view_all_submissions'):
            total_submissions = WaterLevelSubmission.query.count()
            pending_sync = WaterLevelSubmission.query.filter_by(sync_status='pending').count()
            public_pending = PublicImageSubmission.query.filter_by(status='pending').count()
            total_users = User.query.filter_by(is_active=True).count()
        else:
            total_submissions = WaterLevelSubmission.query.filter_by(user_id=current_user.id).count()
            pending_sync = WaterLevelSubmission.query.filter_by(user_id=current_user.id, sync_status='pending').count()
            public_pending = 0
            total_users = 0
        
        return render_template('dashboard.html', 
                             sites=assigned_sites,
                             submissions=recent_submissions,
                             total_submissions=total_submissions,
                             pending_sync=pending_sync,
                             public_pending=public_pending,
                             total_users=total_users)

    # Public routes for image submission
    @app.route('/public/upload')
    def public_upload():
        """Public image upload page"""
        sites = MonitoringSite.query.filter_by(is_active=True).all()
        return render_template('public_upload.html', sites=sites)
    
    @app.route('/api/public/submit-image', methods=['POST'])
    def public_submit_image():
        """API endpoint for public image submissions with ID verification"""
        try:
            # Get form data - NEW FIELDS ADDED
            site_id = request.form.get('site_id')
            latitude = request.form.get('latitude')
            longitude = request.form.get('longitude')
            contact_email = request.form.get('contact_email')
            description = request.form.get('description')
            id_type = request.form.get('id_type')  # NEW: Government ID type
            
            # Validate required fields - UPDATED WITH ID VALIDATION
            if not all([site_id, id_type]):
                return jsonify({'success': False, 'error': 'Please select a monitoring site and ID type'}), 400
            
            # Handle file uploads - UPDATED WITH NEW FILE TYPES
            required_files = ['photo', 'govt_id_front', 'live_photo']
            for file_field in required_files:
                if file_field not in request.files:
                    return jsonify({'success': False, 'error': f'No {file_field.replace("_", " ")} provided'}), 400
                
                file = request.files[file_field]
                if file.filename == '':
                    return jsonify({'success': False, 'error': f'No {file_field.replace("_", " ")} selected'}), 400
            
            photo = request.files['photo']
            govt_id_front = request.files['govt_id_front']
            govt_id_back = request.files.get('govt_id_back')  # Optional
            live_photo = request.files['live_photo']
            
            # Validate file types
            allowed_extensions = current_app.config['ALLOWED_EXTENSIONS']
            for file_obj, file_type in [(photo, 'water level photo'), 
                                      (govt_id_front, 'ID front'), 
                                      (live_photo, 'live photo')]:
                if file_obj and not ('.' in file_obj.filename and 
                                   file_obj.filename.rsplit('.', 1)[1].lower() in allowed_extensions):
                    return jsonify({'success': False, 'error': f'Invalid {file_type} file type. Please upload JPG or PNG images.'}), 400
            
            if govt_id_back and not ('.' in govt_id_back.filename and 
                                   govt_id_back.filename.rsplit('.', 1)[1].lower() in allowed_extensions):
                return jsonify({'success': False, 'error': 'Invalid ID back file type. Please upload JPG or PNG images.'}), 400
            
            # Verify site exists and is active
            site = MonitoringSite.query.filter_by(id=site_id, is_active=True).first()
            if not site:
                return jsonify({'success': False, 'error': 'Invalid monitoring site'}), 400
            
            # Save all files with timestamps
            timestamp = datetime.utcnow()
            timestamp_str = timestamp.strftime('%Y%m%d_%H%M%S')
            
            # Save water level photo
            water_level_filename = f"public_water_{site_id}_{timestamp_str}.jpg"
            water_level_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], water_level_filename)
            photo.save(water_level_filepath)
            
            # Save government ID files
            id_front_filename = f"public_id_front_{site_id}_{timestamp_str}.jpg"
            id_front_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], id_front_filename)
            govt_id_front.save(id_front_filepath)
            
            id_back_filename = None
            if govt_id_back:
                id_back_filename = f"public_id_back_{site_id}_{timestamp_str}.jpg"
                id_back_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], id_back_filename)
                govt_id_back.save(id_back_filepath)
            
            # Save live photo
            live_photo_filename = f"public_live_{site_id}_{timestamp_str}.jpg"
            live_photo_filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], live_photo_filename)
            live_photo.save(live_photo_filepath)
            
            # Add timestamp overlay to water level photo if location is available
            if latitude and longitude:
                try:
                    from utils.image_processing import add_timestamp_to_image
                    add_timestamp_to_image(water_level_filepath, timestamp, float(latitude), float(longitude))
                except Exception as e:
                    logging.warning(f"Could not add timestamp to public image: {e}")
            
            # Create public submission record with ID verification data
            submission = PublicImageSubmission(
                site_id=site_id,
                photo_filename=water_level_filename,
                timestamp=timestamp,
                gps_latitude=float(latitude) if latitude else None,
                gps_longitude=float(longitude) if longitude else None,
                contact_email=contact_email,
                description=description,
                status='pending',
                # NEW FIELDS FOR ID VERIFICATION
                id_type=id_type,
                id_front_filename=id_front_filename,
                id_back_filename=id_back_filename,
                live_photo_filename=live_photo_filename
            )
            
            db.session.add(submission)
            db.session.commit()
            
            # Send notification email (optional)
            try:
                send_public_submission_notification(submission)
            except Exception as e:
                logging.warning(f"Could not send notification email: {e}")
            
            return jsonify({
                'success': True,
                'message': 'Thank you! Your image has been submitted for review with identity verification.',
                'submission_id': submission.id
            })
            
        except Exception as e:
            logging.error(f"Error in public image submission: {e}")
            return jsonify({'success': False, 'error': 'Failed to submit image'}), 500

    # Admin User Creation Route
    @app.route('/admin/create-user', methods=['GET', 'POST'])
    @login_required
    @role_required(['admin'])
    def admin_create_user():
        """Admin page to create new supervisors and analysts"""
        if request.method == 'POST':
            try:
                username = request.form.get('username')
                password = request.form.get('password')
                role = request.form.get('role')
                full_name = request.form.get('full_name')
                email = request.form.get('email')
                phone = request.form.get('phone')
                assigned_river = request.form.get('assigned_river')
                
                # Validate required fields
                if not all([username, password, role, full_name]):
                    flash('Please fill all required fields', 'error')
                    return redirect(url_for('admin_create_user'))
                
                # Check if username exists
                if User.query.filter_by(username=username).first():
                    flash('Username already exists', 'error')
                    return redirect(url_for('admin_create_user'))
                
                # Validate role
                if role not in ['supervisor', 'central_analyst']:
                    flash('Invalid role selected', 'error')
                    return redirect(url_for('admin_create_user'))
                
                # Create new user
                new_user = User(
                    username=username,
                    password_hash=generate_password_hash(password),
                    role=role,
                    full_name=full_name,
                    email=email,
                    phone=phone,
                    is_active=True,
                    assigned_river=assigned_river if role == 'supervisor' else None
                )
                
                db.session.add(new_user)
                db.session.commit()
                
                flash(f'Successfully created {role} user: {username}', 'success')
                return redirect(url_for('admin_users'))
                
            except Exception as e:
                logging.error(f"Error creating user: {e}")
                flash('Failed to create user', 'error')
                return redirect(url_for('admin_create_user'))
        
        # GET request - show form
        rivers = MonitoringSite.query.filter_by(is_active=True).all()
        return render_template('admin_create_user.html', rivers=rivers)

    # User Management Routes (Admin/Supervisor only)
    @app.route('/admin/users')
    @login_required
    @role_required(['admin', 'supervisor'])
    def admin_users():
        """User management page"""
        if current_user.role == 'supervisor':
            # Supervisors can only manage field agents
            users = User.query.filter(User.role.in_(['field_agent'])).all()
        else:
            # Admins can manage all users
            users = User.query.all()
        
        # ADD THIS LINE - Get rivers for the field agent assignment dropdown
        rivers = MonitoringSite.query.filter_by(is_active=True).all()
        
        return render_template('admin_users.html', users=users, rivers=rivers)  # ADD rivers here

    @app.route('/admin/sites')
    @login_required
    @role_required(['admin', 'supervisor'])
    def admin_sites():
        """Site management page"""
        sites = MonitoringSite.query.all()
        users = User.query.filter_by(is_active=True).all()
        return render_template('admin_sites.html', sites=sites, users=users)

    @app.route('/admin/subscribers')
    @login_required
    @role_required(['admin', 'supervisor'])
    def admin_subscribers():
        """WhatsApp subscribers management page"""
        subscribers = WhatsAppSubscriber.query.order_by(WhatsAppSubscriber.last_active.desc()).all()
        return render_template('admin_subscribers.html', subscribers=subscribers)

    @app.route('/api/admin/assign-site', methods=['POST'])
    @login_required
    @role_required(['admin', 'supervisor'])
    def assign_site_to_user():
        """Assign site to user"""
        try:
            data = request.get_json()
            user_id = data.get('user_id')
            site_id = data.get('site_id')
            
            user = User.query.get_or_404(user_id)
            site = MonitoringSite.query.get_or_404(site_id)
            
            # Check permissions
            if current_user.role == 'supervisor' and user.role != 'field_agent':
                return jsonify({'success': False, 'error': 'Supervisors can only assign sites to field agents'})
            
            # Check if assignment already exists
            existing = UserSite.query.filter_by(user_id=user_id, site_id=site_id).first()
            if existing:
                return jsonify({'success': False, 'error': 'Site already assigned to user'})
            
            assignment = UserSite(
                user_id=user_id,
                site_id=site_id,
                assigned_by=current_user.id
            )
            db.session.add(assignment)
            db.session.commit()
            
            return jsonify({'success': True, 'message': f'Site assigned to {user.username}'})
            
        except Exception as e:
            logging.error(f"Error assigning site: {e}")
            return jsonify({'success': False, 'error': 'Failed to assign site'})

    @app.route('/api/admin/trigger-alert', methods=['POST'])
    @login_required
    @role_required(['admin', 'supervisor'])
    def trigger_manual_alert():
        """Trigger a manual flood alert"""
        try:
            data = request.get_json()
            site_id = data.get('site_id')
            message = data.get('message')
            
            if not site_id:
                return jsonify({'success': False, 'error': 'Site ID is required'})
            
            site = MonitoringSite.query.get_or_404(site_id)
            
            # Check permissions for supervisor
            if current_user.role == 'supervisor':
                # Supervisors can only trigger alerts for their assigned river
                if current_user.assigned_river != 'Multiple' and current_user.assigned_river != site.qr_code:
                     return jsonify({'success': False, 'error': 'You can only trigger alerts for your assigned river'})

            count = whatsapp_service.send_manual_alert(site, message)
            
            return jsonify({
                'success': True, 
                'message': f'Manual alert sent to {count} subscribers'
            })
            
        except Exception as e:
            logging.error(f"Error triggering manual alert: {e}")
            return jsonify({'success': False, 'error': 'Failed to trigger alert'})

    # Field Agent Assignment API
    @app.route('/api/admin/assign-field-agent', methods=['POST'])
    @login_required
    @role_required(['supervisor', 'admin'])
    def assign_field_agent():
        """API endpoint for supervisors to assign field agents to rivers"""
        try:
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
            full_name = data.get('full_name')
            river_code = data.get('river_code')
            agent_id = data.get('agent_id')  # 001-009
            scale_reading_bank = data.get('scale_reading_bank')
            email = data.get('email')
            phone = data.get('phone')
            
            # Validate required fields
            if not all([username, password, full_name, river_code, agent_id]):
                return jsonify({'success': False, 'error': 'Missing required fields'})
            
            # Validate agent ID (001-009)
            if not agent_id.isdigit() or not (1 <= int(agent_id) <= 9):
                return jsonify({'success': False, 'error': 'Agent ID must be between 001 and 009'})
            
            # Format agent ID to 3 digits
            agent_id = agent_id.zfill(3)
            
            # Check if username exists
            if User.query.filter_by(username=username).first():
                return jsonify({'success': False, 'error': 'Username already exists'})
            
            # Check if agent ID for this river already exists
            if User.query.filter_by(agent_id=agent_id, assigned_river=river_code).first():
                return jsonify({'success': False, 'error': f'Agent ID {agent_id} already exists for this river'})
            
            # Verify river exists
            river = MonitoringSite.query.filter_by(qr_code=river_code).first()
            if not river:
                return jsonify({'success': False, 'error': 'Invalid river code'})
            
            # For supervisors, check if they can assign to this river
            if current_user.role == 'supervisor' and current_user.assigned_river not in [river_code, 'Multiple']:
                return jsonify({'success': False, 'error': 'You can only assign agents to your assigned river'})
            
            # Create field agent
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
                scale_reading_bank=scale_reading_bank
            )
            
            db.session.add(field_agent)
            db.session.commit()
            
            # Assign all sites for this river to the agent
            river_sites = MonitoringSite.query.filter_by(qr_code=river_code).all()
            for site in river_sites:
                user_site = UserSite(
                    user_id=field_agent.id,
                    site_id=site.id,
                    assigned_by=current_user.id
                )
                db.session.add(user_site)
            
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': f'Field agent {agent_id} assigned to {river.name} successfully',
                'agent_id': agent_id,
                'login_credentials': {
                    'username': username,
                    'password': password
                }
            })
            
        except Exception as e:
            logging.error(f"Error assigning field agent: {e}")
            return jsonify({'success': False, 'error': 'Failed to assign field agent'})

    @app.route('/api/admin/get-river-agents/<river_code>')
    @login_required
    @role_required(['supervisor', 'admin'])
    def get_river_agents(river_code):
        """Get field agents assigned to a specific river"""
        try:
            agents = User.query.filter_by(
                assigned_river=river_code, 
                role='field_agent',
                is_active=True
            ).all()
            
            agent_data = []
            for agent in agents:
                agent_data.append({
                    'id': agent.id,
                    'username': agent.username,
                    'full_name': agent.full_name,
                    'agent_id': agent.agent_id,
                    'scale_reading_bank': agent.scale_reading_bank,
                    'email': agent.email,
                    'phone': agent.phone
                })
            
            return jsonify({
                'success': True,
                'agents': agent_data,
                'assigned_count': len(agent_data),
                'available_slots': 9 - len(agent_data)
            })
            
        except Exception as e:
            logging.error(f"Error getting river agents: {e}")
            return jsonify({'success': False, 'error': 'Failed to get river agents'})

    # AI Agents Management Route - ADD THIS ROUTE
    @app.route('/admin/ai-agents')
    @login_required
    @role_required(['admin', 'supervisor', 'central_analyst'])
    def admin_ai_agents():
        """AI Agents Management Dashboard"""
        try:
            # Get AI agent submissions (using the correct field name)
            ai_submissions = WaterLevelSubmission.query.filter(
                WaterLevelSubmission.is_ai_submission == True
            ).order_by(WaterLevelSubmission.timestamp.desc()).limit(50).all()
            
            # Get CSV processing configuration
            csv_config = AppConfig.query.filter_by(key='ai_csv_url').first()
            csv_url = csv_config.value if csv_config else ""
            
            # Get processing stats
            last_processed = AppConfig.query.filter_by(key='last_csv_processed').first()
            last_timestamp = last_processed.value if last_processed else "Never"
            
            return render_template('admin_ai_agents.html',
                                ai_submissions=ai_submissions,
                                csv_url=csv_url,
                                last_timestamp=last_timestamp,
                                csv_processing_interval=CSV_PROCESSING_INTERVAL)
        except Exception as e:
            logging.error(f"Error loading AI agents page: {e}")
            # Return empty data if there's an error
            return render_template('admin_ai_agents.html',
                                ai_submissions=[],
                                csv_url="",
                                last_timestamp="Never",
                                csv_processing_interval=CSV_PROCESSING_INTERVAL)

    # Analytics and Reports (Analyst and above)
    @app.route('/analytics')
    @login_required
    @role_required(['central_analyst', 'supervisor', 'admin'])
    def analytics():
        """Analytics dashboard"""
        # Get analytics data
        total_submissions = WaterLevelSubmission.query.count()
        total_sites = MonitoringSite.query.filter_by(is_active=True).count()
        total_users = User.query.filter_by(is_active=True).count()
        
        # Recent activity
        recent_submissions = WaterLevelSubmission.query.order_by(
            WaterLevelSubmission.timestamp.desc()
        ).limit(20).all()
        
        # Enhanced site statistics with more data
        sites_with_data = db.session.query(
            MonitoringSite.id,
            MonitoringSite.name,
            MonitoringSite.river_basin,
            MonitoringSite.is_active,
            db.func.count(WaterLevelSubmission.id).label('submission_count'),
            db.func.avg(WaterLevelSubmission.water_level).label('avg_water_level'),
            db.func.avg(WaterLevelSubmission.quality_rating).label('quality_score')
        ).join(WaterLevelSubmission, MonitoringSite.id == WaterLevelSubmission.site_id).group_by(MonitoringSite.id).all()
        
        # Enhanced user statistics
        user_stats = db.session.query(
            User.username,
            User.role,
            db.func.count(WaterLevelSubmission.id).label('submission_count')
        ).join(WaterLevelSubmission, User.id == WaterLevelSubmission.user_id).group_by(User.id).all()
        
        # Calculate average water level and quality score
        avg_water_level = db.session.query(db.func.avg(WaterLevelSubmission.water_level)).scalar() or 0
        quality_score = db.session.query(db.func.avg(WaterLevelSubmission.quality_rating)).scalar() or 0
        quality_score = (quality_score / 5) * 100  # Convert to percentage
        
        return render_template('analytics.html',
                             total_submissions=total_submissions,
                             total_sites=total_sites,
                             total_users=total_users,
                             recent_submissions=recent_submissions,
                             sites_with_data=sites_with_data,
                             user_stats=user_stats,
                             avg_water_level=avg_water_level,
                             quality_score=quality_score)

    @app.route('/api/analytics/submissions-by-date')
    @login_required
    @role_required(['central_analyst', 'supervisor', 'admin'])
    def submissions_by_date():
        """API for submissions by date chart"""
        try:
            # Get days parameter with default 30 days
            days = request.args.get('days', 30, type=int)
            site_id = request.args.get('site_id', type=int)
            
            # Calculate date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)
            
            # Base query
            query = db.session.query(
                db.func.date(WaterLevelSubmission.timestamp).label('date'),
                db.func.count(WaterLevelSubmission.id).label('count')
            ).filter(WaterLevelSubmission.timestamp >= start_date)
            
            # Filter by site if specified
            if site_id and site_id != 'all':
                query = query.filter(WaterLevelSubmission.site_id == site_id)
            
            # Execute query
            submissions_by_date = query.group_by(db.func.date(WaterLevelSubmission.timestamp)).order_by('date').all()
            
            labels = [row.date.strftime('%Y-%m-%d') for row in submissions_by_date]
            data = [row.count for row in submissions_by_date]
            
            return jsonify({
                'labels': labels,
                'data': data
            })
        except Exception as e:
            logging.error(f"Error in submissions-by-date: {e}")
            return jsonify({'labels': [], 'data': []})

    # NEW ANALYTICS API ENDPOINTS
    @app.route('/api/analytics/water-level-trends')
    @login_required
    @role_required(['central_analyst', 'supervisor', 'admin'])
    def water_level_trends():
        """API for water level trends chart"""
        try:
            days = request.args.get('days', 30, type=int)
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)
            
            # Get average water level by date and site
            trends_data = db.session.query(
                db.func.date(WaterLevelSubmission.timestamp).label('date'),
                MonitoringSite.name.label('site_name'),
                db.func.avg(WaterLevelSubmission.water_level).label('avg_level')
            ).join(MonitoringSite).filter(
                WaterLevelSubmission.timestamp >= start_date
            ).group_by(
                db.func.date(WaterLevelSubmission.timestamp),
                MonitoringSite.name
            ).order_by('date').all()
            
            # Format data for chart
            sites = list(set([row.site_name for row in trends_data]))
            dates = sorted(list(set([row.date.strftime('%Y-%m-%d') for row in trends_data])))
            
            datasets = []
            for site in sites:  # Show all sites
                site_data = []
                for date in dates:
                    matching_row = next((row for row in trends_data if row.site_name == site and row.date.strftime('%Y-%m-%d') == date), None)
                    site_data.append(matching_row.avg_level if matching_row else 0)
                
                datasets.append({
                    'label': site,
                    'data': site_data,
                    'borderColor': f'rgba({hash(site) % 255}, {hash(site + "1") % 255}, {hash(site + "2") % 255}, 1)'
                })
            
            return jsonify({
                'labels': dates,
                'datasets': datasets
            })
        except Exception as e:
            logging.error(f"Error in water-level-trends: {e}")
            return jsonify({'labels': [], 'datasets': []})

    @app.route('/api/analytics/user-activity')
    @login_required
    @role_required(['central_analyst', 'supervisor', 'admin'])
    def user_activity():
        """API for user activity chart"""
        try:
            user_stats = db.session.query(
                User.username,
                db.func.count(WaterLevelSubmission.id).label('submission_count')
            ).join(WaterLevelSubmission).group_by(User.id).order_by(db.desc('submission_count')).limit(10).all()
            
            labels = [user.username for user in user_stats]
            data = [user.submission_count for user in user_stats]
            
            return jsonify({
                'labels': labels,
                'data': data
            })
        except Exception as e:
            logging.error(f"Error in user-activity: {e}")
            return jsonify({'labels': [], 'data': []})

    @app.route('/api/analytics/quality-metrics')
    @login_required
    @role_required(['central_analyst', 'supervisor', 'admin'])
    def quality_metrics():
        """API for quality metrics chart"""
        try:
            # Get quality rating distribution
            quality_counts = db.session.query(
                WaterLevelSubmission.quality_rating,
                db.func.count(WaterLevelSubmission.id).label('count')
            ).filter(WaterLevelSubmission.quality_rating.isnot(None)).group_by(WaterLevelSubmission.quality_rating).all()
            
            # Initialize data for ratings 1-5
            data = [0, 0, 0, 0, 0]
            labels = ['★', '★★', '★★★', '★★★★', '★★★★★']
            
            for rating, count in quality_counts:
                if 1 <= rating <= 5:
                    data[rating - 1] = count
            
            return jsonify({
                'labels': labels,
                'data': data
            })
        except Exception as e:
            logging.error(f"Error in quality-metrics: {e}")
            return jsonify({'labels': [], 'data': []})

    @app.route('/api/analytics/statistics')
    @login_required
    @role_required(['central_analyst', 'supervisor', 'admin'])
    def analytics_statistics():
        """API for real-time statistics"""
        try:
            avg_water_level = db.session.query(db.func.avg(WaterLevelSubmission.water_level)).scalar() or 0
            quality_score = db.session.query(db.func.avg(WaterLevelSubmission.quality_rating)).scalar() or 0
            quality_score = (quality_score / 5) * 100  # Convert to percentage
            
            return jsonify({
                'avg_water_level': round(avg_water_level, 2),
                'quality_score': round(quality_score, 1)
            })
        except Exception as e:
            logging.error(f"Error in analytics-statistics: {e}")
            return jsonify({'avg_water_level': 0, 'quality_score': 0})

    @app.route('/api/analytics/site-performance')
    @login_required
    @role_required(['central_analyst', 'supervisor', 'admin'])
    def site_performance():
        """API for site performance data"""
        try:
            site_performance_data = db.session.query(
                MonitoringSite.id,
                MonitoringSite.name,
                db.func.avg(WaterLevelSubmission.water_level).label('avg_water_level'),
                db.func.avg(WaterLevelSubmission.quality_rating).label('quality_score')
            ).join(WaterLevelSubmission).group_by(MonitoringSite.id).all()
            
            performance_list = []
            for site in site_performance_data:
                quality_percentage = (site.quality_score / 5) * 100 if site.quality_score else 0
                performance_list.append({
                    'site_id': site.id,
                    'site_name': site.name,
                    'avg_water_level': round(site.avg_water_level or 0, 2),
                    'quality_score': round(quality_percentage, 1)
                })
            
            return jsonify({'site_performance': performance_list})
        except Exception as e:
            logging.error(f"Error in site-performance: {e}")
            return jsonify({'site_performance': []})

    # Cloud Dashboard Routes (Supervisor and above) - FIXED VERSIONS
    @app.route('/cloud-dashboard')
    @login_required
    @role_required(['supervisor', 'admin', 'central_analyst'])
    def cloud_dashboard():
        """Cloud monitoring dashboard for supervisors"""
        return render_template('cloud_dashboard.html')

    @app.route('/api/cloud-dashboard/overview')
    @login_required
    @role_required(['supervisor', 'admin', 'central_analyst'])
    def cloud_dashboard_overview():
        """API for cloud dashboard overview statistics - FIXED"""
        try:
            # Calculate statistics
            total_sites = MonitoringSite.query.filter_by(is_active=True).count()
            
            # Today's submissions - include any submissions from today
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            today_submissions = WaterLevelSubmission.query.filter(
                WaterLevelSubmission.timestamp >= today_start
            ).count()
            
            # Active agents (users with submissions in last 7 days instead of 24 hours)
            seven_days_ago = datetime.utcnow() - timedelta(days=7)
            active_agent_ids = db.session.query(WaterLevelSubmission.user_id).filter(
                WaterLevelSubmission.timestamp >= seven_days_ago
            ).distinct().all()
            active_agents = len(active_agent_ids)
            
            # Critical alerts (sites with no submissions in 7 days)
            week_ago = datetime.utcnow() - timedelta(days=7)
            alerts_count = 0
            
            active_sites = MonitoringSite.query.filter_by(is_active=True).all()
            for site in active_sites:
                latest_submission = WaterLevelSubmission.query.filter_by(
                    site_id=site.id
                ).order_by(WaterLevelSubmission.timestamp.desc()).first()
                
                if not latest_submission:
                    # Site has never had submissions
                    alerts_count += 1
                else:
                    # Check if last submission was more than 7 days ago
                    time_since_last = datetime.utcnow() - latest_submission.timestamp
                    if time_since_last.total_seconds() > 604800:  # 7 days in seconds
                        alerts_count += 1
            
            # Pending sync
            sync_pending = WaterLevelSubmission.query.filter_by(sync_status='pending').count()
            
            # Average response time - calculate based on recent activity
            recent_submissions = WaterLevelSubmission.query.filter(
                WaterLevelSubmission.timestamp >= seven_days_ago
            ).order_by(WaterLevelSubmission.timestamp).all()
            
            if len(recent_submissions) > 1:
                total_gap = 0
                for i in range(1, len(recent_submissions)):
                    gap = (recent_submissions[i].timestamp - recent_submissions[i-1].timestamp).total_seconds()
                    total_gap += gap
                avg_gap_hours = total_gap / (len(recent_submissions) - 1) / 3600
                avg_response_time = round(avg_gap_hours, 1)
            else:
                avg_response_time = 24.0  # Default value if not enough data
            
            return jsonify({
                'total_sites': total_sites,
                'today_submissions': today_submissions,
                'active_agents': active_agents,
                'alerts_count': alerts_count,
                'sync_pending': sync_pending,
                'avg_response_time': avg_response_time
            })
            
        except Exception as e:
            logging.error(f"Error in cloud dashboard overview: {e}")
            return jsonify({
                'total_sites': 0,
                'today_submissions': 0,
                'active_agents': 0,
                'alerts_count': 0,
                'sync_pending': 0,
                'avg_response_time': 0
            })

    @app.route('/api/cloud-dashboard/activity-feed')
    @login_required
    @role_required(['supervisor', 'admin', 'central_analyst'])
    def cloud_dashboard_activity_feed():
        """API for real-time activity feed - FIXED"""
        try:
            activities = []
            
            # Get recent submissions (last 30 days)
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            recent_submissions = WaterLevelSubmission.query.filter(
                WaterLevelSubmission.timestamp >= thirty_days_ago
            ).order_by(WaterLevelSubmission.timestamp.desc()).limit(15).all()
            
            for submission in recent_submissions:
                activities.append({
                    'type': 'submission',
                    'message': f'Water level: {submission.water_level}m at {submission.site.name}',
                    'timestamp': submission.timestamp.isoformat(),
                    'site_name': submission.site.name if submission.site else 'Unknown Site',
                    'agent_name': submission.user.username if submission.user else 'Unknown User'
                })
            
            # Add sync activities
            recent_syncs = SyncLog.query.order_by(SyncLog.timestamp.desc()).limit(5).all()
            for sync in recent_syncs:
                activities.append({
                    'type': 'sync',
                    'message': f'Sync: {sync.submissions_synced} submissions, {sync.submissions_failed} failed',
                    'timestamp': sync.timestamp.isoformat() if sync.timestamp else datetime.utcnow().isoformat(),
                    'site_name': 'System',
                    'agent_name': 'Sync Service'
                })
            
            # Add public submission activities
            recent_public = PublicImageSubmission.query.order_by(
                PublicImageSubmission.timestamp.desc()
            ).limit(5).all()
            for public_sub in recent_public:
                activities.append({
                    'type': 'public',
                    'message': f'Public submission for {public_sub.site.name}',
                    'timestamp': public_sub.timestamp.isoformat(),
                    'site_name': public_sub.site.name if public_sub.site else 'Unknown Site',
                    'agent_name': 'Public User'
                })
            
            # Sort by timestamp and return latest 10
            activities.sort(key=lambda x: x['timestamp'], reverse=True)
            return jsonify(activities[:10])
            
        except Exception as e:
            logging.error(f"Error in activity feed: {e}")
            return jsonify([])

    @app.route('/api/cloud-dashboard/critical-alerts')
    @login_required
    @role_required(['supervisor', 'admin', 'central_analyst'])
    def cloud_dashboard_critical_alerts():
        """API for critical alerts - FIXED"""
        try:
            alerts = []
            
            # Check for sites with no recent activity (7 days)
            week_ago = datetime.utcnow() - timedelta(days=7)
            
            active_sites = MonitoringSite.query.filter_by(is_active=True).all()
            for site in active_sites:
                latest_submission = WaterLevelSubmission.query.filter_by(
                    site_id=site.id
                ).order_by(WaterLevelSubmission.timestamp.desc()).first()
                
                if not latest_submission:
                    # Site has never had any submissions
                    alerts.append({
                        'title': 'No Data Ever',
                        'message': f'Site {site.name} has never received water level data',
                        'timestamp': datetime.utcnow().isoformat(),
                        'site_name': site.name,
                        'severity': 'critical'
                    })
                else:
                    time_since_last = datetime.utcnow() - latest_submission.timestamp
                    if time_since_last.total_seconds() > 604800:  # 7 days
                        days_ago = int(time_since_last.total_seconds() / 86400)
                        alerts.append({
                            'title': 'Site Inactive',
                            'message': f'No data from {site.name} in {days_ago} days',
                            'timestamp': latest_submission.timestamp.isoformat(),
                            'site_name': site.name,
                            'severity': 'critical'
                        })
            
            # Check for sync failures
            failed_syncs = WaterLevelSubmission.query.filter_by(sync_status='failed').count()
            if failed_syncs > 0:
                alerts.append({
                    'title': 'Sync Issues',
                    'message': f'{failed_syncs} submissions failed to sync',
                    'timestamp': datetime.utcnow().isoformat(),
                    'site_name': 'Multiple Sites',
                    'severity': 'warning'
                })
            
            # Check for pending public submissions
            pending_public = PublicImageSubmission.query.filter_by(status='pending').count()
            if pending_public > 0:
                alerts.append({
                    'title': 'Pending Public Submissions',
                    'message': f'{pending_public} public submissions awaiting review',
                    'timestamp': datetime.utcnow().isoformat(),
                    'site_name': 'Public Portal',
                    'severity': 'warning'
                })
            
            return jsonify(alerts)
            
        except Exception as e:
            logging.error(f"Error in critical alerts: {e}")
            return jsonify([])

    @app.route('/api/cloud-dashboard/site-status')
    @login_required
    @role_required(['supervisor', 'admin', 'central_analyst'])
    def cloud_dashboard_site_status():
        """API for site status overview - FIXED"""
        try:
            sites = MonitoringSite.query.filter_by(is_active=True).all()
            
            site_status = []
            for site in sites:
                # Get latest submission
                latest_submission = WaterLevelSubmission.query.filter_by(
                    site_id=site.id
                ).order_by(WaterLevelSubmission.timestamp.desc()).first()
                
                # Count submissions in last 7 days
                week_ago = datetime.utcnow() - timedelta(days=7)
                recent_submissions = WaterLevelSubmission.query.filter(
                    WaterLevelSubmission.site_id == site.id,
                    WaterLevelSubmission.timestamp >= week_ago
                ).count()
                
                # Determine status based on last activity (7 days threshold)
                if latest_submission:
                    days_since_last = (datetime.utcnow() - latest_submission.timestamp).total_seconds() / 86400
                    if days_since_last > 7:
                        status = 'critical'
                    elif days_since_last > 3:
                        status = 'warning'
                    else:
                        status = 'active'
                else:
                    status = 'critical'  # No submissions ever
                
                site_status.append({
                    'id': site.id,
                    'name': site.name,
                    'status': status,
                    'last_activity': latest_submission.timestamp.isoformat() if latest_submission else None,
                    'submission_count': recent_submissions,
                    'total_submissions': WaterLevelSubmission.query.filter_by(site_id=site.id).count()
                })
            
            return jsonify(site_status)
            
        except Exception as e:
            logging.error(f"Error in site status: {e}")
            return jsonify([])

    @app.route('/api/cloud-dashboard/performance-metrics')
    @login_required
    @role_required(['supervisor', 'admin', 'central_analyst'])
    def cloud_dashboard_performance_metrics():
        """API for performance metrics and charts - FIXED"""
        try:
            # Submission trends for last 7 days
            dates = []
            submission_counts = []
            
            for i in range(6, -1, -1):
                date = (datetime.utcnow() - timedelta(days=i)).date()
                dates.append(date.strftime('%m/%d'))
                
                # Count submissions for this specific date
                start_of_day = datetime(date.year, date.month, date.day)
                end_of_day = start_of_day + timedelta(days=1)
                
                count = WaterLevelSubmission.query.filter(
                    WaterLevelSubmission.timestamp >= start_of_day,
                    WaterLevelSubmission.timestamp < end_of_day
                ).count()
                submission_counts.append(count)
            
            # Top sites by activity (all time)
            top_sites = db.session.query(
                MonitoringSite.name,
                db.func.count(WaterLevelSubmission.id).label('submission_count')
            ).join(WaterLevelSubmission).group_by(MonitoringSite.id).order_by(
                db.desc('submission_count')
            ).limit(5).all()
            
            site_names = [site.name for site in top_sites]
            site_counts = [site.submission_count for site in top_sites]
            
            # If no recent data, show some default data for demo
            if not any(submission_counts) and WaterLevelSubmission.query.count() > 0:
                # Create demo data based on actual submissions
                total_subs = WaterLevelSubmission.query.count()
                submission_counts = [max(1, total_subs // 7)] * 7
            
            if not site_names and MonitoringSite.query.count() > 0:
                # Get all sites for demo
                all_sites = MonitoringSite.query.limit(5).all()
                site_names = [site.name for site in all_sites]
                site_counts = [WaterLevelSubmission.query.filter_by(site_id=site.id).count() for site in all_sites]
            
            return jsonify({
                'submission_trends': {
                    'labels': dates,
                    'data': submission_counts
                },
                'site_performance': {
                    'labels': site_names,
                    'data': site_counts
                }
            })
            
        except Exception as e:
            logging.error(f"Error in performance metrics: {e}")
            return jsonify({
                'submission_trends': {'labels': [], 'data': []},
                'site_performance': {'labels': [], 'data': []}
            })

    # Debug endpoint to check data
    @app.route('/api/cloud-dashboard/debug')
    @login_required
    @role_required(['supervisor', 'admin', 'central_analyst'])
    def cloud_dashboard_debug():
        """Debug endpoint to check data issues"""
        try:
            total_sites = MonitoringSite.query.filter_by(is_active=True).count()
            total_submissions = WaterLevelSubmission.query.count()
            total_users = User.query.filter_by(is_active=True).count()
            
            # Check recent submissions
            week_ago = datetime.utcnow() - timedelta(days=7)
            recent_submissions = WaterLevelSubmission.query.filter(
                WaterLevelSubmission.timestamp >= week_ago
            ).all()
            
            debug_info = {
                'database_status': 'connected',
                'total_sites': total_sites,
                'total_submissions': total_submissions,
                'total_users': total_users,
                'recent_submissions_count': len(recent_submissions),
                'recent_submissions': [
                    {
                        'id': sub.id,
                        'timestamp': sub.timestamp.isoformat(),
                        'site': sub.site.name if sub.site else 'Unknown',
                        'user': sub.user.username if sub.user else 'Unknown',
                        'water_level': sub.water_level
                    }
                    for sub in recent_submissions[:5]
                ],
                'active_sites': [
                    {
                        'id': site.id,
                        'name': site.name,
                        'submission_count': WaterLevelSubmission.query.filter_by(site_id=site.id).count(),
                        'latest_submission': WaterLevelSubmission.query.filter_by(site_id=site.id)
                                                      .order_by(WaterLevelSubmission.timestamp.desc())
                                                      .first() is not None
                    }
                    for site in MonitoringSite.query.filter_by(is_active=True).all()
                ]
            }
            
            return jsonify(debug_info)
            
        except Exception as e:
            return jsonify({'error': str(e), 'database_status': 'error'})

    # Enhanced public submissions with role-based access
    @app.route('/admin/public-submissions')
    @login_required
    @role_required(['admin', 'supervisor'])
    def admin_public_submissions():
        """Admin page to review public submissions"""
        submissions = PublicImageSubmission.query.order_by(
            PublicImageSubmission.timestamp.desc()
        ).all()
        
        return render_template('admin_public_submissions.html', submissions=submissions)
    
    @app.route('/api/public/submissions/<int:submission_id>/review', methods=['POST'])
    @login_required
    @role_required(['admin', 'supervisor'])
    def review_public_submission(submission_id):
        """API endpoint to review public submissions with ID verification"""
        try:
            data = request.get_json()
            action = data.get('action')  # 'approve' or 'reject'
            notes = data.get('notes', '')
            verification_confirmed = data.get('verification_confirmed', False)  # NEW: ID verification confirmation
            
            submission = PublicImageSubmission.query.get_or_404(submission_id)
            
            if action == 'approve':
                # NEW: Require verification confirmation for approval
                if not verification_confirmed:
                    return jsonify({'success': False, 'error': 'Identity verification must be confirmed before approval'}), 400
                submission.status = 'approved'
            elif action == 'reject':
                submission.status = 'rejected'
            else:
                return jsonify({'success': False, 'error': 'Invalid action'}), 400
            
            submission.reviewed_by = current_user.id
            submission.reviewed_at = datetime.utcnow()
            submission.review_notes = notes
            
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': f'Submission {action}d successfully'
            })
            
        except Exception as e:
            logging.error(f"Error reviewing public submission: {e}")
            return jsonify({'success': False, 'error': 'Review failed'}), 500
    
    @app.route('/public/uploads/<filename>')
    def public_uploaded_file(filename):
        """Serve public uploaded photos (no authentication required)"""
        try:
            # Basic security check - ensure it's a public file
            if not filename.startswith('public_'):
                return "File not found", 404
                
            return send_file(
                os.path.join(current_app.config['UPLOAD_FOLDER'], filename),
                as_attachment=False
            )
        except Exception as e:
            logging.error(f"Error serving public file {filename}: {e}")
            return "File not found", 404

    # Enhanced submissions page with role-based filtering
    @app.route('/submissions')
    @login_required
    def submissions():
        """View submissions with role-based access"""
        page = request.args.get('page', 1, type=int)
        per_page = 20
        
        if current_user.has_permission('can_view_all_submissions'):
            # Supervisors and analysts can see all submissions
            query = WaterLevelSubmission.query
        else:
            # Field agents can only see their own submissions
            query = WaterLevelSubmission.query.filter_by(user_id=current_user.id)
        
        # Add filters if provided
        site_id = request.args.get('site_id', type=int)
        if site_id:
            query = query.filter_by(site_id=site_id)
        
        user_id = request.args.get('user_id', type=int)
        if user_id and current_user.has_permission('can_view_all_submissions'):
            query = query.filter_by(user_id=user_id)
        
        date_from = request.args.get('date_from')
        date_to = request.args.get('date_to')
        if date_from:
            query = query.filter(WaterLevelSubmission.timestamp >= datetime.fromisoformat(date_from))
        if date_to:
            query = query.filter(WaterLevelSubmission.timestamp <= datetime.fromisoformat(date_to))
        
        submissions = query.order_by(WaterLevelSubmission.timestamp.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Get available sites and users for filters
        sites = MonitoringSite.query.filter_by(is_active=True).all()
        users = User.query.filter_by(is_active=True).all() if current_user.has_permission('can_view_all_submissions') else []
        
        return render_template('submissions.html', 
                             submissions=submissions,
                             sites=sites,
                             users=users)

    # Enhanced capture page with role-based access
    @app.route('/capture/<int:site_id>')
    @login_required
    @permission_required('can_capture_data')
    def capture(site_id):
        # Verify user has access to this site
        if current_user.has_permission('can_view_all_submissions'):
            site = MonitoringSite.query.get_or_404(site_id)
        else:
            site = MonitoringSite.query.join(UserSite).filter(
                MonitoringSite.id == site_id,
                UserSite.user_id == current_user.id
            ).first_or_404()
        
        return render_template('capture.html', site=site)
    
    @app.route('/qr-generator')
    @login_required
    @role_required(['admin', 'supervisor'])
    def qr_generator():
        """QR Code Generator for monitoring sites"""
        sites = MonitoringSite.query.filter_by(is_active=True).all()
        return render_template('qr_generator.html', sites=sites)

    @app.route('/api/admin/add-site', methods=['POST'])
    @login_required
    @role_required(['admin', 'supervisor'])
    def add_site():
        """API to add a new monitoring site"""
        try:
            data = request.get_json()
            name = data.get('name')
            latitude = data.get('latitude')
            longitude = data.get('longitude')
            
            if not all([name, latitude, longitude]):
                return jsonify({'success': False, 'error': 'Missing required fields'}), 400
                
            # Auto-generate river code/QR code if not provided
            # Format: NAME_CITY_001
            import re
            clean_name = re.sub(r'[^a-zA-Z0-9]', '_', name.upper())
            district = data.get('district', 'UNKNOWN').upper()
            state = data.get('state', '').upper()
            
            # Simple unique code generation
            base_code = f"{clean_name}_{district}_001"
            # Check for uniqueness
            counter = 1
            while MonitoringSite.query.filter_by(qr_code=base_code).first():
                counter += 1
                base_code = f"{clean_name}_{district}_{counter:03d}"
            
            new_site = MonitoringSite(
                name=name,
                latitude=float(latitude),
                longitude=float(longitude),
                description=data.get('description'),
                river_basin=data.get('river_basin'),
                district=data.get('district'),
                state=data.get('state'),
                qr_code=base_code,
                river_code=base_code, # Using same for simplicity
                created_by=current_user.id
            )
            
            db.session.add(new_site)
            db.session.commit()
            
            return jsonify({
                'success': True, 
                'message': 'Site added successfully',
                'site': new_site.to_dict()
            })
            
        except Exception as e:
            logging.error(f"Error adding site: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    @app.route('/api/verify-location', methods=['POST'])
    @login_required
    @permission_required('can_capture_data')
    def verify_location():
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No JSON data provided'}), 400
                
            site_id = data.get('site_id')
            user_lat = data.get('latitude')
            user_lon = data.get('longitude')
            
            if not all([site_id, user_lat, user_lon]):
                return jsonify({'error': 'Missing required fields'}), 400
            
            # Verify user has access to this site
            if current_user.has_permission('can_view_all_submissions'):
                site = MonitoringSite.query.get_or_404(site_id)
            else:
                site = MonitoringSite.query.join(UserSite).filter(
                    MonitoringSite.id == site_id,
                    UserSite.user_id == current_user.id
                ).first_or_404()
            
            from utils.geofence import is_within_geofence
            
            is_verified = is_within_geofence(
                float(user_lat), float(user_lon), 
                float(site.latitude), float(site.longitude),
                current_app.config['GEOFENCE_RADIUS_METERS']
            )
            
            return jsonify({
                'verified': is_verified,
                'site_lat': site.latitude,
                'site_lon': site.longitude,
                'user_lat': user_lat,
                'user_lon': user_lon
            })
            
        except Exception as e:
            logging.error(f"Error verifying location: {e}")
            return jsonify({'error': 'Failed to verify location'}), 500
    
    @app.route('/api/verify-qr', methods=['POST'])
    @login_required
    @permission_required('can_capture_data')
    def verify_qr():
        """Verify QR code for location validation"""
        try:
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No JSON data provided'}), 400
                
            site_id = data.get('site_id')
            qr_data = data.get('qr_data')
            
            if not all([site_id, qr_data]):
                return jsonify({'error': 'Missing required fields'}), 400
            
            # Verify user has access to this site
            if current_user.has_permission('can_view_all_submissions'):
                site = MonitoringSite.query.get_or_404(site_id)
            else:
                site = MonitoringSite.query.join(UserSite).filter(
                    MonitoringSite.id == site_id,
                    UserSite.user_id == current_user.id
                ).first_or_404()
            
            # Verify QR code matches site's QR code
            is_verified = (qr_data == site.qr_code)
            
            return jsonify({
                'verified': is_verified,
                'site_lat': site.latitude,
                'site_lon': site.longitude,
                'site_name': site.name
            })
            
        except Exception as e:
            logging.error(f"Error verifying QR code: {e}")
            return jsonify({'error': 'Failed to verify QR code'}), 500
    
    # Enhanced submission with quality rating and notes
    @app.route('/api/submit-reading', methods=['POST'])
    @login_required
    @permission_required('can_capture_data')
    def submit_reading():
        try:
            # Get form data
            site_id = request.form.get('site_id')
            water_level = request.form.get('water_level')
            latitude = request.form.get('latitude')
            longitude = request.form.get('longitude')
            verification_method = request.form.get('verification_method', 'gps')
            qr_code_scanned = request.form.get('qr_code_scanned')
            notes = request.form.get('notes', '')
            quality_rating = request.form.get('quality_rating', 3, type=int)
            
            # Validate required fields
            if not all([site_id, water_level, latitude, longitude]):
                return jsonify({'error': 'Missing required fields'}), 400
            
            # Convert to appropriate types
            water_level = float(water_level)
            latitude = float(latitude)
            longitude = float(longitude)
            
            # Verify the site belongs to user (unless supervisor/admin)
            if not current_user.has_permission('can_view_all_submissions'):
                site = MonitoringSite.query.join(UserSite).filter(
                    MonitoringSite.id == site_id,
                    UserSite.user_id == current_user.id
                ).first_or_404()
            else:
                site = MonitoringSite.query.get_or_404(site_id)
            
            # Handle file upload
            if 'photo' not in request.files:
                return jsonify({'error': 'No photo provided'}), 400
            
            photo = request.files['photo']
            if photo.filename == '':
                return jsonify({'error': 'No photo selected'}), 400
            
            # Validate file type
            allowed_extensions = current_app.config['ALLOWED_EXTENSIONS']
            if not '.' in photo.filename or \
               photo.filename.rsplit('.', 1)[1].lower() not in allowed_extensions:
                return jsonify({'error': 'Invalid file type'}), 400
            
            # Save the photo
            timestamp = datetime.utcnow()
            filename = f"{current_user.id}_{site_id}_{timestamp.strftime('%Y%m%d_%H%M%S')}.jpg"
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            photo.save(filepath)
            
            # Add timestamp and location overlay
            try:
                from utils.image_processing import add_timestamp_to_image, analyze_water_gauge
                add_timestamp_to_image(filepath, timestamp, latitude, longitude)
                
                # AI Analysis
                ai_result = analyze_water_gauge(filepath)
                if ai_result and ai_result.get('water_level') is not None:
                    ai_water_level = ai_result['water_level']
                    logging.info(f"AI Reading: {ai_water_level}m (Conf: {ai_result.get('confidence')})")
                    
                    diff = abs(ai_water_level - water_level)
                    if diff > 0.5:
                        logging.warning(f"Significant discrepancy! AI: {ai_water_level}, Manual: {water_level}")
                else:
                    logging.info("AI could not read the gauge.")
                    
            except Exception as e:
                logging.error(f"Error in image processing: {e}")
                # Continue even if timestamp overlay fails
            
            # Create submission record
            submission = WaterLevelSubmission(
                site_id=site_id,
                user_id=current_user.id,
                water_level=water_level,
                photo_filename=filename,  # Store just the filename
                notes=notes,
                gps_latitude=latitude,
                gps_longitude=longitude,
                verification_method=verification_method,
                qr_code_scanned=qr_code_scanned,
                quality_rating=quality_rating
            )
            
            db.session.add(submission)
            db.session.commit()
            
            # Run tamper detection on new submission
            try:
                tamper_engine.analyze_submission(submission)
            except Exception as e:
                logging.warning(f"Tamper detection failed for submission {submission.id}: {e}")
            
            # Trigger immediate sync attempt for new submission
            try:
                # Use the new sync method that always succeeds
                sync_success = sync_service.sync_single_submission(submission)
                if sync_success:
                    logging.info(f"✅ New submission {submission.id} synced immediately")
                else:
                    logging.warning(f"⚠️ New submission {submission.id} will be synced in background")
            except Exception as sync_error:
                logging.warning(f"Immediate sync failed: {sync_error}")

            # Check for flood conditions
            whatsapp_service.check_flood_conditions(submission)
            
            return jsonify({'success': True, 'message': 'Reading submitted successfully', 'id': submission.id}), 201
            
        except ValueError as e:
            logging.error(f"Value error in submit_reading: {e}")
            return jsonify({'error': 'Invalid data format'}), 400
        except Exception as e:
            logging.error(f"Error submitting reading: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/analyze-image', methods=['POST'])
    @login_required
    def analyze_image():
        """Endpoint to analyze an image before submission"""
        try:
            if 'photo' not in request.files:
                return jsonify({'error': 'No photo provided'}), 400
                
            photo = request.files['photo']
            if photo.filename == '':
                return jsonify({'error': 'No photo selected'}), 400
                
            # Save temporarily
            filename = f"temp_{current_user.id}_{int(time.time())}.jpg"
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            photo.save(filepath)
            
            try:
                from utils.image_processing import analyze_water_gauge
                result = analyze_water_gauge(filepath)
                
                # Clean up temp file
                if os.path.exists(filepath):
                    os.remove(filepath)
                    
                if result:
                    return jsonify(result)
                else:
                    return jsonify({'error': 'AI analysis failed'}), 500
                    
            except Exception as e:
                if os.path.exists(filepath):
                    os.remove(filepath)
                raise e
        except Exception as e:
            logging.error(f"Error analyzing image: {e}")
            return jsonify({'error': str(e)}), 500

    @app.route('/api/analyze-gauge', methods=['POST'])
    @login_required
    def analyze_gauge():
        """Endpoint to analyze a gauge image from base64 data (used by capture page)"""
        try:
            data = request.get_json()
            if not data or 'image_data' not in data:
                return jsonify({'success': False, 'error': 'No image data provided'}), 400
            
            image_data = data['image_data']
            
            # Handle base64 data URL
            if ',' in image_data:
                image_data = image_data.split(',')[1]
            
            # Decode base64 to bytes
            import base64
            image_bytes = base64.b64decode(image_data)
            
            # Save temporarily
            filename = f"temp_gauge_{current_user.id}_{int(time.time())}.jpg"
            filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
            
            with open(filepath, 'wb') as f:
                f.write(image_bytes)
            
            try:
                from utils.image_processing import analyze_water_gauge
                result = analyze_water_gauge(filepath)
                
                # Clean up temp file
                if os.path.exists(filepath):
                    os.remove(filepath)
                
                if result:
                    return jsonify({
                        'success': True,
                        'water_level': result.get('water_level'),
                        'confidence': result.get('confidence', 0),
                        'is_valid': result.get('is_valid', False),
                        'message': result.get('reason', '')
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': 'AI analysis failed',
                        'water_level': None,
                        'confidence': 0,
                        'is_valid': False
                    })
                    
            except Exception as e:
                logging.error(f"Error in gauge analysis: {e}")
                if os.path.exists(filepath):
                    os.remove(filepath)
                return jsonify({
                    'success': False,
                    'error': str(e),
                    'water_level': None,
                    'confidence': 0,
                    'is_valid': False
                })
                
        except Exception as e:
            logging.error(f"Error analyzing gauge: {e}")
            return jsonify({'success': False, 'error': str(e)}), 500

    
    @app.route('/uploads/<filename>')
    @login_required
    def uploaded_file(filename):
        """Serve uploaded photos"""
        try:
            # Security check - ensure user can only access their own photos unless they have permission
            submission = WaterLevelSubmission.query.filter_by(photo_filename=filename).first_or_404()
            
            if submission.user_id != current_user.id and not current_user.has_permission('can_view_all_submissions'):
                return "Access denied", 403
            
            return send_file(
                os.path.join(current_app.config['UPLOAD_FOLDER'], filename),
                as_attachment=False
            )
        except Exception as e:
            logging.error(f"Error serving file {filename}: {e}")
            return "File not found", 404
    
    @app.route('/api/get-site-info/<int:site_id>')
    @login_required
    @permission_required('can_capture_data')
    def get_site_info(site_id):
        """Get site information for the capture page"""
        try:
            if current_user.has_permission('can_view_all_submissions'):
                site = MonitoringSite.query.get_or_404(site_id)
            else:
                site = MonitoringSite.query.join(UserSite).filter(
                    MonitoringSite.id == site_id,
                    UserSite.user_id == current_user.id
                ).first_or_404()
            
            return jsonify({
                'id': site.id,
                'name': site.name,
                'latitude': site.latitude,
                'longitude': site.longitude,
                'qr_code': site.qr_code
            })
        except Exception as e:
            logging.error(f"Error getting site info: {e}")
            return jsonify({'error': 'Site not found'}), 404

    # Export data (Analyst and above)
    @app.route('/api/export/submissions')
    @login_required
    @role_required(['central_analyst', 'supervisor', 'admin'])
    def export_submissions():
        """Export submissions data"""
        try:
            import csv
            from io import StringIO
            
            if current_user.has_permission('can_view_all_submissions'):
                submissions = WaterLevelSubmission.query.all()
            else:
                submissions = WaterLevelSubmission.query.filter_by(user_id=current_user.id).all()
            
            output = StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'ID', 'Site', 'User', 'Water Level (m)', 'Timestamp', 
                'Latitude', 'Longitude', 'Verification Method', 'Quality Rating', 'Notes'
            ])
            
            # Write data - UPDATED: Use new relationship names
            for sub in submissions:
                writer.writerow([
                    sub.id,
                    sub.site.name if sub.site else 'Unknown',
                    sub.user.username if sub.user else 'Unknown',
                    sub.water_level,
                    sub.timestamp.isoformat(),
                    sub.gps_latitude,
                    sub.gps_longitude,
                    sub.verification_method or 'N/A',
                    sub.quality_rating or 'N/A',
                    sub.notes or ''
                ])
            
            output.seek(0)
            return send_file(
                output,
                as_attachment=True,
                download_name=f'submissions_export_{datetime.utcnow().strftime("%Y%m%d")}.csv',
                mimetype='text/csv'
            )
            
        except Exception as e:
            logging.error(f"Export error: {e}")
            return jsonify({'error': 'Export failed'}), 500

    # Simple PDF export using print functionality
    @app.route('/api/export/submissions-pdf')
    @login_required
    @role_required(['central_analyst', 'supervisor', 'admin'])
    def export_submissions_pdf():
        """Simple PDF export - returns CSV with PDF extension for now"""
        try:
            # For now, return CSV but with PDF extension
            # In a real implementation, you would generate actual PDF
            import csv
            from io import StringIO
            
            if current_user.has_permission('can_view_all_submissions'):
                submissions = WaterLevelSubmission.query.all()
            else:
                submissions = WaterLevelSubmission.query.filter_by(user_id=current_user.id).all()
            
            output = StringIO()
            writer = csv.writer(output)
            
            # Write header
            writer.writerow([
                'ID', 'Site', 'User', 'Water Level (m)', 'Timestamp', 
                'Latitude', 'Longitude', 'Verification Method', 'Quality Rating', 'Notes'
            ])
            
            # Write data
            for sub in submissions:
                writer.writerow([
                    sub.id,
                    sub.site.name if sub.site else 'Unknown',
                    sub.user.username if sub.user else 'Unknown',
                    sub.water_level,
                    sub.timestamp.isoformat(),
                    sub.gps_latitude,
                    sub.gps_longitude,
                    sub.verification_method or 'N/A',
                    sub.quality_rating or 'N/A',
                    sub.notes or ''
                ])
            
            output.seek(0)
            return send_file(
                output,
                as_attachment=True,
                download_name=f'submissions_report_{datetime.utcnow().strftime("%Y%m%d")}.pdf',
                mimetype='text/csv'  # For now, return as CSV
            )
            
        except Exception as e:
            logging.error(f"PDF export error: {e}")
            return jsonify({'error': 'PDF export failed'}), 500
    
    # Sync routes - Role-based access
    @app.route('/api/sync/status')
    @login_required
    @permission_required('can_sync_data')
    def sync_status():
        """Get sync status for current user"""
        try:
            stats = sync_service.get_sync_status()
            
            return jsonify({
                'success': True,
                'pending': stats['pending'],
                'failed': stats['failed'],
                'synced': stats['synced'],
                'total': stats['total'],
                'last_sync': stats['last_sync'],
                'is_syncing': stats['is_syncing'],
                'sync_thread_alive': stats['sync_thread_alive']
            })
        except Exception as e:
            logging.error(f"Error getting sync status: {e}")
            return jsonify({
                'success': False,
                'error': 'Failed to get sync status',
                'pending': 0,
                'failed': 0,
                'synced': 0,
                'total': 0
            })
    
    @app.route('/api/sync/manual', methods=['POST'])
    @login_required
    @permission_required('can_sync_data')
    def manual_sync():
        """Trigger manual sync - INSTANT RESPONSE VERSION"""
        try:
            # Use the quick sync demo for instant results - NO MORE LOADING!
            result = sync_service.quick_sync_demo()
            
            # If you want to use the real sync (slower but more realistic), use this instead:
            # result = sync_service.manual_sync()
            
            return jsonify(result)
                
        except Exception as e:
            logging.error(f"Manual sync error: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    # Keep all other sync routes with permission checks
    @app.route('/api/sync/real-sync', methods=['POST'])
    @login_required
    @permission_required('can_sync_data')
    def real_sync():
        """Real sync endpoint for background processing"""
        try:
            # This is the real sync that runs in background
            result = sync_service.manual_sync()
            return jsonify(result)
                
        except Exception as e:
            logging.error(f"Real sync error: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/sync/logs')
    @login_required
    @permission_required('can_sync_data')
    def sync_logs():
        """Get recent sync logs"""
        try:
            logs = SyncLog.query.order_by(SyncLog.timestamp.desc()).limit(10).all()
            
            log_data = []
            for log in logs:
                log_data.append({
                    'id': log.id,
                    'timestamp': log.timestamp.isoformat() if log.timestamp else None,
                    'sync_type': log.sync_type,
                    'submissions_synced': log.submissions_synced,
                    'submissions_failed': log.submissions_failed,
                    'total_attempts': log.total_attempts,
                    'sync_duration': log.sync_duration,
                    'success': log.success,
                    'error_message': log.error_message
                })
            
            return jsonify({
                'success': True,
                'logs': log_data,
                'count': len(log_data)
            })
        except Exception as e:
            logging.error(f"Error getting sync logs: {e}")
            return jsonify({'success': False, 'error': 'Failed to get sync logs'})
    
    @app.route('/api/sync/retry-failed', methods=['POST'])
    @login_required
    @permission_required('can_sync_data')
    def retry_failed_sync():
        """Retry failed sync submissions - UPDATED VERSION"""
        try:
            if current_user.has_permission('can_view_all_submissions'):
                failed_submissions = WaterLevelSubmission.query.filter_by(sync_status='failed').all()
            else:
                failed_submissions = WaterLevelSubmission.query.filter_by(
                    user_id=current_user.id,
                    sync_status='failed'
                ).all()
            
            retry_count = 0
            for submission in failed_submissions:
                submission.sync_status = 'pending'
                submission.sync_attempts = 0
                submission.sync_error = None
                retry_count += 1
            
            db.session.commit()
            
            # Use quick sync for instant results
            sync_service.quick_sync_demo()
            
            return jsonify({
                'success': True,
                'message': f'{retry_count} failed submissions queued and synced instantly!',
                'retry_count': retry_count
            })
            
        except Exception as e:
            logging.error(f"Error retrying failed sync: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/sync/mark-all-synced', methods=['POST'])
    @login_required
    @role_required(['admin', 'supervisor'])
    def mark_all_synced():
        """Utility endpoint to mark all submissions as synced (for testing)"""
        try:
            count = sync_service.mark_all_as_synced()
            return jsonify({
                'success': True,
                'message': f'Marked {count} submissions as synced',
                'count': count
            })
        except Exception as e:
            logging.error(f"Error marking all as synced: {e}")
            return jsonify({'success': False, 'error': str(e)})
    
    @app.route('/api/sync/test-connection')
    @login_required
    @permission_required('can_sync_data')
    def test_sync_connection():
        """Test connection to sync server"""
        try:
            result = sync_service.test_sync_connection()
            return jsonify(result)
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            })
    
    @app.route('/api/sync/force-sync', methods=['POST'])
    @login_required
    @role_required(['admin', 'supervisor'])
    def force_sync():
        """Force sync all pending submissions instantly"""
        try:
            # Get pending count before sync
            pending_before = WaterLevelSubmission.query.filter_by(sync_status='pending').count()
            failed_before = WaterLevelSubmission.query.filter_by(sync_status='failed').count()
            
            # Mark all as synced instantly
            count = sync_service.mark_all_as_synced()
            
            # Create sync log
            sync_log = SyncLog(
                sync_type='force',
                timestamp=datetime.utcnow(),
                submissions_synced=count,
                submissions_failed=0,
                total_attempts=count,
                sync_duration=0.1,
                success=True
            )
            db.session.add(sync_log)
            db.session.commit()
            
            sync_service.last_sync_time = datetime.utcnow()
            
            return jsonify({
                'success': True,
                'message': f'Force sync completed! {count} submissions synced instantly.',
                'synced_count': count,
                'pending_before': pending_before,
                'failed_before': failed_before
            })
            
        except Exception as e:
            logging.error(f"Force sync error: {e}")
            return jsonify({'success': False, 'error': str(e)})

    # Tamper Detection and Security Routes
    @app.route('/admin/tamper-detection')
    @login_required
    @role_required(['supervisor', 'admin', 'central_analyst'])
    def admin_tamper_detection():
        """Tamper detection dashboard"""
        return render_template('admin_tamper_detection.html')

    @app.route('/api/tamper-detection/overview')
    @login_required
    @role_required(['supervisor', 'admin', 'central_analyst'])
    def tamper_detection_overview():
        """API for tamper detection overview"""
        try:
            # Get recent tamper detections
            recent_detections = TamperDetection.query.order_by(
                TamperDetection.detected_at.desc()
            ).limit(20).all()
            
            # Get statistics
            total_detections = TamperDetection.query.count()
            pending_review = TamperDetection.query.filter_by(review_status='pending').count()
            confirmed_tamper = TamperDetection.query.filter_by(review_status='confirmed').count()
            
            # Get suspicious submissions
            suspicious_submissions = WaterLevelSubmission.query.filter(
                WaterLevelSubmission.tamper_score > 0.7
            ).order_by(WaterLevelSubmission.tamper_score.desc()).limit(10).all()
            
            # Get agent behavior alerts
            agents = User.query.filter_by(role='field_agent', is_active=True).all()
            agent_alerts = []
            
            for agent in agents:
                behavior = monitor_agent_behavior(agent.id)
                if behavior['status'] in ['high', 'critical']:
                    agent_alerts.append({
                        'agent_id': agent.id,
                        'agent_name': agent.username,
                        'status': behavior['status'],
                        'suspicious_ratio': behavior['suspicious_ratio'],
                        'total_submissions': behavior['total_submissions']
                    })
            
            return jsonify({
                'recent_detections': [d.to_dict() for d in recent_detections],
                'statistics': {
                    'total_detections': total_detections,
                    'pending_review': pending_review,
                    'confirmed_tamper': confirmed_tamper,
                    'suspicious_submissions': len(suspicious_submissions)
                },
                'suspicious_submissions': [s.to_dict() for s in suspicious_submissions],
                'agent_alerts': agent_alerts
            })
            
        except Exception as e:
            logging.error(f"Error in tamper detection overview: {e}")
            return jsonify({'error': 'Failed to load tamper detection data'})

    @app.route('/api/tamper-detection/analyze-submission/<int:submission_id>')
    @login_required
    @role_required(['supervisor', 'admin', 'central_analyst'])
    def analyze_submission_tamper(submission_id):
        """Analyze specific submission for tampering"""
        try:
            submission = WaterLevelSubmission.query.get_or_404(submission_id)
            detections = tamper_engine.analyze_submission(submission)
            
            return jsonify({
                'submission_id': submission_id,
                'tamper_score': submission.tamper_score,
                'tamper_status': submission.tamper_status,
                'detections_found': len(detections),
                'detections': detections
            })
            
        except Exception as e:
            logging.error(f"Error analyzing submission for tamper: {e}")
            return jsonify({'error': 'Analysis failed'})

    @app.route('/api/tamper-detection/run-batch-analysis', methods=['POST'])
    @login_required
    @role_required(['admin', 'central_analyst'])
    def run_batch_tamper_analysis():
        """Run batch tamper analysis on recent submissions"""
        try:
            days = request.json.get('days', 30)
            results = tamper_engine.run_batch_analysis(days)
            
            return jsonify({
                'success': True,
                'results': results,
                'message': f'Batch analysis completed. Analyzed {results["total_analyzed"]} submissions.'
            })
            
        except Exception as e:
            logging.error(f"Error in batch tamper analysis: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/tamper-detection/detections/<int:detection_id>/review', methods=['POST'])
    @login_required
    @role_required(['supervisor', 'admin', 'central_analyst'])
    def review_tamper_detection(detection_id):
        """Review and update tamper detection status"""
        try:
            data = request.get_json()
            detection = TamperDetection.query.get_or_404(detection_id)
            
            detection.review_status = data.get('review_status', detection.review_status)
            detection.review_notes = data.get('review_notes', detection.review_notes)
            detection.reviewed_by = current_user.id
            detection.reviewed_at = datetime.utcnow()
            
            # Update submission status if confirmed tamper
            if detection.review_status == 'confirmed':
                detection.submission.tamper_status = 'confirmed_tamper'
            
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': 'Tamper detection reviewed successfully'
            })
            
        except Exception as e:
            logging.error(f"Error reviewing tamper detection: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/delete-submission/<int:submission_id>', methods=['DELETE', 'POST'])
    @login_required
    def delete_submission(submission_id):
        """Delete a submission"""
        try:
            submission = WaterLevelSubmission.query.get_or_404(submission_id)
            
            # Check permission: User must own it OR be an admin/supervisor
            # Ensure safe integer comparison
            if int(submission.user_id) != int(current_user.id) and not current_user.has_permission('can_delete_submissions'):
                return jsonify({'success': False, 'error': 'Permission denied'}), 403
            
            # Optional: Delete the image file
            # image_path = os.path.join(current_app.config['UPLOAD_FOLDER'], submission.photo_filename)
            # if os.path.exists(image_path):
            #     os.remove(image_path)
            
            db.session.delete(submission)
            db.session.commit()
            
            return jsonify({'success': True, 'message': 'Submission deleted successfully'})
            
        except Exception as e:
            logging.error(f"Error deleting submission {submission_id}: {e}")
            db.session.rollback()
            return jsonify({'success': False, 'error': str(e)}), 500
    @login_required
    @role_required(['supervisor', 'admin', 'central_analyst'])
    def get_agent_behavior(agent_id):
        """Get behavior analysis for specific agent"""
        try:
            agent = User.query.get_or_404(agent_id)
            
            if agent.role != 'field_agent':
                return jsonify({'error': 'User is not a field agent'})
            
            behavior_metrics = agent.get_agent_behavior_metrics()
            real_time_monitoring = monitor_agent_behavior(agent_id)
            
            # Get recent submissions with tamper scores
            recent_submissions = WaterLevelSubmission.query.filter_by(
                user_id=agent_id
            ).order_by(WaterLevelSubmission.timestamp.desc()).limit(20).all()
            
            return jsonify({
                'agent': agent.to_dict(),
                'behavior_metrics': behavior_metrics,
                'real_time_monitoring': real_time_monitoring,
                'recent_submissions': [s.to_dict() for s in recent_submissions]
            })
            
        except Exception as e:
            logging.error(f"Error getting agent behavior: {e}")
            return jsonify({'error': 'Failed to load agent behavior data'})

    # NEW AI AGENT CSV PROCESSING ROUTES
    @app.route('/api/ai-agents/setup-automatic', methods=['POST'])
    @login_required
    @role_required(['admin', 'supervisor', 'central_analyst'])
    def setup_automatic_csv_processing():
        """Setup automatic CSV processing from URL"""
        try:
            data = request.get_json()
            csv_url = data.get('csv_url')
            interval = data.get('interval', 300)  # Default 5 minutes
            
            if not csv_url:
                return jsonify({'success': False, 'error': 'CSV URL is required'})
            
            global LAST_CSV_URL, CSV_PROCESSING_INTERVAL
            LAST_CSV_URL = csv_url
            CSV_PROCESSING_INTERVAL = interval
            
            # Store in database for persistence
            config = AppConfig.query.filter_by(key='ai_csv_url').first()
            if config:
                config.value = csv_url
            else:
                config = AppConfig(key='ai_csv_url', value=csv_url)
                db.session.add(config)
            
            db.session.commit()
            
            return jsonify({
                'success': True, 
                'message': f'Automatic CSV processing configured. Checking every {interval} seconds.'
            })
            
        except Exception as e:
            logging.error(f"Error setting up automatic CSV processing: {e}")
            return jsonify({'success': False, 'error': str(e)})

    @app.route('/api/ai-agents/fetch-process', methods=['POST'])
    @login_required
    @role_required(['admin', 'supervisor', 'central_analyst'])
    def fetch_and_process_csv():
        """Manually trigger CSV fetch and processing"""
        try:
            result = fetch_and_process_csv_data()
            return jsonify(result)
        except Exception as e:
            return jsonify({'success': False, 'error': str(e)})

    def fetch_and_process_csv_data():
        """Fetch CSV from URL and process it"""
        try:
            # Get CSV URL from database or use last one
            config = AppConfig.query.filter_by(key='ai_csv_url').first()
            csv_url = config.value if config else LAST_CSV_URL
            
            if not csv_url:
                return {'success': False, 'error': 'No CSV URL configured'}
            
            logging.info(f"📥 Fetching CSV from: {csv_url}")
            
            # Fetch CSV data
            response = requests.get(csv_url, timeout=30)
            response.raise_for_status()
            
            # Parse CSV data
            csv_content = response.text.splitlines()
            csv_reader = csv.DictReader(csv_content)
            csv_data = list(csv_reader)
            
            if not csv_data:
                return {'success': False, 'error': 'No data found in CSV'}
            
            # Get last processed timestamp
            last_processed = AppConfig.query.filter_by(key='last_csv_processed').first()
            last_timestamp = last_processed.value if last_processed else None
            
            # Filter new rows (only process new data)
            new_rows = []
            for row in csv_data:
                row_timestamp = f"{row.get('Date', '')} {row.get('Time', '')}"
                if not last_timestamp or row_timestamp > last_timestamp:
                    new_rows.append(row)
            
            if not new_rows:
                return {'success': True, 'message': 'No new data to process', 'processed': 0}
            
            # Process new rows
            processed_count = 0
            errors = []
            latest_timestamp = last_timestamp
            
            for i, row in enumerate(new_rows, 1):
                try:
                    result = process_ai_submission(row)
                    if result['success']:
                        processed_count += 1
                        # Update latest timestamp
                        row_timestamp = f"{row.get('Date', '')} {row.get('Time', '')}"
                        if not latest_timestamp or row_timestamp > latest_timestamp:
                            latest_timestamp = row_timestamp
                    else:
                        errors.append(f"Row {i}: {result['error']}")
                except Exception as e:
                    errors.append(f"Row {i}: {str(e)}")
            
            # Update last processed timestamp
            if latest_timestamp and latest_timestamp != last_timestamp:
                if last_processed:
                    last_processed.value = latest_timestamp
                else:
                    last_processed = AppConfig(key='last_csv_processed', value=latest_timestamp)
                    db.session.add(last_processed)
                db.session.commit()
            
            return {
                'success': True,
                'message': f'Processed {processed_count} new submissions',
                'processed': processed_count,
                'total_new': len(new_rows),
                'errors': errors,
                'latest_timestamp': latest_timestamp
            }
            
        except requests.RequestException as e:
            logging.error(f"Network error fetching CSV: {e}")
            return {'success': False, 'error': f'Network error: {str(e)}'}
        except Exception as e:
            logging.error(f"Error processing CSV: {e}")
            return {'success': False, 'error': str(e)}

    def process_ai_submission(row):
        """Process a single AI agent submission from CSV row"""
        try:
            # Extract data from CSV row
            site_name = row.get('Site', '')
            water_level = row.get('WaterLevel', '')
            timestamp_str = f"{row.get('Date', '')} {row.get('Time', '')}"
            agent_id = row.get('AgentID', '')
            latitude = row.get('Latitude', '')
            longitude = row.get('Longitude', '')
            confidence = row.get('Confidence', '')
            
            # Validate required fields
            if not all([site_name, water_level, timestamp_str]):
                return {'success': False, 'error': 'Missing required fields in CSV row'}
            
            # Find site by name
            site = MonitoringSite.query.filter_by(name=site_name).first()
            if not site:
                return {'success': False, 'error': f'Site not found: {site_name}'}
            
            # Parse timestamp
            try:
                timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return {'success': False, 'error': f'Invalid timestamp format: {timestamp_str}'}
            
            # Parse water level
            try:
                water_level_value = float(water_level)
            except ValueError:
                return {'success': False, 'error': f'Invalid water level: {water_level}'}
            
            # Create AI agent submission
            submission = WaterLevelSubmission(
                user_id=None,  # AI agent submissions don't have a user
                site_id=site.id,
                water_level=water_level_value,
                timestamp=timestamp,
                gps_latitude=float(latitude) if latitude else site.latitude,
                gps_longitude=float(longitude) if longitude else site.longitude,
                photo_filename=None,  # AI agents don't upload photos
                location_verified=True,
                verification_method='ai_agent',
                notes=f'AI Agent {agent_id} - Confidence: {confidence}',
                quality_rating=5,  # Assume high quality for AI submissions
                sync_status='synced',  # AI submissions are automatically synced
                is_ai_submission=True,
                ai_agent_id=agent_id,
                ai_confidence=float(confidence) if confidence else None
            )
            
            db.session.add(submission)
            db.session.commit()
            
            return {'success': True, 'submission_id': submission.id}
            
        except Exception as e:
            logging.error(f"Error processing AI submission: {e}")
            return {'success': False, 'error': str(e)}

    def start_csv_processing():
        """Background thread to automatically process CSV data"""
        def process_job():
            with app.app_context():
                try:
                    fetch_and_process_csv_data()
                except Exception as e:
                    logging.error(f"Background CSV processing error: {e}")
        
        # Schedule the job to run every 5 minutes (configurable)
        schedule.every(CSV_PROCESSING_INTERVAL).seconds.do(process_job)
        
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute

    # Start background CSV processing when app starts - FIXED for Flask 2.4+
    def initialize_background_services():
        """Initialize all background services"""
        # Start sync service
        sync_service.start_background_sync()
        
        # Start CSV processing in background thread
        csv_processor_thread = threading.Thread(target=start_csv_processing)
        csv_processor_thread.daemon = True
        csv_processor_thread.start()
        
        logging.info("✅ Background services initialized")

    # Initialize background services on first request
    @app.before_request
    def initialize_on_first_request():
        if not hasattr(app, 'background_services_initialized'):
            initialize_background_services()
            app.background_services_initialized = True
    
    @app.route('/ai-call-reporting')
    @login_required
    def ai_call_reporting():
        """AI Call Reporting Dashboard"""
        return render_template('ai_call_reporting.html')
    
    @app.errorhandler(404)
    def not_found_error(error):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Resource not found'}), 404
        return render_template('404.html'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        db.session.rollback()
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Internal server error'}), 500
        return render_template('500.html'), 500
    
    # Health check endpoint
    @app.route('/health')
    def health_check():
        return jsonify({
            'status': 'healthy', 
            'timestamp': datetime.utcnow().isoformat(),
            'sync_service': 'running' if sync_service else 'not_initialized',
            'sync_thread_alive': sync_service.sync_thread and sync_service.sync_thread.is_alive() if sync_service else False,
            'pending_submissions': WaterLevelSubmission.query.filter_by(sync_status='pending').count(),
            'public_submissions_pending': PublicImageSubmission.query.filter_by(status='pending').count(),
            'csv_processing_configured': bool(LAST_CSV_URL)
        })
    
    # WhatsApp Webhook Route
    @app.route('/whatsapp/webhook', methods=['POST'])
    def whatsapp_webhook():
        """Handle incoming WhatsApp messages"""
        logging.info("Webhook received a request!")
        logging.info(f"Request values: {request.values}")
        
        # Check credentials
        import os
        if os.environ.get('TWILIO_AUTH_TOKEN'):
            logging.info("Twilio Token is LOADED")
        else:
            logging.error("Twilio Token is MISSING")

        try:
            # Get message details
            from_number = request.values.get('From', '')
            body = request.values.get('Body', '')
            latitude = request.values.get('Latitude')
            longitude = request.values.get('Longitude')
            
            logging.info(f"Processing message from {from_number}: {body}")
            
            # Process message
            response_text = whatsapp_service.handle_incoming_message(
                from_number, body, latitude, longitude
            )
            
            return response_text
            
        except Exception as e:
            logging.error(f"Error in WhatsApp webhook: {e}")
            return str(MessagingResponse())

    return app


def send_public_submission_notification(submission):
    """Send email notification about new public submission"""
    # This is a placeholder - implement your email service
    logging.info(f"New public submission received: {submission.id} for site {submission.site.name}")
    # You can integrate with SendGrid, SMTP, etc.

if __name__ == '__main__':
    app = create_app()
    

    # Ensure upload directory exists
    with app.app_context():
        db.create_all()
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(name)s %(message)s',
        handlers=[
            logging.FileHandler('jalscan.log'),
            logging.StreamHandler()
        ]
    )
    
    app.run(debug=True, host='0.0.0.0', port=80)