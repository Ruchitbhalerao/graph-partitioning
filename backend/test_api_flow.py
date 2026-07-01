import urllib.request
import urllib.parse
import json
import time

BASE_URL = "http://localhost:5000/api/v1"
DATA_FILE = "../Pune_Dataset_Large.xlsx"

def multipart_post(url, file_path):
    import io, uuid
    boundary = uuid.uuid4().hex
    
    with open(file_path, "rb") as f:
        file_content = f.read()
    
    body = io.BytesIO()
    body.write(f"--{boundary}\r\n".encode("utf-8"))
    body.write(f"Content-Disposition: form-data; name=\"file\"; filename=\"Pune_Dataset_Large.xlsx\"\r\n".encode("utf-8"))
    body.write(b"Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n")
    body.write(file_content)
    body.write(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    
    req = urllib.request.Request(url, data=body.getvalue())
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
    
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def run_test():
    print("Uploading file...")
    try:
        data = multipart_post(f"{BASE_URL}/upload", DATA_FILE)
        job_id = data["job_id"]
        print("Job ID:", job_id)
    except Exception as e:
        print("Upload failed:", e)
        return
        
    print("Starting optimization...")
    req = urllib.request.Request(f"{BASE_URL}/optimize/{job_id}", data=b"{}", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        pass
        
    while True:
        req = urllib.request.Request(f"{BASE_URL}/status/{job_id}")
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            status = data.get("status")
            print(f"Status: {status}, Progress: {data.get('progress')}")
            if status == "completed":
                break
            if status in ("cancelled", "error"):
                return
        time.sleep(1)
        
    print("Generating exports...")
    req = urllib.request.Request(f"{BASE_URL}/export/{job_id}/generate?include_routes=false", data=b"", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            print("Export success:", resp.read())
    except urllib.error.HTTPError as e:
        print("Export failed:", e.code, e.read().decode())

if __name__ == "__main__":
    run_test()
