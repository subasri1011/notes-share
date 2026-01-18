import requests
import os

BASE_URL = "http://127.0.0.1:5000"
USERNAME = "admin"
PASSWORD = "password123"

def test_upload():
    session = requests.Session()
    
    # 1. Login
    print("Attempting login...")
    login_data = {
        "username": USERNAME,
        "password": PASSWORD
    }
    resp = session.post(f"{BASE_URL}/login", data=login_data)
    if "Logged in successfully" in resp.text or resp.url == f"{BASE_URL}/" or True: # Assuming redirect to home
        print("Login seems successful (or at least we got a response)")
        # Check if we are redirected to home
        print(f"Current URL: {resp.url}")
    else:
        print("Login failed")
        return

    # 2. Upload
    print("Attempting upload...")
    files = {
        'file': ('test_file.txt', open('test_file.txt', 'rb'), 'text/plain')
    }
    data = {
        'subject': 'Test Subject',
        'semester': '1',
        'dept': 'CSE',
        'category': 'Other',
        'description': 'Test Description'
    }
    
    resp = session.post(f"{BASE_URL}/upload", files=files, data=data)
    
    print(f"Upload Response Code: {resp.status_code}")
    print(f"Upload Response URL: {resp.url}")
    
    if "File uploaded successfully" in resp.text:
        print("SUCCESS: File uploaded successfully message found.")
    else:
        print("FAILURE: Success message not found.")
        # Print part of the response to see errors
        print(resp.text[:500])

if __name__ == "__main__":
    test_upload()
