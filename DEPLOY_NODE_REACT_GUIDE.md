# 🚀 Deployment Guide: Node.js (Render) + React (Vercel) + Cloudinary

This guide outlines how to deploy a full-stack application with a **Node.js/Express backend** and a **React frontend**, using **Cloudinary** for image storage.

---

## 🏗️ Phase 1: Cloudinary Setup (Image Storage)
*Before deploying, get your API keys.*

1.  **Create an Account**: Go to [Cloudinary.com](https://cloudinary.com/) and sign up.
2.  **Dashboard**: unique "Cloud Name", "API Key", and "API Secret" are visible on the dashboard.
3.  **Keep these handy** for Phase 2.

---

## ⚙️ Phase 2: Backend Deployment (Render.com)
*We deploy the backend first so the frontend has an API URL to connect to.*

### 1. Prepare Your Node.js Project
Ensure your `package.json` has a start script:
```json
"scripts": {
  "start": "node index.js"
}
```
*Make sure you are listening on `process.env.PORT` in your code:*
```javascript
const port = process.env.PORT || 5000;
app.listen(port, () => console.log(`Server running on port ${port}`));
```

### 2. Push to GitHub
Upload your backend code to a GitHub repository.

### 3. Deploy on Render
1.  Log in to [Render.com](https://render.com).
2.  Click **New +** → **Web Service**.
3.  Connect your backend GitHub repository.
4.  **Settings**:
    *   **Runtime**: Node
    *   **Build Command**: `npm install`
    *   **Start Command**: `npm start`
5.  **Environment Variables** (Scroll down):
    Add the following keys from Cloudinary:
    *   `CLOUDINARY_CLOUD_NAME`: `your_cloud_name`
    *   `CLOUDINARY_API_KEY`: `your_api_key`
    *   `CLOUDINARY_API_SECRET`: `your_api_secret`
6.  Click **Create Web Service**.

### 4. Get Backend URL
Once deployed (green "Live" badge), copy the **onrender.com URL** (e.g., `https://my-api.onrender.com`). You will need this for the frontend.

---

## 🎨 Phase 3: Frontend Deployment (Vercel)
*Now we deploy the React/Next.js frontend.*

### 1. Prepare Your React Project
Ensure your frontend makes API calls to the **backend URL** (not localhost).
*Best Practice: Use an Environment Variable.*
```javascript
const API_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:5000";
// OR for Create React App: process.env.REACT_APP_API_BASE_URL
fetch(`${API_URL}/users`)
```

### 2. Push to GitHub
Upload your frontend code to a GitHub repository.

### 3. Deploy on Vercel
1.  Log in to [Vercel.com](https://vercel.com).
2.  Click **Add New...** → **Project**.
3.  Import your frontend GitHub repository.
4.  **Build Settings**: Vercel usually auto-detects React/Vite/Next.js. Leave as default unless you have custom setups.
5.  **Environment Variables**:
    *   Key: `VITE_API_BASE_URL` (or `REACT_APP_API_BASE_URL` depending on your setup).
    *   Value: Your Render Backend URL (e.g., `https://my-api.onrender.com`).
    *   *Note: Do not include a trailing slash `/` unless your code expects it.*
6.  Click **Deploy**.

---

## ✅ Phase 4: Verification
1.  Open your **Vercel App URL**.
2.  Test a feature that uses the backend (e.g., Log in).
3.  Test an image upload (should save to **Cloudinary**).

---

## 🔧 Troubleshooting
*   **CORS Errors**: If the frontend fails to talk to the backend, go to your Node.js backend code and ensure CORS is allowed for your Vercel domain:
    ```javascript
    const cors = require('cors');
    app.use(cors({
      origin: 'https://your-frontend-app.vercel.app'
    }));
    ```
*   **Images invalid**: Check your Cloudinary env vars on Render.
