from app import create_app
from models import db
from sqlalchemy import text
import os

def migrate_database():
    app = create_app()
    
    with app.app_context():
        print("Starting database migration...")
        
        try:
            # Check if PublicImageSubmission table exists
            result = db.session.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='public_image_submissions'"))
            public_table_exists = result.fetchone() is not None
            
            # Check if the columns already exist in water_level_submissions
            result = db.session.execute(text("PRAGMA table_info(water_level_submissions)"))
            columns = [row[1] for row in result]
            
            qr_columns_exist = 'qr_code_scanned' in columns and 'verification_method' in columns
            
            # Check if new ID verification columns exist in public_image_submissions
            if public_table_exists:
                result = db.session.execute(text("PRAGMA table_info(public_image_submissions)"))
                public_columns = [row[1] for row in result]
                id_columns_exist = all(col in public_columns for col in [
                    'id_type', 'id_front_filename', 'id_back_filename', 'live_photo_filename',
                    'verification_status', 'verification_notes', 'submitted_ip', 'user_agent'
                ])
            else:
                id_columns_exist = False

            # Check if app_config table exists
            result = db.session.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='app_config'"))
            app_config_exists = result.fetchone() is not None

            if public_table_exists and qr_columns_exist and id_columns_exist and app_config_exists:
                print("Database is already up to date!")
                return
            
            print("Starting database migration for new features...")
            
            # Add the missing columns to water_level_submissions table if they don't exist
            if 'verification_method' not in columns:
                print("Adding verification_method column...")
                db.session.execute(text('''
                    ALTER TABLE water_level_submissions 
                    ADD COLUMN verification_method VARCHAR(20)
                '''))
            
            if 'qr_code_scanned' not in columns:
                print("Adding qr_code_scanned column...")
                db.session.execute(text('''
                    ALTER TABLE water_level_submissions 
                    ADD COLUMN qr_code_scanned VARCHAR(100)
                '''))
            
            # Create SyncLog table if it doesn't exist
            db.session.execute(text('''
                CREATE TABLE IF NOT EXISTS sync_logs (
                    id INTEGER PRIMARY KEY,
                    timestamp DATETIME,
                    sync_type VARCHAR(20),
                    submissions_synced INTEGER,
                    submissions_failed INTEGER,
                    total_attempts INTEGER,
                    sync_duration FLOAT,
                    error_message TEXT,
                    success BOOLEAN
                )
            '''))
            
            # Create PublicImageSubmission table if it doesn't exist
            if not public_table_exists:
                print("Creating public_image_submissions table with ID verification columns...")
                db.session.execute(text('''
                    CREATE TABLE public_image_submissions (
                        id INTEGER PRIMARY KEY,
                        site_id INTEGER,
                        photo_filename VARCHAR(255) NOT NULL,
                        timestamp DATETIME,
                        gps_latitude FLOAT,
                        gps_longitude FLOAT,
                        contact_email VARCHAR(120),
                        description TEXT,
                        status VARCHAR(20) DEFAULT 'pending',
                        reviewed_by INTEGER,
                        reviewed_at DATETIME,
                        review_notes TEXT,
                        id_type VARCHAR(50),
                        id_front_filename VARCHAR(255),
                        id_back_filename VARCHAR(255),
                        live_photo_filename VARCHAR(255),
                        verification_status VARCHAR(20) DEFAULT 'pending',
                        verification_notes TEXT,
                        submitted_ip VARCHAR(45),
                        user_agent TEXT,
                        FOREIGN KEY (site_id) REFERENCES monitoring_sites (id) ON DELETE CASCADE,
                        FOREIGN KEY (reviewed_by) REFERENCES users (id)
                    )
                '''))
            else:
                # Add new ID verification columns to existing table
                print("Adding ID verification columns to existing public_image_submissions table...")
                
                new_columns = [
                    ('id_type', 'VARCHAR(50)'),
                    ('id_front_filename', 'VARCHAR(255)'),
                    ('id_back_filename', 'VARCHAR(255)'),
                    ('live_photo_filename', 'VARCHAR(255)'),
                    ('verification_status', 'VARCHAR(20) DEFAULT "pending"'),
                    ('verification_notes', 'TEXT'),
                    ('submitted_ip', 'VARCHAR(45)'),
                    ('user_agent', 'TEXT')
                ]
                
                for column_name, column_type in new_columns:
                    if column_name not in public_columns:
                        print(f"Adding column: {column_name}")
                        db.session.execute(text(f'''
                            ALTER TABLE public_image_submissions 
                            ADD COLUMN {column_name} {column_type}
                        '''))
            
            # Create AppConfig table if it doesn't exist
            if not app_config_exists:
                add_app_config_table()
            
            db.session.commit()
            print("Database migration completed successfully!")
            
        except Exception as e:
            db.session.rollback()
            print(f"Migration failed: {e}")
            print("Trying alternative migration approach...")
            try_alternative_migration()

