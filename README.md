# College Notes Platform

A secure platform for college students to share and access study materials.

## Features
- **Public Access**: Search and download notes.
- **Student Access**: Upload notes (PDF, PPT, DOC, EXE, ZIP).
- **Admin Access**: Manage content and users.
- **Secure**: Password hashing, specific file types only.

## Setup & Run
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Initialize Database (if not already done):
   ```bash
   python database_setup.py
   ```
3. Run the App:
   ```bash
   python app.py
   ```
4. Open your browser at: `http://127.0.0.1:5000`

## Render Deployment Setup

### Firebase Authentication Setup

To enable DSCE Google Sign-In on Render:

1. Go to Firebase Console → Project Settings → Service Accounts
2. Click "Generate new private key" to download the service account JSON
3. In Render Dashboard, go to your Web Service → Environment → Add Environment Variable
4. Add a variable named `FIREBASE_CREDENTIALS_JSON` and paste the entire JSON content as the value
5. Redeploy the application

Alternatively, you can set `GOOGLE_APPLICATION_CREDENTIALS` to point to a credentials file if you prefer file-based authentication.

### Required Environment Variables

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL connection string (from Neon or similar) |
| `FIREBASE_CREDENTIALS_JSON` | Firebase service account JSON (for DSCE login) |
| `SECRET_KEY` | Random secret for Flask sessions |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary cloud name |
| `CLOUDINARY_API_KEY` | Cloudinary API key |
| `CLOUDINARY_API_SECRET` | Cloudinary API secret |
