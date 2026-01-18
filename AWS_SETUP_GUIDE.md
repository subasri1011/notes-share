# AWS S3 Setup Guide

To move your notes to the cloud, you need an **AWS S3 Bucket** and **Credentials**. Follow these steps strictly:

## 1. Create an AWS Account
Go to [aws.amazon.com](https://aws.amazon.com/) and sign up. It requires a credit card for identity verification, but S3 has a generous free tier (5GB storage).

## 2. Create an S3 Bucket (Storage Container)
1.  Search for **S3** in the AWS Console search bar.
2.  Click **Create bucket**.
3.  **Bucket Name**: Choose a *globally unique* name (e.g., `noteshare-app-storage-2026`).
4.  **Region**: Select a region close to you (e.g., `ap-south-1` for Mumbai).
5.  **Block Public Access**: **Uncheck** "Block all public access" (for now, to keep things simple).
    *   *Warning checkbox*: Acknowledge that current settings might result in this bucket being public.
6.  Click **Create bucket** at the bottom.

## 3. Create Credentials (IAM User)
1.  Search for **IAM** in the AWS Console.
2.  Click **Users** -> **Create user**.
3.  **User name**: `noteshare-uploader`.
4.  Click **Next**.
5.  **Permissions options**: Select **"Attach policies directly"**.
6.  Search for `AmazonS3FullAccess` and check the box next to it.
7.  Click **Next** -> **Create user**.

## 4. Get Access Keys
1.  Click on the newly created user `noteshare-uploader`.
2.  Go to the **Security credentials** tab.
3.  Scroll down to **Access keys**.
4.  Click **Create access key**.
5.  Select **Local code** (or Other), accept the warning, and click **Next**.
6.  **IMPORTANT**: You will see an **Access Key ID** and a **Secret Access Key**.
    *   **COPY THESE NOW.** You cannot see the Secret Key again.

## 5. Connect Your App
Create a file named `.env` in your project folder (`c:/Users/NFS Photographer/Documents/College Notes Platform/.env`) and paste the following:

```ini
AWS_ACCESS_KEY_ID=Put_Your_Access_Key_Here
AWS_SECRET_ACCESS_KEY=Put_Your_Secret_Key_Here
S3_BUCKET_NAME=your-bucket-name
AWS_REGION=ap-south-1
```

Once you do this, restart your app. It will automatically detect these keys and start using the Cloud!
