import cloudinary
import cloudinary.utils

cloudinary.config(
    cloud_name="dgwfdlwcw",
    api_key="498172598213555",
    api_secret="cWEMdSyhMtbD2krGk89oEiBRTNQ",
    secure=True
)

def test_url(filename, res_type):
    # This matches the current logic in app.py
    public_id = filename 
    ext = filename.rsplit('.', 1)[1].lower() if '.' in filename else ''
    
    # Current broken logic (Step 235/239)
    url, _ = cloudinary.utils.cloudinary_url(public_id, resource_type=res_type, format=ext)
    print(f"RES_TYPE: {res_type} | FILENAME: {filename} | URL: {url}")

test_url("test.pdf", "image")
test_url("test.pdf", "raw")
test_url("test.docx", "raw")
