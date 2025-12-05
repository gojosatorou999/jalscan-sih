# JalScan - Flood Monitoring & Alert System 🌊

JalScan is a comprehensive flood monitoring application designed to track water levels in rivers and send timely alerts to nearby residents. It combines manual field reporting, automated tamper detection, and instant WhatsApp notifications to ensure public safety.

## 🚀 Key Features

*   **Real-time Monitoring**: Track water levels across multiple monitoring sites (e.g., Musi River, Ganga).
*   **WhatsApp Alerts**:
    *   **Automated**: Triggers alerts when water levels exceed defined thresholds.
    *   **Manual**: Admins can trigger urgent alerts manually from the dashboard.
    *   **Geo-targeted**: Alerts are sent ONLY to subscribers within a **10km radius** of the affected site.
*   **Field Reporting**: Field agents can submit water level readings with photo evidence.
*   **Tamper Detection**: AI-powered analysis to detect duplicate or manipulated report submissions.
*   **Admin Dashboard**: Manage sites, users, and view live flood status.
*   **Subscriber Management**: View and manage WhatsApp subscribers and their locations.

## 🛠️ Tech Stack

*   **Backend**: Python (Flask)
*   **Database**: SQLite (SQLAlchemy)
*   **Notifications**: Twilio API (WhatsApp)
*   **Frontend**: HTML/CSS/JavaScript (Jinja2 templates)

## ⚙️ Installation & Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/vishnu601/jalscan-sih.git
    cd jalscan-sih
    ```

2.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configure Environment Variables:**
    Create a `.env` file in the root directory and add your credentials:
    ```env
    SECRET_KEY=your_secret_key
    DATABASE_URL=sqlite:///jalscan.db
    TWILIO_ACCOUNT_SID=your_twilio_sid
    TWILIO_AUTH_TOKEN=your_twilio_token
    TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
    ```

4.  **Run the Application:**
    ```bash
    python3 app.py
    ```
    The app will start at `http://127.0.0.1:5000`.

## 📱 WhatsApp Bot Commands

Users can interact with the JalScan bot using these commands:
*   `SUBSCRIBE`: Opt-in for flood alerts.
*   `STATUS`: Check the water level of the nearest river.
*   `UNSUBSCRIBE`: Stop receiving alerts.
*   **Share Location**: Send a location attachment to update your position for geo-targeted alerts.

## 🧪 Testing

*   **Simulation Mode**: If Twilio keys are missing, the app runs in simulation mode and logs alerts to the terminal instead of sending them.
*   **Test Script**: Run `python3 test_submission.py` to simulate a high-water level report and trigger an alert.

## 👥 Contributors

*   **Vishnu Mukkavilli** - *Lead Developer*