def try_alternative_migration():
    """Alternative migration using backup and restore"""
    app = create_app()
    
    with app.app_context():
        try:
            print("Creating database backup and recreating with new schema...")
            
            # Import all models
            from models import User, MonitoringSite, UserSite, WaterLevelSubmission, SyncLog, PublicImageSubmission
            
            # Backup data
            users = User.query.all()
            sites = MonitoringSite.query.all()
            user_sites = UserSite.query.all()
            submissions = WaterLevelSubmission.query.all()
            public_submissions = PublicImageSubmission.query.all()
            sync_logs = SyncLog.query.all()
            
            print(f"Backing up: {len(users)} users, {len(sites)} sites, {len(submissions)} submissions, {len(public_submissions)} public submissions")
            
            # Create new database with updated schema
            print("Recreating database with new schema including ID verification...")
            db.drop_all()
            db.create_all()
            
            # Restore users
            user_mapping = {}
            for user in users:
                new_user = User(
                    username=user.username,
                    password_hash=user.password_hash,
                    role=user.role,
                    full_name=user.full_name,
                    email=user.email,
                    phone=user.phone,
                    is_active=user.is_active,
                    created_at=user.created_at,
                    last_login=user.last_login
                )
                db.session.add(new_user)
                db.session.flush()  # Get the new ID
                user_mapping[user.id] = new_user.id
            
            db.session.commit()
            
            # Restore sites
            site_mapping = {}
            for site in sites:
                new_site = MonitoringSite(
                    name=site.name,
                    latitude=site.latitude,
                    longitude=site.longitude,
                    qr_code=site.qr_code,
                    description=site.description,
                    river_basin=site.river_basin,
                    district=site.district,
                    state=site.state,
                    is_active=site.is_active,
                    created_by=user_mapping.get(site.created_by),
                    created_at=site.created_at
                )
                db.session.add(new_site)
                db.session.flush()  # Get the new ID
                site_mapping[site.id] = new_site.id
            
            db.session.commit()
            
            # Restore user sites
            for user_site in user_sites:
                new_user_site = UserSite(
                    user_id=user_mapping.get(user_site.user_id),
                    site_id=site_mapping[user_site.site_id],
                    assigned_at=user_site.assigned_at,
                    assigned_by=user_mapping.get(user_site.assigned_by)
                )
                db.session.add(new_user_site)
            
            # Restore submissions with new fields
            for submission in submissions:
                new_submission = WaterLevelSubmission(
                    user_id=user_mapping.get(submission.user_id),
                    site_id=site_mapping[submission.site_id],
                    water_level=submission.water_level,
                    timestamp=submission.timestamp,
                    gps_latitude=submission.gps_latitude,
                    gps_longitude=submission.gps_longitude,
                    photo_filename=submission.photo_filename,
                    location_verified=submission.location_verified,
                    verification_method=getattr(submission, 'verification_method', 'gps'),
                    qr_code_scanned=getattr(submission, 'qr_code_scanned', None),
                    sync_status=submission.sync_status,
                    sync_attempts=submission.sync_attempts,
                    last_sync_attempt=submission.last_sync_attempt,
                    sync_error=submission.sync_error,
                    notes=submission.notes,
                    quality_rating=submission.quality_rating,
                    reviewed_by=user_mapping.get(submission.reviewed_by) if submission.reviewed_by else None,
                    reviewed_at=submission.reviewed_at,
                    review_notes=submission.review_notes,
                    created_at=submission.created_at,
                    tamper_score=getattr(submission, 'tamper_score', 0.0),
                    tamper_status=getattr(submission, 'tamper_status', 'clean'),
                    last_tamper_check=getattr(submission, 'last_tamper_check', None),
                    tamper_check_version=getattr(submission, 'tamper_check_version', '1.0')
                )
                db.session.add(new_submission)
            
            # Restore public submissions with new ID verification fields
            for public_sub in public_submissions:
                new_public_sub = PublicImageSubmission(
                    site_id=site_mapping[public_sub.site_id],
                    photo_filename=public_sub.photo_filename,
                    timestamp=public_sub.timestamp,
                    gps_latitude=public_sub.gps_latitude,
                    gps_longitude=public_sub.gps_longitude,
                    contact_email=public_sub.contact_email,
                    description=public_sub.description,
                    status=public_sub.status,
                    reviewed_by=user_mapping.get(public_sub.reviewed_by) if public_sub.reviewed_by else None,
                    reviewed_at=public_sub.reviewed_at,
                    review_notes=public_sub.review_notes,
                    # New ID verification fields with default values
                    id_type=getattr(public_sub, 'id_type', None),
                    id_front_filename=getattr(public_sub, 'id_front_filename', None),
                    id_back_filename=getattr(public_sub, 'id_back_filename', None),
                    live_photo_filename=getattr(public_sub, 'live_photo_filename', None),
                    verification_status=getattr(public_sub, 'verification_status', 'pending'),
                    verification_notes=getattr(public_sub, 'verification_notes', None),
                    submitted_ip=getattr(public_sub, 'submitted_ip', None),
                    user_agent=getattr(public_sub, 'user_agent', None)
                )
                db.session.add(new_public_sub)
            
            # Restore sync logs
            for sync_log in sync_logs:
                new_sync_log = SyncLog(
                    timestamp=sync_log.timestamp,
                    sync_type=sync_log.sync_type,
                    submissions_synced=sync_log.submissions_synced,
                    submissions_failed=sync_log.submissions_failed,
                    total_attempts=sync_log.total_attempts,
                    sync_duration=sync_log.sync_duration,
                    error_message=sync_log.error_message,
                    success=sync_log.success
                )
                db.session.add(new_sync_log)
            
            # Create AppConfig table
            add_app_config_table()
            
            db.session.commit()
            print("Database migration completed successfully with backup/restore!")
            
        except Exception as e:
            db.session.rollback()
            print(f"Alternative migration also failed: {e}")
            print("Please use the reinitialization method instead.")

