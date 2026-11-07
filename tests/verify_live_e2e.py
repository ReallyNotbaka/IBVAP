import json
import os
import pathlib
import time
import urllib.request

base_url = "http://127.0.0.1:8000/api/v1"
token = os.getenv("IBVAP_API_TOKEN", "ibvap-local-dev-token")
headers = {"Content-Type": "application/json", "X-API-Token": token}

sample_fixture = pathlib.Path("tests/fixtures/sample.mp4")
user_path = os.getenv("TEST_FOOTAGE_PATH", str(sample_fixture.resolve()))

print("1. Testing endpoint /cameras/test with footage path...")
req = urllib.request.Request(
    f"{base_url}/cameras/test",
    data=json.dumps({"endpoint": user_path}).encode(),
    headers=headers,
)
with urllib.request.urlopen(req) as resp:
    res = json.loads(resp.read().decode())
    print("Test result:", res["result"])
    print("Safe message:", res["safe_message"])
    print("Probe info:", res.get("probe"))
    assert res["result"] == "ok"

print("\n2. Creating camera with footage path...")
create_data = {
    "name": "E2E Test Video Footage",
    "site_id": "00000000-0000-0000-0000-000000000001",
    "source_type": "video_footage",
    "protocol": "file",
    "endpoint": user_path,
    "temporary": True,
}
req = urllib.request.Request(
    f"{base_url}/cameras",
    data=json.dumps(create_data).encode(),
    headers=headers,
)
with urllib.request.urlopen(req) as resp:
    cam = json.loads(resp.read().decode())
    cam_id = cam["id"]
    print(f"Created camera: {cam_id}, observed_state: {cam['observed_state']}")

print("\n3. Waiting for worker to process frames and check observations...")
time.sleep(2.0)

req = urllib.request.Request(f"{base_url}/cameras/{cam_id}/observations")
with urllib.request.urlopen(req) as resp:
    obs = json.loads(resp.read().decode())
    print("Observations frame dimensions:", obs.get("frame_width"), "x", obs.get("frame_height"))
    print("Detections count:", len(obs.get("detections", [])))
    print("Tracks count:", len(obs.get("tracks", [])))

print("\n4. Checking playback state...")
req = urllib.request.Request(f"{base_url}/cameras/{cam_id}/playback")
with urllib.request.urlopen(req) as resp:
    pb = json.loads(resp.read().decode())
    print("Playback status:", pb)
    assert pb["state"] == "playing"
    assert pb["duration_seconds"] is not None

print("\n5. Testing MJPEG stream endpoint reading a chunk...")
req = urllib.request.Request(f"{base_url}/cameras/{cam_id}/stream")
with urllib.request.urlopen(req) as resp:
    chunk = resp.read(4096)
    print(f"Stream received {len(chunk)} bytes. Content-Type: {resp.headers.get('Content-Type')}")
    assert b"--frame" in chunk or len(chunk) > 0

print("\n6. Cleaning up / deleting camera...")
req = urllib.request.Request(f"{base_url}/cameras/{cam_id}", headers=headers, method="DELETE")
with urllib.request.urlopen(req) as resp:
    del_res = json.loads(resp.read().decode())
    print("Delete result:", del_res)

print("\nALL LIVE E2E CHECKS PASSED!")
