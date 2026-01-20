path = 'app.py'
with open(path, 'rb') as f:
    content = f.read()

# Look for the start of the corrupted section
# It starts with \r\n\r\n and then some nul bytes/UTF-16
# Let's find the last 'return render_template('admin.html', users=users, files=files)'
marker = b"return render_template('admin.html', users=users, files=files)"
if marker in content:
    idx = content.rfind(marker) + len(marker)
    clean_content = content[:idx]
    
    # Add the missing footer
    footer = """

if __name__ == '__main__':
    if not os.path.exists(app.config['UPLOAD_FOLDER']):
        os.makedirs(app.config['UPLOAD_FOLDER'])
    # SECURITY: Debug disabled, 0.0.0.0 for mobile access
    app.run(host='0.0.0.0', debug=False, port=5000)
"""
    with open(path, 'wb') as f:
        f.write(clean_content)
        f.write(footer.encode('utf-8'))
    print("Fixed app.py footer.")
else:
    print("Marker not found!")
