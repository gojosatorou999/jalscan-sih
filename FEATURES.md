# JalScan - Features & Tech Stack

> **Only features that are actually implemented and working in the codebase**

---

## 📱 Core Features

### 1. Water Level Capture & Submission
- **GPS-verified photo capture** with live camera feed
- **AI-powered water level OCR** using Google Gemini Vision API
- **Confidence scoring** for AI readings (0-100%)
- **Manual water level entry** as fallback
- **Photo proof storage** with timestamp embedding
- **Site-specific capture pages** with geofencing

### 2. QR Code Verification System
- **Dynamic QR code generation** for each monitoring site
- **Site-encoded QR data** with GPS coordinates
- **Scan-to-verify** location authentication
- **Batch QR download** for all sites
- **Print-ready PDF generation**

### 3. Multi-Step Public Submission Form
- **5-step wizard interface** for citizen reports
- **Government ID upload** (Aadhaar/Voter ID/PAN)
- **Live selfie capture** holding ID
- **Site selection** from active monitoring sites
- **Declaration checkbox** before final submit
- **Admin review workflow** for public submissions

---

## 📊 Dashboards & Analytics

### 4. Main Dashboard
- **Recent submissions feed** with status indicators
- **Quick stats cards** (total submissions, sync status)
- **Site-wise breakdown** of activity
- **Role-based view** (different content for admin vs field agent)

### 5. Analytics Dashboard
- **Submissions by date** (line chart)
- **Water level trends** by site (multi-line chart)
- **Submissions by site** (pie chart)
- **User activity ranking** (bar chart)
- **Quality rating distribution** (bar chart)
- **Date range filters** (7/14/30/90 days)

### 6. Cloud Dashboard (Supervisor+)
- **Real-time sync status** overview
- **Critical alerts feed** with severity badges
- **Activity log** with timestamps
- **Performance metrics** per site
- **Site health status cards**

### 7. Flood Risk Dashboard
- **Site risk cards** with color-coded severity
- **AI confidence scores** per prediction
- **Risk explanations** in human-readable format
- **Recommendations** based on risk level
- **Modal for detailed site view**

### 8. River Memory AI Dashboard
- **Digital twin timeline** for each site
- **Water color analysis** visualization
- **Flow speed estimation** display
- **Gauge health indicators**
- **Anomaly detection alerts**
- **Date range filtering** (7/30/90 days)
- **Site selector dropdown** with disabled state

---

## 🛡️ Security & Verification

### 9. Tamper Detection Engine
- **AI-powered tamper analysis** on submissions
- **Tamper score calculation** (0-1 scale)
- **Detection by type**: Location mismatch, timestamp anomaly, image manipulation
- **Review workflow**: Pending → Confirmed/False Positive
- **Batch analysis** capability
- **Trend visualization over time**

### 10. Role-Based Access Control
- **4 user roles**: Admin, Supervisor, Central Analyst, Field Agent
- **Role-specific navigation** (sidebar + mobile)
- **Permission decorators** on routes
- **Admin-only pages**: Sites, Subscribers, Users, Public Submissions

---

## 🤖 AI Features

### 11. JalScan GPT Chatbot
- **Floating chat widget** on all pages
- **Natural language flood queries**
- **Intent detection** (flood_risk, flash_flood, water_level, prediction, explanation)
- **Site name extraction** from user messages
- **Risk-level templated responses**
- **API endpoint** for web integration

### 12. River Memory AI Pipeline
- **Water Color Analysis** (HSV-based)
  - 6 classes: clear, silt, muddy, green, dark, polluted
  - Color index calculation (0-1 turbidity scale)
- **Flow Speed Estimation**
  - Optical flow for multi-frame
  - Texture analysis (Laplacian + Gabor) for single-frame
  - 5 classes: still, low, moderate, high, turbulent
- **Anomaly Detection**
  - Rapid rise/fall detection (>30cm/1h, >50cm/3h)
  - Color change alerts
  - Flow spike detection
  - Combined flash flood indicators
- **Gauge Health Monitoring**
  - Algae detection
  - Fading/damage detection
  - Visibility scoring

### 13. Flood Risk ML Prediction
- **RandomForest classifier** with 24 features
- **4 risk categories**: SAFE, CAUTION, FLOOD_RISK, FLASH_FLOOD_RISK
- **Rule-based fallback** when no trained model
- **Explainability** with key factors
- **Per-site predictions** via API

---

## 📞 Communication & Alerts

### 14. WhatsApp Integration
- **Twilio WhatsApp API** webhook
- **Incoming message handling**
- **JalScan GPT responses** via WhatsApp
- **Subscriber management page**

### 15. AI Voice Call Reporting
- **Twilio Voice API** integration
- **Speech-to-text input** for water levels
- **IVR menu navigation**
- **External CSV sync** from Replit agent
- **Voice submission dashboard**