def add_app_config_table():
    """Create AppConfig table for storing application configuration"""
    app = create_app()
    
    with app.app_context():
        try:
            # Create AppConfig table
            db.session.execute(text('''
                CREATE TABLE IF NOT EXISTS app_config (
                    id INTEGER PRIMARY KEY,
                    key VARCHAR(100) UNIQUE NOT NULL,
                    value TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            '''))
            
            # Insert default configuration values
            default_configs = [
                ('id_verification_required', 'true'),
                ('public_submissions_enabled', 'true'),
                ('max_file_size_mb', '10'),
                ('allowed_file_types', 'jpg,jpeg,png,pdf'),
                ('auto_verification_threshold', '0.8'),
                ('maintenance_mode', 'false')
            ]
            
            for key, value in default_configs:
                db.session.execute(
                    text('INSERT OR IGNORE INTO app_config (key, value) VALUES (:key, :value)'),
                    {'key': key, 'value': value}
                )
            
            db.session.commit()
            print("✓ AppConfig table created and populated with default values")
            
        except Exception as e:
            db.session.rollback()
            print(f"Error creating AppConfig table: {e}")

def add_sample_public_submissions():
    """Add sample public submissions for testing with ID verification"""
    app = create_app()
    
    with app.app_context():
        try:
            from models import PublicImageSubmission, MonitoringSite
            from datetime import datetime, timedelta
            
            # Get active sites
            sites = MonitoringSite.query.filter_by(is_active=True).all()
            
            if not sites:
                print("No active sites found. Please run init_db.py first.")
                return
            
            # Clear existing public submissions
            PublicImageSubmission.query.delete()
            
            # Create sample public submissions with ID verification data
            sample_data = [
                {
                    'days_ago': 1,
                    'site': sites[0],
                    'description': 'Water level looks normal today',
                    'contact_email': 'citizen1@example.com',
                    'has_gps': True,
                    'id_type': 'aadhaar',
                    'has_id_verification': True
                },
                {
                    'days_ago': 2,
                    'site': sites[1],
                    'description': 'Heavy rainfall yesterday, water level seems higher',
                    'contact_email': 'local.observer@example.com',
                    'has_gps': False,
                    'id_type': 'voter_id',
                    'has_id_verification': True
                },
                {
                    'days_ago': 3,
                    'site': sites[2],
                    'description': 'Regular monitoring photo',
                    'contact_email': None,
                    'has_gps': True,
                    'id_type': 'driving_license',
                    'has_id_verification': True
                },
                {
                    'days_ago': 4,
                    'site': sites[0],
                    'description': 'Dry season, water level is low',
                    'contact_email': 'river.watcher@example.com',
                    'has_gps': True,
                    'id_type': 'pan_card',
                    'has_id_verification': True
                },
                {
                    'days_ago': 5,
                    'site': sites[3],
                    'description': 'Weekly checkup photo',
                    'contact_email': 'community.helper@example.com',
                    'has_gps': False,
                    'id_type': 'passport',
                    'has_id_verification': True
                },
                {
                    'days_ago': 6,
                    'site': sites[1],
                    'description': 'Testing without ID verification',
                    'contact_email': 'test@example.com',
                    'has_gps': True,
                    'id_type': None,
                    'has_id_verification': False
                }
            ]
            
            for i, data in enumerate(sample_data):
                submission = PublicImageSubmission(
                    site_id=data['site'].id,
                    photo_filename=f"public_water_{data['site'].id}_{i+1}.jpg",
                    timestamp=datetime.utcnow() - timedelta(days=data['days_ago']),
                    gps_latitude=data['site'].latitude + 0.0001 if data['has_gps'] else None,
                    gps_longitude=data['site'].longitude + 0.0001 if data['has_gps'] else None,
                    contact_email=data['contact_email'],
                    description=data['description'],
                    status='pending',
                    # ID verification fields
                    id_type=data['id_type'],
                    id_front_filename=f"public_id_front_{data['site'].id}_{i+1}.jpg" if data['has_id_verification'] else None,
                    id_back_filename=f"public_id_back_{data['site'].id}_{i+1}.jpg" if data['has_id_verification'] and i % 2 == 0 else None,  # Only some have back side
                    live_photo_filename=f"public_live_{data['site'].id}_{i+1}.jpg" if data['has_id_verification'] else None,
                    verification_status='verified' if data['has_id_verification'] and i < 3 else 'pending',  # First 3 are verified
                    verification_notes='Automatically verified for testing' if data['has_id_verification'] and i < 3 else None,
                    submitted_ip='192.168.1.100',
                    user_agent='Mozilla/5.0 (Test Browser)'
                )
                db.session.add(submission)
                status_info = "with ID verification" if data['has_id_verification'] else "without ID verification"
                print(f"✓ Created sample public submission for {data['site'].name} {status_info}")
            
            db.session.commit()
            print("✓ Sample public submissions with ID verification added successfully!")
            
        except Exception as e:
            db.session.rollback()
            print(f"Error adding sample public submissions: {e}")

