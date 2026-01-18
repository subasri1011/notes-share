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

## Default Credentials
**Admin:**
- Username: `admin`
- Password: `admin123`

**Student:**
- Username: `student`
- Password: `student123`
