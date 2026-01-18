# 🚀 Deployment Guide (Professional Version)

This guide helps you deploy the **College Notes Platform** with a **Permanent Database (Postgres)** and **Permanent Storage (Cloudinary)**.

## Step 1: Push to GitHub
I have already connected your project to:
`https://github.com/suasri2006/notes-share.git`
The latest code with Postgres support is already there.

## Step 2: Create a Database on Render
1.  Go to [Render.com](https://render.com).
2.  Click **"New"** (blue button) -> **"PostgreSQL"**.
3.  Name it `notes-db`.
4.  Click **"Create Database"**.
5.  **Stop!** On the database page, find the **"Internal Database URL"**. It looks like:
    `postgres://user:password@hostname:5432/dbname`
    (You will need this in Step 3).

## Step 3: Create the Web Service
1.  Go to your Render Dashboard.
2.  Click **"New"** -> **"Web Service"**.
3.  Connect your `notes-share` repository.
4.  **Settings**:
    *   **Start Command**: `gunicorn app:app`
5.  **Environment Variables**:
    Add the following:
    *   `DATABASE_URL`: (Paste the **Internal Database URL** from Step 2 here).
    *   `CLOUDINARY_CLOUD_NAME`: `dgwfdlwcw`
    *   `CLOUDINARY_API_KEY`: `498172598213555`
    *   `CLOUDINARY_API_SECRET`: `cWEMdSyhMtbD2krGk89oEiBRTNQ`
    *   `SECRET_KEY`: `any-random-string123`
    *   `PYTHON_VERSION`: `3.10`

## Step 4: Done!
When Render finishes building, your site will be live.
The app will automatically detect PostgreSQL and setup all tables (`users`, `files`, `comments`) on the first run.

---
**Note about the ID you provided (`dpg-d5mgmrkoud1c739ce520-a`):**
That is your **Database ID** on Render. You don't need to put that in the code. Instead, just use the **Internal Database URL** as shown in Step 2 above. Render handles the connection using that URL!