def verify_migration():
    """Verify that the migration was successful"""
    app = create_app()
    
    with app.app_context():
        try:
            print("\nVerifying migration...")
            
            # Check public_image_submissions table structure
            result = db.session.execute(text("PRAGMA table_info(public_image_submissions)"))
            columns = [row[1] for row in result]
            
            required_columns = [
                'id_type', 'id_front_filename', 'id_back_filename', 'live_photo_filename',
                'verification_status', 'verification_notes', 'submitted_ip', 'user_agent'
            ]
            
            missing_columns = [col for col in required_columns if col not in columns]
            
            if missing_columns:
                print(f"❌ Missing columns: {missing_columns}")
                return False
            else:
                print("✅ All ID verification columns are present")
            
            # Check if we can query the table
            from models import PublicImageSubmission
            count = PublicImageSubmission.query.count()
            print(f"✅ Public submissions table is accessible ({count} records)")
            
            # Check AppConfig table
            result = db.session.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='app_config'"))
            app_config_exists = result.fetchone() is not None
            
            if app_config_exists:
                print("✅ AppConfig table exists")
                
                # Check if default config values are present
                result = db.session.execute(text("SELECT COUNT(*) FROM app_config"))
                config_count = result.fetchone()[0]
                print(f"✅ AppConfig table has {config_count} configuration entries")
            else:
                print("❌ AppConfig table is missing")
                return False
            
            # Test creating a new submission with ID verification
            test_site = db.session.execute(text("SELECT id FROM monitoring_sites LIMIT 1")).fetchone()
            if test_site:
                test_submission = PublicImageSubmission(
                    site_id=test_site[0],
                    photo_filename="test_water.jpg",
                    id_type="aadhaar",
                    id_front_filename="test_id_front.jpg",
                    live_photo_filename="test_live.jpg",
                    verification_status="pending"
                )
                # Just test the object creation, don't save it
                print("✅ Can create PublicImageSubmission objects with ID verification")
            
            print("✅ Migration verification completed successfully!")
            return True
            
        except Exception as e:
            print(f"❌ Migration verification failed: {e}")
            return False

if __name__ == '__main__':
    migrate_database()
    
    # Verify migration
    if verify_migration():
        # Ask if user wants to add sample public submissions
        add_samples = input("\nDo you want to add sample public submissions with ID verification? (y/n): ").lower().strip()
        if add_samples in ['y', 'yes']:
            add_sample_public_submissions()
            print("✓ Sample public submissions with ID verification added!")
    else:
        print("\n❌ Migration failed. Please check the error messages above.")
    
    print("\nMigration process completed!")