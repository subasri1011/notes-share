# 🚀 Deployment Guide (Render + Cloudinary)

This guide takes your code from your laptop to the world for **FREE**.

## Prerequisite: Database Note
*   **Locally**, we use `users.db` (SQLite).
*   **On Render**, SQLite files **get deleted** when the server restarts.
    *   *Option A (Quick/Temporary)*: Use SQLite, but expect user accounts and comments to reset daily.
    *   *Option B (Real Prod)*: Connect to a **PostgreSQL** database (Render offers a free tier).
    *   *For now*: We will deploy assuming Option A to get you online fast.

---

## Step 1: Prepare Code (Running Now)
I have already created the necessary files for you:
1.  `Procfile` (Tells Render how to run the app).
2.  `requirements.txt` (List of required libraries like Flask, Cloudinary, Gunicorn).

## Step 2: Push to GitHub
You need to put your code on GitHub.
1.  Create a **New Repository** on GitHub (e.g., `noteshare-app`).
2.  Run these commands in your terminal:
    ```bash
    git init
    git add .
    git commit -m "Initial commit"
    git branch -M main
    git remote add origin https://github.com/YOUR_USERNAME/noteshare-app.git
    git push -u origin main
    ```

## Step 3: Deploy on Render.com
1.  Go to [Render.com](https://render.com) and sign up (GitHub login recommended).
2.  Click **"New + "** -> **"Web Service"**.
3.  Connect your GitHub repository.
4.  **Settings**:
    *   **Name**: `noteshare-platform` (or similar)
    *   **Region**: Singapore (closest) or default.
    *   **Branch**: `main`
    *   **Runtime**: `Python 3`
    *   **Build Command**: `pip install -r requirements.txt`
    *   **Start Command**: `gunicorn app:app`
5.  **Environment Variables** (Crucial!):
    Scroll down to "Environment Variables" and add:
    *   `CLOUDINARY_CLOUD_NAME`: `dldydrqdb`
    *   `CLOUDINARY_API_KEY`: `756177661263517`
    *   `CLOUDINARY_API_SECRET`: `PcA6CTww57imc8HAWi2tsN033eo`
    *   `SECRET_KEY`: `some_random_secret_string`

6.  Click **"Create Web Service"**.

## Step 4: Go Live! 🌐
Render will build your app (takes ~2 minutes). Once done, it will give you a URL like:
`https://noteshare-platform.onrender.com`

**Share this link with your college!**
All uploaded notes will live safely in Cloudinary, so they will persist forever.
