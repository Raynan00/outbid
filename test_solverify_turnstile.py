"""
Test Solverify TURNSTILE solver with Upwork
Turnstile is Cloudflare's invisible challenge - more likely to work!
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

# Your Webshare proxy
PROXY = "http://tfbunegq-1:9zyzv0v5wsv5@p.webshare.io:80"

# Cloudflare Turnstile sitekey for Upwork (we need to extract this)
# Common Cloudflare sitekeys - we'll try the visible one from the challenge page
TURNSTILE_SITEKEY = None  # Will try to extract


def get_turnstile_sitekey(proxy):
    """First, visit the page to get the Turnstile sitekey"""
    print("[*] Step 1: Fetching page to extract Turnstile sitekey...")
    
    proxies = {"http": proxy, "https": proxy}
    
    try:
        response = curl_requests.get(
            TARGET_URL,
            proxies=proxies,
            impersonate="chrome",
            timeout=30
        )
        
        html = response.text
        
        # Look for Turnstile sitekey in the HTML
        # Usually in format: data-sitekey="0x..." or sitekey: '0x...'
        import re
        
        # Try different patterns
        patterns = [
            r'data-sitekey="([^"]+)"',
            r"data-sitekey='([^']+)'",
            r'sitekey["\']?\s*[:\=]\s*["\']([0-9a-zA-Z_-]+)["\']',
            r'turnstileSiteKey["\']?\s*[:\=]\s*["\']([^"\']+)["\']',
            r'cf-turnstile.*?data-sitekey="([^"]+)"',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                sitekey = match.group(1)
                print(f"[✓] Found Turnstile sitekey: {sitekey}")
                return sitekey
        
        # Check if we see turnstile in the page
        if 'turnstile' in html.lower() or 'cf-turnstile' in html.lower():
            print("[!] Turnstile detected but couldn't extract sitekey")
            # Save for inspection
            with open("turnstile_page.html", "w", encoding="utf-8") as f:
                f.write(html)
            print("[*] Saved page to turnstile_page.html for inspection")
        else:
            print("[!] No Turnstile detected on page")
            
        return None
        
    except Exception as e:
        print(f"[!] Error fetching page: {e}")
        return None


def solve_turnstile(url, sitekey, proxy):
    """Send Turnstile task to Solverify"""
    print(f"\n[*] Step 2: Sending Turnstile solve request to Solverify...")
    print(f"[*] URL: {url}")
    print(f"[*] Sitekey: {sitekey}")
    
    # Parse proxy
    proxy_clean = proxy.replace("http://", "").replace("https://", "")
    if "@" in proxy_clean:
        auth, host_port = proxy_clean.split("@")
        username, password = auth.split(":")
        host, port = host_port.split(":")
    else:
        parts = proxy_clean.split(":")
        host, port = parts[0], parts[1]
        username, password = "", ""

    payload = {
        "clientKey": CLIENT_KEY,
        "task": {
            "type": "turnstile",  # Turnstile solver!
            "websiteURL": url,
            "websiteKey": sitekey,
            "proxyType": "http",
            "proxyAddress": host,
            "proxyPort": str(port),
            "proxyLogin": username,
            "proxyPassword": password
        }
    }

    print(f"[*] Creating Turnstile task...")
    
    response = requests.post(CREATE_TASK_URL, json=payload)
    print(f"[*] Response: {response.status_code}")
    
    if response.status_code != 200:
        print(f"[!] Failed: {response.text}")
        return None

    data = response.json()
    print(f"[*] Response: {data}")
    
    if data.get("errorId") != 0:
        print(f"[!] API Error: {data}")
        return None

    task_id = data.get("taskId")
    print(f"[*] Task ID: {task_id}")
    print(f"[*] Polling for result...")

    poll_payload = {"clientKey": CLIENT_KEY, "taskId": task_id}

    start_time = time.time()
    attempt = 0
    while time.time() - start_time < 300:
        time.sleep(5)
        attempt += 1
        try:
            res = requests.post(GET_RESULT_URL, json=poll_payload)
            if res.status_code != 200:
                continue
                
            res_data = res.json()
            status = res_data.get("status", "unknown")
            print(f"[*] Poll {attempt}: {status}")
            
            if status == "completed":
                print(f"[✓] Turnstile solved!")
                return res_data.get("solution")
            
            if res_data.get("errorId") != 0:
                print(f"[!] Error: {res_data}")
                return None
                
        except Exception as e:
            print(f"[!] Poll error: {e}")
            
    print("[!] Timeout")
    return None


def fetch_with_turnstile_token(token, user_agent, proxy):
    """Use the Turnstile token to access Upwork"""
    print(f"\n[*] Step 3: Using Turnstile token to access Upwork...")
    print(f"[*] Token: {token[:50]}..." if token else "[!] No token!")
    
    proxies = {"http": proxy, "https": proxy}
    
    # The token needs to be submitted - this varies by implementation
    # Usually via cf-turnstile-response header or in form data
    headers = {
        "User-Agent": user_agent,
        "cf-turnstile-response": token,
    }
    
    try:
        response = curl_requests.get(
            TARGET_URL,
            headers=headers,
            proxies=proxies,
            impersonate="chrome",
            timeout=30
        )
        
        print(f"[*] Status: {response.status_code}")
        print(f"[*] Length: {len(response.text)} chars")
        
        if "job-tile" in response.text or "search-results" in response.text:
            print("[✓] SUCCESS! Got Upwork job data!")
            with open("turnstile_success.html", "w", encoding="utf-8") as f:
                f.write(response.text)
            return True
        elif "challenge" in response.text.lower():
            print("[!] Still getting challenge page")
            with open("turnstile_failed.html", "w", encoding="utf-8") as f:
                f.write(response.text)
            return False
        else:
            print("[?] Unknown response")
            with open("turnstile_unknown.html", "w", encoding="utf-8") as f:
                f.write(response.text)
            return False
            
    except Exception as e:
        print(f"[!] Error: {e}")
        return False


def try_with_cookies(solution, proxy):
    """Alternative: Try using cookies from solution"""
    print(f"\n[*] Alternative: Trying with cookies from solution...")
    
    cookies = solution.get("cookies", {})
    user_agent = solution.get("useragent", "Mozilla/5.0")
    token = solution.get("token", solution.get("cf_turnstile_response", ""))
    
    print(f"[*] Cookies: {list(cookies.keys())}")
    print(f"[*] Token present: {bool(token)}")
    
    proxies = {"http": proxy, "https": proxy}
    
    try:
        response = curl_requests.get(
            TARGET_URL,
            cookies=cookies,
            headers={"User-Agent": user_agent},
            proxies=proxies,
            impersonate="chrome",
            timeout=30
        )
        
        print(f"[*] Status: {response.status_code}")
        
        if "job-tile" in response.text:
            print("[✓] SUCCESS with cookies!")
            with open("turnstile_cookie_success.html", "w", encoding="utf-8") as f:
                f.write(response.text)
            return True
        else:
            print("[!] Cookies didn't work either")
            return False
            
    except Exception as e:
        print(f"[!] Error: {e}")
        return False


if __name__ == "__main__":
    print("=" * 60)
    print("SOLVERIFY TURNSTILE TEST FOR UPWORK")
    print("=" * 60)
    print()
    
    # Method 1: Try to extract sitekey and solve Turnstile
    sitekey = get_turnstile_sitekey(PROXY)
    
    if sitekey:
        solution = solve_turnstile(TARGET_URL, sitekey, PROXY)
        if solution:
            print(f"\n[*] Solution keys: {list(solution.keys())}")
            
            # Try with token
            token = solution.get("token", "")
            user_agent = solution.get("useragent", "Mozilla/5.0")
            
            success = fetch_with_turnstile_token(token, user_agent, PROXY)
            
            if not success:
                # Try with cookies as fallback
                try_with_cookies(solution, PROXY)
    else:
        print("\n[!] Could not extract Turnstile sitekey")
        print("[*] Upwork may use a different challenge method")
        
        # Try interstitial with turnstile type anyway using known CF sitekey
        print("\n[*] Trying with generic Cloudflare managed challenge...")
        
        # Use a known Cloudflare sitekey format
        solution = solve_turnstile(TARGET_URL, "0x4AAAAAAADnPIDROrmt1Wwj", PROXY)
        if solution:
            try_with_cookies(solution, PROXY)
    
    print("\n" + "=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)
