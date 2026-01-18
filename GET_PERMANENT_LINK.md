# 🌐 How to Get a Permanent Link (24/7 Online)

To give your website a **permanent link** (like `your-app.onrender.com`) that works forever, you need to put your code on a cloud server.

Since I cannot create accounts for you, please follow these 3 steps exactly.

### Step 1: Install Git (Required)
Your computer is missing a tool called `Git`. You need it to send your code to the cloud.
1.  **Download Git**: [Click here to download Git for Windows](https://git-scm.com/download/win)
2.  Install it (Keep clicking "Next" -> "Next" -> "Finish").
3.  **Restart your terminal** (Close this VS Code window and open it again).

### Step 2: Upload Code to GitHub
1.  Log in to [GitHub.com](https://github.com) (Create an account if you don't have one).
2.  Click the **+** icon (top right) -> **New repository**.
3.  Name it `college-notes` and click **Create repository**.
4.  Copy the commands they show you (or run the ones below in your terminal):
    ```bash
    git init
    git add .
    git commit -m "Ready for deploy"
    git branch -M main
    # Replace URL below with YOUR new repository URL
    git remote add origin https://github.com/YOUR_USERNAME/college-notes.git
    git push -u origin main
    ```

### Step 3: Connect to Render (Hosting)
1.  Go to [Render.com](https://render.com) and sign up with GitHub.
2.  Click **New +** -> **Web Service**.
3.  Select your `college-notes` repository.
4.  Scroll down to **Environment Variables** and add:
    *   `CLOUDINARY_CLOUD_NAME`: `dldydrqdb`
    *   `CLOUDINARY_API_KEY`: `756177661263517`
    *   `CLOUDINARY_API_SECRET`: `PcA6CTww57imc8HAWi2tsN033eo`
    *   `SECRET_KEY`: `any_secret_password`
5.  Click **Create Web Service**.

**Done!** Render will give you a link like `https://college-notes.onrender.com`. This is your permanent link.
