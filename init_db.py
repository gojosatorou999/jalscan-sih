from app import create_app
from models import db, User, MonitoringSite, UserSite, WaterLevelSubmission, PublicImageSubmission, SyncLog
from werkzeug.security import generate_password_hash
from datetime import datetime

def init_database():
    app = create_app()
    
    with app.app_context():
        try:
            print("Dropping all tables...")
            db.drop_all()
            
            print("Creating all tables with new schema...")
            db.create_all()
            
            print("Creating sample users with all roles...")
            
            # Define rivers and their codes
            rivers_data = [
                {
                    'name': 'Ganga River - Haridwar',
                    'code': 'GANGA_HARIDWAR_001',
                    'latitude': 29.9457,
                    'longitude': 78.1642,
                    'basin': 'Ganga'
                },
                {
                    'name': 'Musi River - Hyderabad',
                    'code': 'MUSI_HYDERABAD_001', 
                    'latitude': 17.477836,
                    'longitude': 78.356650,
                    'basin': 'Krishna'
                },
                {
                    'name': 'Yamuna River - Delhi',
                    'code': 'YAMUNA_DELHI_001',
                    'latitude': 28.5931,
                    'longitude': 77.2507,
                    'basin': 'Yamuna'
                },
                {
                    'name': 'Godavari River - Nashik',
                    'code': 'GODAVARI_NASHIK_001',
                    'latitude': 19.9975,
                    'longitude': 73.7898,
                    'basin': 'Godavari'
                },
                {
                    'name': 'Krishna River - Vijayawada',
                    'code': 'KRISHNA_VIJAYAWADA_001',
                    'latitude': 16.5062,
                    'longitude': 80.6480,
                    'basin': 'Krishna'
                },
                {
                    'name': 'Kaveri River',
                    'code': 'KAVERI_001',
                    'latitude': 12.2600,
                    'longitude': 76.5000,
                    'basin': 'Kaveri'
                },
                {
                    'name': 'Brahmaputra River',
                    'code': 'BRAHMAPUTRA_001',
                    'latitude': 26.1900,
                    'longitude': 91.7500,
                    'basin': 'Brahmaputra'
                },
                {
                    'name': 'Narmada River',
                    'code': 'NARMADA_001',
                    'latitude': 22.2500,
                    'longitude': 78.7500,
                    'basin': 'Narmada'
                },
                {
                    'name': 'Tripti River',
                    'code': 'TRIPTI_001',
                    'latitude': 23.5000,
                    'longitude': 87.5000,
                    'basin': 'Tripti'
                }
            ]
            
            # Create admin user first
            admin_user = User(
                username='admin',
                password_hash=generate_password_hash('admin123'),
                role='admin',
                full_name='Administrator User',
                email='admin@jalscan.com',
                phone='+91-9876543213',
                is_active=True
            )
            db.session.add(admin_user)
            db.session.flush()  # Get the admin ID
            
            # Create rivers/sites
            for river in rivers_data:
                site = MonitoringSite(
                    name=river['name'],
                    latitude=river['latitude'],
                    longitude=river['longitude'],
                    qr_code=river['code'],
                    description=f'Primary monitoring site on {river["name"]}',
                    river_basin=river['basin'],
                    district='Multiple',
                    state='Various',
                    is_active=True,
                    created_by=admin_user.id
                )
                db.session.add(site)
                print(f"✓ River site '{river['name']}' created with code: {river['code']}")
            
            db.session.commit()
            
            # Create supervisor and analyst users
            supervisor_users = [
                {
                    'username': 'supervisor_ganga',
                    'password': 'supervisor123',
                    'full_name': 'Ganga River Supervisor',
                    'email': 'supervisor.ganga@jalscan.com',
                    'assigned_river': 'GANGA_HARIDWAR_001'
                },
                {
                    'username': 'supervisor_south',
                    'password': 'supervisor123', 
                    'full_name': 'Southern Rivers Supervisor',
                    'email': 'supervisor.south@jalscan.com',
                    'assigned_river': 'Multiple'
                }
            ]
            
            analyst_users = [
                {
                    'username': 'analyst_central',
                    'password': 'analyst123',
                    'full_name': 'Central Analyst',
                    'email': 'analyst@jalscan.com'
                }
            ]
            
            # Create supervisors
            for sup_data in supervisor_users:
                supervisor = User(
                    username=sup_data['username'],
                    password_hash=generate_password_hash(sup_data['password']),
                    role='supervisor',
                    full_name=sup_data['full_name'],
                    email=sup_data['email'],
                    phone='+91-9876543211',
                    is_active=True,
                    assigned_river=sup_data.get('assigned_river')
                )
                db.session.add(supervisor)
                print(f"✓ Supervisor '{sup_data['username']}' created")
            
            # Create analysts
            for ana_data in analyst_users:
                analyst = User(
                    username=ana_data['username'],
                    password_hash=generate_password_hash(ana_data['password']),
                    role='central_analyst',
                    full_name=ana_data['full_name'],
                    email=ana_data['email'],
                    phone='+91-9876543212',
                    is_active=True
                )
                db.session.add(analyst)
                print(f"✓ Analyst '{ana_data['username']}' created")
            
            db.session.commit()
            
            print("\n" + "="*60)
            print("DATABASE INITIALIZATION COMPLETE!")
            print("="*60)
            print("Available Rivers (9):")
            for river in rivers_data:
                print(f"  - {river['name']} ({river['code']})")
            
            print("\nLogin Credentials:")
            print("  Admin:")
            print("    Username: admin")
            print("    Password: admin123")
            print("  Supervisors:")
            for sup in supervisor_users:
                print(f"    Username: {sup['username']}")
                print(f"    Password: {sup['password']}")
            print("  Analyst:")
            print("    Username: analyst_central")
            print("    Password: analyst123")
            
            print("\nRiver Assignment System:")
            print("  - Each river can have up to 9 field agents (ID 001-009)")
            print("  - Supervisors can assign agents to specific rivers")
            print("  - Admin can create new supervisors and analysts")
            
        except Exception as e:
            print(f"Error during database initialization: {e}")
            db.session.rollback()
            raise

