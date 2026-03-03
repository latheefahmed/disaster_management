import requests

BASE = "http://127.0.0.1:8000"

checks = [
    (
        "district_603",
        "district123",
        [
            ("/district/allocations", 20),
            ("/district/unmet", 20),
            ("/district/solver-status", 20),
            ("/district/run-history", 20),
            ("/district/requests?latest_only=true", 20),
            ("/district/stock", 20),
        ],
    ),
    (
        "state_33",
        "state123",
        [
            ("/state/requests", 20),
            ("/state/allocations/summary", 20),
            ("/state/pool", 20),
            ("/state/pool/transactions", 20),
            ("/state/mutual-aid/market", 20),
            ("/state/run-history", 20),
        ],
    ),
    (
        "national_admin",
        "national123",
        [
            ("/national/escalations", 20),
            ("/national/allocations/summary", 20),
            ("/national/pool", 20),
            ("/national/pool/transactions", 20),
            ("/national/run-history", 20),
        ],
    ),
    (
        "admin",
        "admin123",
        [
            ("/admin/scenarios", 20),
            ("/admin/agent/recommendations", 20),
            ("/admin/meta-controller/status", 20),
        ],
    ),
]

for username, password, paths in checks:
    login_resp = requests.post(
        f"{BASE}/auth/login",
        json={"username": username, "password": password},
        timeout=20,
    )
    print(f"\nUSER {username} LOGIN {login_resp.status_code}")
    if login_resp.status_code != 200:
        continue

    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    for path, timeout_sec in paths:
        try:
            resp = requests.get(f"{BASE}{path}", headers=headers, timeout=timeout_sec)
            print(f"  {resp.status_code} {path}")
        except Exception as exc:
            print(f"  ERR {path} {type(exc).__name__}")