### 16. Weather Map
- **Site locations on map** (via Leaflet)
- **Temperature/weather display** per site
- **Risk overlay visualization**
- **Alert triggering** from map

---

## 🔧 Admin Features

### 17. Site Management
- **Add/Edit/Delete** monitoring sites
- **GPS coordinates** entry
- **Alert/Danger threshold** configuration
- **River type** classification
- **Site assignment** to users

### 18. User Management
- **Create new users** with roles
- **View all users** list
- **Role assignment**
- **Site-to-user mapping**

### 19. My Submissions
- **Search by site name**
- **Filter by status** (synced/pending/failed)
- **Filter by quality** (star ratings)
- **Filter by date range** (7/30/90 days)
- **Image preview modal**
- **Delete submission**
- **Export to CSV/PDF**

---

## 📱 PWA Features

### 20. Progressive Web App
- **Service Worker** for offline caching
- **Web App Manifest** for installation
- **Mobile bottom navigation**
- **Responsive design** (Bootstrap 5)
- **Install app prompt**

---

## 🛠️ Tech Stack

| Layer | Technology | Version |
|-------|------------|---------|
| **Backend** | Python | 3.13 |
| | Flask | 2.3.3 |
| | Flask-SQLAlchemy | 3.0.5 |
| | Flask-Login | 0.6.3 |
| | Werkzeug | 2.3.7 |
| **Database** | SQLite | Built-in |
| **AI/ML** | Google Gemini API | 0.8.5 |
| | OpenCV (cv2) | Latest |
| | NumPy | Latest |
| | scikit-learn | Latest |
| **Frontend** | Bootstrap | 5.1.3 |
| | Bootstrap Icons | 1.11.1 |
| | Chart.js | 4.x |
| | Leaflet.js | 1.9.x |
| **Integrations** | Twilio Voice API | 8.5.0 |
| | Twilio WhatsApp API | 8.5.0 |
| **Utilities** | QRCode | 7.4.2 |
| | Pillow | Latest |
| | python-dotenv | 1.0.0 |

---

## 🌟 WOW Factor - What Makes JalScan Stand Out

### 🧠 "River Memory" - India's First AI Digital Twin for Rivers

> *"Sir, our app doesn't just read water levels. It REMEMBERS the river."*

| Ordinary Apps | JalScan |
|---------------|---------|
| Take photo, read number | AI analyzes color, flow, gauge health, erosion |
| Static water level | Historical timeline with AI annotations |
| Manual alerts | Anomaly detection with configurable thresholds |
| Single data point | 24 engineered features for ML prediction |

### 🔮 Predictive Intelligence, Not Just Monitoring

| What Others Do | What JalScan Does |
|----------------|-------------------|
| Show current level | Predict risk 6 hours ahead |
| Simple threshold alerts | 4-tier risk classification with explanations |
| "Water is high" | "Water rose 35cm in 1 hour - Flash flood risk 87%" |

### 💬 Conversational AI for Everyone

| Traditional Apps | JalScan GPT |
|------------------|-------------|
| Complex dashboards | "What's the flood risk at Ganga River?" |
| Technical jargon | Natural language answers with recommendations |
| Web-only | WhatsApp integration for mobile access |

### 🛡️ Trust Through Verification

| Basic Apps | JalScan |
|------------|---------|
| Accept any photo | GPS geofencing + QR verification |
| No audit trail | Tamper detection with AI scoring |
| Anonymous submissions | ID-verified public contributions |

### 📊 Multi-Modal Data Ingestion

```
┌─────────────────────────────────────────────────────────────┐
│                 JalScan Data Sources                        │
├─────────────┬─────────────┬─────────────┬──────────────────┤
│ 📷 Camera   │ 📱 QR Code  │ 📞 Voice    │ 🌐 Public        │
│ Field Agent │ Site Verify │ Twilio IVR  │ Citizen Reports  │
├─────────────┴─────────────┴─────────────┴──────────────────┤
│                    → AI Processing →                        │
│     Gemini Vision | OpenCV | RandomForest | Rule Engine     │
├─────────────────────────────────────────────────────────────┤
│                    → Predictions →                          │
│   SAFE | CAUTION | FLOOD_RISK | FLASH_FLOOD_RISK           │
└─────────────────────────────────────────────────────────────┘
```

### 🎯 The One-Liner Pitch

> **"JalScan is to river monitoring what MRI is to X-ray - it doesn't just show you the water level, it shows you the river's health, behavior, and future."**

---

## 📈 By The Numbers

| Metric | Value |
|--------|-------|
| Routes/Endpoints | 107 |
| HTML Templates | 22 |
| Database Models | 8 |
| AI/ML Components | 6 |
| Dashboard Pages | 7 |
| Lines of Python | 3,418+ |

---

*Updated: December 2024*