def add_test_submissions():
    """Add some test submissions for demonstration"""
    app = create_app()
    
    with app.app_context():
        try:
            from datetime import datetime, timedelta
            
            # Get field agent or create one if needed
            field_agent = User.query.filter_by(username='field_agent').first()
            if not field_agent:
                field_agent = User(
                    username='field_agent',
                    password_hash=generate_password_hash('password123'),
                    role='field_agent',
                    full_name='Field Agent User',
                    email='field@jalscan.com',
                    phone='+91-9876543210',
                    is_active=True
                )
                db.session.add(field_agent)
                db.session.commit()
            
            site = MonitoringSite.query.filter_by(qr_code='MUSI_HYDERABAD_001').first()
            
            if field_agent and site:
                # Clear existing submissions
                WaterLevelSubmission.query.delete()
                
                # Create test submissions from past days
                test_data = [
                    {'days_ago': 1, 'water_level': 2.45, 'method': 'gps', 'qr_code': None, 'quality': 4},
                    {'days_ago': 2, 'water_level': 2.38, 'method': 'gps', 'qr_code': None, 'quality': 3},
                    {'days_ago': 3, 'water_level': 2.52, 'method': 'qr', 'qr_code': 'MUSI_HYDERABAD_001', 'quality': 5},
                    {'days_ago': 4, 'water_level': 2.41, 'method': 'gps', 'qr_code': None, 'quality': 4},
                    {'days_ago': 5, 'water_level': 2.35, 'method': 'qr', 'qr_code': 'MUSI_HYDERABAD_001', 'quality': 3},
                ]
                
                for data in test_data:
                    submission = WaterLevelSubmission(
                        user_id=field_agent.id,
                        site_id=site.id,
                        water_level=data['water_level'],
                        timestamp=datetime.utcnow() - timedelta(days=data['days_ago']),
                        gps_latitude=17.477836,
                        gps_longitude=78.356650,
                        photo_filename=f"sample_{data['days_ago']}.jpg",
                        location_verified=True,
                        verification_method=data['method'],
                        qr_code_scanned=data['qr_code'],
                        quality_rating=data['quality'],
                        notes=f"Test submission from {data['days_ago']} days ago",
                        sync_status='synced',
                        sync_attempts=1,
                        last_sync_attempt=datetime.utcnow() - timedelta(days=data['days_ago'], hours=1),
                        sync_error=None
                    )
                    db.session.add(submission)
                    print(f"✓ Created test submission for {data['days_ago']} days ago - Quality: {data['quality']}")
                
                db.session.commit()
                print("✓ Test submissions added with quality ratings")
        except Exception as e:
            print(f"Error adding test submissions: {e}")
            db.session.rollback()

if __name__ == '__main__':
    try:
        init_database()
        
        # Ask if user wants test data
        add_test = input("\nDo you want to add test submissions? (y/n): ").lower().strip()
        if add_test in ['y', 'yes']:
            add_test_submissions()
            print("✓ Test submissions added successfully!")
        
    except Exception as e:
        print(f"Failed to initialize database: {e}")