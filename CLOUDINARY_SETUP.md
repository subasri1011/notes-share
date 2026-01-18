# Cloudinary Setup Guide (Forever Free)

**Cloudinary** is the best "Forever Free" option for your notes app.
*   **Storage/Bandwidth:** You get ~25 Free Credits per month (approx. 25GB of combined storage and viewing bandwidth).
*   **Cost:** $0 (Free Forever tier).

## 1. Create Account
1.  Go to [cloudinary.com](https://cloudinary.com/users/register/free).
2.  Sign up (Email/GitHub/Google).
3.  You will be taken to the **Dashboard**.

## 2. Get Credentials
On the Dashboard, look for the **"Product Environment Credentials"** section at the top left.
You need three things:
1.  **Cloud Name**
2.  **API Key**
3.  **API Secret**

*(Click the "Copy" icon or "Reveal" eye to see them).*

## 3. Connect App
Create or update your `.env` file in the project folder with these values:

```ini
# Comment out AWS lines if you have them
# AWS_ACCESS_KEY_ID=...

# Add Cloudinary Configuration
CLOUDINARY_CLOUD_NAME=paste_cloud_name_here
CLOUDINARY_API_KEY=paste_api_key_here
CLOUDINARY_API_SECRET=paste_api_secret_here
```

## 4. That's it!
Restart your app (`python app.py`). It will detect Cloudinary and start using it automatically!
