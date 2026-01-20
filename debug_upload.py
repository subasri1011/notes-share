import os
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv

load_dotenv()

cloudinary.config(
    cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'),
    api_key=os.getenv('CLOUDINARY_API_KEY'),
    api_secret=os.getenv('CLOUDINARY_API_SECRET'),
    secure=True
)

def test_upload(filename, local_path):
    print(f"Testing upload for {filename}...")
    try:
        # Create a dummy file
        with open(local_path, "w") as f: f.write("dummy content")
        
        # Upload with filename as public_id
        res = cloudinary.uploader.upload(
            local_path,
            public_id=filename,
            resource_type="auto"
        )
        print(f"Result: PublicID: {res.get('public_id')} | ResType: {res.get('resource_type')} | URL: {res.get('secure_url')}")
    except Exception as e:
        print(f"Error: {e}")

test_upload("test_via_script.pdf", "test_file.pdf")
test_upload("test_via_script.docx", "test_file.docx")
