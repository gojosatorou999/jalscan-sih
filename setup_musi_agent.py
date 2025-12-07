from app import create_app
from models import db, User, MonitoringSite, UserSite
from werkzeug.security import generate_password_hash

def setup_musi_agent():
    app = create_app()
    with app.app_context():
        print("--- Setting up Musi River Field Agent ---")
        
        # 1. Get or Create User
        user = User.query.filter_by(username='field_agent').first()
        if not user:
            print("Creating new field_agent user...")
            user = User(username='field_agent')
        else:
            print("Updating existing field_agent user...")
            
        user.password_hash = generate_password_hash('password123')
        user.role = 'field_agent'
        user.full_name = 'Musi Field Agent'
        user.email = 'field.musi@jalscan.com'
        user.phone = '+91-9876543210'
        user.is_active = True
        user.assigned_river = 'MUSI_HYDERABAD_001'
        user.agent_id = '001'
        
        db.session.add(user)
        db.session.commit()
        print(f"User '{user.username}' saved.")
        
        # 2. Get Musi River Site
        site = MonitoringSite.query.filter(MonitoringSite.name.like('%Musi%')).first()
        if not site:
            print("Error: Musi River site not found!")
            return
            
        print(f"Found Site: {site.name} (ID: {site.id})")
        
        # 3. Assign User to Site (Explicit Assignment)
        # Check if already assigned
        assignment = UserSite.query.filter_by(user_id=user.id, site_id=site.id).first()
        if not assignment:
            print("Assigning user to site...")
            assignment = UserSite(
                user_id=user.id,
                site_id=site.id,
                assigned_by=1  # Assuming admin is ID 1
            )
            db.session.add(assignment)
            db.session.commit()
            print("Assignment created.")
        else:
            print("User already assigned to this site.")
            
        print("\n✅ Setup Complete!")
        print(f"Username: {user.username}")
        print("Password: password123")
        print(f"Assigned River: {user.assigned_river}")

if __name__ == "__main__":
    setup_musi_agent()
