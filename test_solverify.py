"""
Test script to verify Solverify works with Upwork
"""
import time
import requests
from curl_cffi import requests as curl_requests

# Solverify credentials
CLIENT_KEY = "b0RDD2GdYC4qn0frQyeEpC9rcZXwOcD6yNZvKnLCxnJNgFLLCcygZu4KM30WKNyW"
CREATE_TASK_URL = "https://solver.solverify.net/createTask"
GET_RESULT_URL = "https://solver.solverify.net/getTaskResult"

# Target
TARGET_URL = "https://www.upwork.com/nx/search/jobs/?sort=recency&per_page=50"

# Your Webshare proxy (from your .env)
PROXY = "http://tfbunegq-1:9zyzv0v5wsv5@p.webshare.io:80"


def solve_cloudflare(url, proxy):
    """Send task to Solverify to solve Cloudflare"""
    print(f"[*] Sending Cloudflare solve request to Solverify...")
    print(f"[*] URL: {url}")
    print(f"[*] Proxy: {proxy[:30]}...")
    
    # Parse proxy
    proxy_clean = proxy.replace("http://", "").replace("https://", "")
    if "@" in proxy_clean:
        auth, host_port = proxy_clean.split("@")
        username, password = auth.split(":")
        host, port = host_port.split(":")
    else:
        parts = proxy_clean.split(":")
        host = parts[0]
        port = parts[1]
        username = parts[2] if len(parts) > 2 else ""
        password = parts[3] if len(parts) > 3 else ""

    payload = {
        "clientKey": CLIENT_KEY,
        "task": {
            "type": "interstitial",  # For Cloudflare interstitial challenges
            "websiteURL": url,
            "proxyType": "http",
            "proxyAddress": host,
            "proxyPort": str(port),
            "proxyLogin": username,
            "proxyPassword": password
        }
    }

    print(f"[*] Creating task with payload: {payload['task']['type']}")
    
    response = requests.post(CREATE_TASK_URL, json=payload)
    print(f"[*] Create task response: {response.status_code}")
    
    if response.status_code != 200:
        print(f"[!] Failed to create task: {response.text}")
        return None

    data = response.json()
    print(f"[*] Response data: {data}")
    
    if data.get("errorId") != 0:
        print(f"[!] API Error: {data}")
        return None

    task_id = data.get("taskId")
    print(f"[*] Task created! ID: {task_id}")
    print(f"[*] Polling for result (timeout: 5 minutes)...")

    poll_payload = {
        "clientKey": CLIENT_KEY,
        "taskId": task_id
    }

    start_time = time.time()
    attempt = 0
    while time.time() - start_time < 300:
        time.sleep(5)
        attempt += 1
        try:
            res = requests.post(GET_RESULT_URL, json=poll_payload)
            if res.status_code != 200:
                print(f"[*] Poll attempt {attempt}: HTTP {res.status_code}")
                continue
                
            res_data = res.json()
            status = res_data.get("status", "unknown")
            print(f"[*] Poll attempt {attempt}: status={status}")
            
            if status == "completed":
                print(f"[✓] Task completed!")
                return res_data.get("solution")
            
            if res_data.get("errorId") != 0:
                print(f"[!] Polling API Error: {res_data}")
                return None
                
        except Exception as e:
            print(f"[!] Polling error: {e}")
            
    print("[!] Task timed out after 5 minutes.")
    return None


def fetch_upwork(solution, proxy):
    """Use the solved cookies to fetch Upwork"""
    print("\n[*] Attempting to fetch Upwork with solved cookies...")
    
    cookies = solution.get("cookies", {})
    user_agent = solution.get("useragent", "Mozilla/5.0")
    
    print(f"[*] Got {len(cookies)} cookies")
    print(f"[*] Cookies: {list(cookies.keys())}")
    print(f"[*] User-Agent: {user_agent[:50]}...")
    
    if "cf_clearance" not in cookies:
        print("[!] WARNING: cf_clearance cookie is MISSING!")
    else:
        print("[✓] cf_clearance cookie present")

    proxies = {
        "http": proxy,
        "https": proxy
    }

    try:
        print(f"[*] Making request to Upwork...")
        response = curl_requests.get(
            TARGET_URL,
            cookies=cookies,
            headers={"User-Agent": user_agent},
            proxies=proxies,
            impersonate="chrome",
            timeout=30
        )

        print(f"[*] Response status: {response.status_code}")
        print(f"[*] Response length: {len(response.text)} chars")
        
        # Check if it's a Cloudflare challenge page
        if "Checking your browser" in response.text or "Just a moment" in response.text:
            print("[!] FAILED: Still getting Cloudflare challenge page")
            with open("solverify_failed.html", "w", encoding="utf-8") as f:
                f.write(response.text)
            print("[*] Saved response to solverify_failed.html")
            return False
            
        # Check if we got actual job data
        if "job-tile" in response.text or "search-results" in response.text:
            print("[✓] SUCCESS! Got actual Upwork job data!")
            with open("solverify_success.html", "w", encoding="utf-8") as f:
                f.write(response.text)
            print("[*] Saved response to solverify_success.html")
            
            # Count jobs
            job_count = response.text.count('data-test="job-tile"')
            print(f"[✓] Found approximately {job_count} job tiles!")
            return True
        else:
            print("[?] Unknown response - saving for inspection")
            with open("solverify_unknown.html", "w", encoding="utf-8") as f:
                f.write(response.text)
            print("[*] Saved response to solverify_unknown.html")
            return False

    except Exception as e:
        print(f"[!] curl_cffi error: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("SOLVERIFY + UPWORK TEST")
    print("=" * 60)
    print()
    
    # Step 1: Solve Cloudflare
    solution = solve_cloudflare(TARGET_URL, PROXY)
    
    if solution:
        print("\n" + "=" * 60)
        print("SOLUTION RECEIVED")
        print("=" * 60)
        
        # Step 2: Use solution to fetch Upwork
        success = fetch_upwork(solution, PROXY)
        
        print("\n" + "=" * 60)
        if success:
            print("RESULT: ✓ SOLVERIFY WORKS WITH UPWORK!")
            print("Cost: $0.20 per 1000 requests (interstitial)")
            print("This could reduce your scraping costs by 80%+")
        else:
            print("RESULT: ✗ SOLVERIFY DID NOT WORK")
            print("Sticking with BrightData is recommended")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("RESULT: ✗ FAILED TO SOLVE CLOUDFLARE")
        print("Solverify could not complete the challenge")
        print("=" * 60)
