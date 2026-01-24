"""
Browser-based scanner for Upwork job monitoring.
Robust Cloudflare Bypass & Server-Ready Logic.
"""

import asyncio
import logging
import hashlib
import os
import random
import re
import time
import requests
import urllib.parse
import io
import base64
import json
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from bs4 import BeautifulSoup
from curl_cffi import requests as cffi_requests

# Force visible browser (works with Xvfb)
os.environ['DRISSIONPAGE_HEADLESS'] = 'False'

from DrissionPage import ChromiumPage, ChromiumOptions
from config import config
from database import db_manager

logger = logging.getLogger(__name__)

class JobData:
    def __init__(self, job_data: Dict[str, Any]):
        self.id = job_data.get('id')
        self.title = job_data.get('title', '').strip()
        self.link = job_data.get('link', '').strip()
        self.description = job_data.get('summary', job_data.get('description', '')).strip()
        self.published = job_data.get('published')
        self.tags = job_data.get('tags', [])
        self.budget = job_data.get('budget')
        # New filter fields
        self.budget_min = job_data.get('budget_min', 0)
        self.budget_max = job_data.get('budget_max', 0)
        self.job_type = job_data.get('job_type', 'Unknown')
        self.experience_level = job_data.get('experience_level', 'Unknown')
        self.posted = job_data.get('posted', '')

    def matches_keywords(self, keywords: List[str]) -> bool:
        keywords_lower = [kw.lower() for kw in keywords]
        text_to_check = f"{self.title} {self.description} {' '.join(self.tags)}".lower()
        return any(keyword in text_to_check for keyword in keywords_lower)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'title': self.title,
            'link': self.link,
            'description': self.description,
            'tags': self.tags,
            'budget': self.budget,
            'budget_min': self.budget_min,
            'budget_max': self.budget_max,
            'job_type': self.job_type,
            'experience_level': self.experience_level,
            'posted': self.posted,
            'published': self.published
        }

class UpworkScanner:
    def __init__(self):
        self.is_running = False
        self.last_scan_time = None
        self.job_callbacks: List[Callable] = []
        self.browser = None
        self.proxies = self._load_proxies()
        
        # Track bypass server health
        self._last_successful_proxy: Optional[str] = None
        
        # Round-robin bypass server management
        self._bypass_urls = config.CLOUDFLARE_BYPASS_URLS.copy()
        self._current_bypass_index = 0
        self._bypass_failures: Dict[str, int] = {url: 0 for url in self._bypass_urls}
        self._consecutive_total_failures = 0
        self._max_failures_before_restart = 2  # Restart container after 2 consecutive failures
        
        logger.info(f"Initialized with {len(self._bypass_urls)} bypass servers: {self._bypass_urls}")
        
    def _load_proxies(self) -> List[str]:
        """Load and format proxies from file."""
        proxies = []
        try:
            proxy_file = "Webshare residential proxies.txt"
            if os.path.exists(proxy_file):
                with open(proxy_file, 'r') as f:
                    for line in f:
                        if ':' in line:
                            parts = line.strip().split(':')
                            if len(parts) == 4:
                                # Format: host:port:user:pass
                                host, port, user, password = parts
                                # Convert to: http://user:pass@host:port
                                proxies.append(f"http://{user}:{password}@{host}:{port}")
                logger.info(f"Loaded {len(proxies)} proxies from {proxy_file}")
            else:
                logger.warning(f"Proxy file {proxy_file} not found")
        except Exception as e:
            logger.error(f"Error loading proxies: {e}")
        return proxies

    def _get_random_proxy(self) -> Optional[str]:
        """Get a random proxy from the loaded list."""
        if self.proxies:
            return random.choice(self.proxies)
        # Fallback to config proxy if file list is empty
        return config.PROXY_URL if config.PROXY_ENABLED else None

    def _get_next_bypass_url(self) -> str:
        """Get the next bypass server URL using round-robin."""
        if not self._bypass_urls:
            return config.CLOUDFLARE_BYPASS_URL
        
        url = self._bypass_urls[self._current_bypass_index]
        self._current_bypass_index = (self._current_bypass_index + 1) % len(self._bypass_urls)
        return url
    
    def _mark_bypass_success(self, url: str):
        """Mark a bypass server as successful, reset its failure count."""
        self._bypass_failures[url] = 0
        self._consecutive_total_failures = 0
        logger.info(f"Bypass server {url} succeeded, failure count reset")
    
    def _mark_bypass_failure(self, url: str):
        """Mark a bypass server as failed, trigger restart if needed."""
        self._bypass_failures[url] = self._bypass_failures.get(url, 0) + 1
        self._consecutive_total_failures += 1
        
        logger.warning(f"Bypass server {url} failed (count: {self._bypass_failures[url]}, total consecutive: {self._consecutive_total_failures})")
        
        # Check if this specific server needs restart
        if self._bypass_failures[url] >= self._max_failures_before_restart:
            self._restart_bypass_container(url)
    
    def _restart_bypass_container(self, url: str):
        """Restart a specific bypass server container."""
        try:
            # Extract container number from URL (e.g., http://localhost:8001 -> 1)
            port = url.split(':')[-1].replace('/', '')
            container_num = int(port) - 8000  # 8001->1, 8002->2, 8003->3
            container_name = f"cloudflare_bypass_{container_num}"
            
            logger.info(f"Restarting container {container_name} due to {self._bypass_failures[url]} consecutive failures...")
            
            # Get a new random proxy for the container
            new_proxy = self._get_random_proxy()
            
            # Run docker restart in background (non-blocking)
            import subprocess
            if new_proxy:
                # Stop, remove, and recreate with new proxy
                cmd = f'docker stop {container_name} && docker rm {container_name} && docker run -d -p {port}:8000 --name {container_name} -e PROXY_URL="{new_proxy}" --restart unless-stopped ghcr.io/sarperavci/cloudflarebypassforscraping:latest'
            else:
                cmd = f'docker restart {container_name}'
            
            subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Reset failure count for this server
            self._bypass_failures[url] = 0
            logger.info(f"Container {container_name} restart initiated with fresh proxy")
            
        except Exception as e:
            logger.error(f"Failed to restart bypass container: {e}")

    def add_job_callback(self, callback: Callable):
        self.job_callbacks.append(callback)

    async def start_scanning(self):
        if not config.SCRAPING_ENABLED:
            logger.info("Scraping disabled via config.")
            return

        self.is_running = True
        logger.info("Starting Upwork scanner (Browser + Residential Proxy)...")

        while self.is_running:
            try:
                # Scan
                jobs = await asyncio.to_thread(self._scan_jobs_blocking)
                
                # Process
                if jobs:
                    await self._process_found_jobs(jobs)
                
                self.last_scan_time = datetime.now()
                await asyncio.sleep(config.SCAN_INTERVAL_SECONDS)

            except Exception as e:
                logger.error(f"Scanner Loop Error: {e}")
                self.browser = None
                await asyncio.sleep(config.RETRY_DELAY_SECONDS)

        await asyncio.to_thread(self._cleanup_browser_blocking)

    async def _process_found_jobs(self, jobs: List[Dict]):
        new_jobs = []
        for job_data in jobs:
            if not await db_manager.is_job_seen(job_data['id']):
                job_obj = JobData(job_data)
                new_jobs.append(job_obj)
                await db_manager.mark_job_seen(job_obj.id, job_obj.title, job_obj.link)

        if new_jobs:
            logger.info(f"Found {len(new_jobs)} new jobs")
            for callback in self.job_callbacks:
                try:
                    await callback(new_jobs)
                except Exception as e:
                    logger.error(f"Callback error: {e}")

    # ==========================================
    # BLOCKING METHODS (Thread Safe)
    # ==========================================

    def _is_browser_alive(self):
        try:
            return self.browser and self.browser.process_id is not None
        except:
            return False

    def _init_browser_blocking(self):
        logger.info("Initializing Stealth Browser with Proxy...")
        try:
            # Persistent Profile Path
            profile_path = os.path.join(os.getcwd(), 'browser_profile')
            
            co = ChromiumOptions()
            co.set_argument('--no-sandbox')
            co.set_argument(f'--user-data-dir={profile_path}')
            
            # Anti-Detection Flags
            co.set_argument('--disable-blink-features=AutomationControlled')
            co.set_argument('--start-maximized')
            co.set_argument('--mute-audio')
            
            # Proxy Configuration (Extension Method)
            # DrissionPage cannot handle auth-proxies directly via arguments.
            # We must create a temporary extension to inject auth.
            proxy_url = config.PROXY_URL
            if config.PROXY_ENABLED and proxy_url:
                logger.info("Configuring browser with proxy (Extension Method)...")
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(proxy_url)
                    
                    if parsed.username and parsed.password:
                        # Auth Proxy: Create extension
                        manifest_json = """
                        {
                            "version": "1.0.0",
                            "manifest_version": 2,
                            "name": "Chrome Proxy",
                            "permissions": [
                                "proxy",
                                "tabs",
                                "unlimitedStorage",
                                "storage",
                                "<all_urls>",
                                "webRequest",
                                "webRequestBlocking"
                            ],
                            "background": {
                                "scripts": ["background.js"]
                            },
                            "minimum_chrome_version":"22.0.0"
                        }
                        """
                        
                        background_js = f"""
                        var config = {{
                                mode: "fixed_servers",
                                rules: {{
                                  singleProxy: {{
                                    scheme: "{parsed.scheme}",
                                    host: "{parsed.hostname}",
                                    port: parseInt({parsed.port})
                                  }},
                                  bypassList: ["localhost"]
                                }}
                              }};

                        chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});

                        function callbackFn(details) {{
                            return {{
                                authCredentials: {{
                                    username: "{parsed.username}",
                                    password: "{parsed.password}"
                                }}
                            }};
                        }}

                        chrome.webRequest.onAuthRequired.addListener(
                                    callbackFn,
                                    {{urls: ["<all_urls>"]}},
                                    ['blocking']
                        );
                        """
                        
                        plugin_path = os.path.join(os.getcwd(), 'proxy_auth_plugin')
                        if not os.path.exists(plugin_path):
                            os.makedirs(plugin_path)
                        
                        with open(os.path.join(plugin_path, "manifest.json"), "w") as f:
                            f.write(manifest_json)
                        with open(os.path.join(plugin_path, "background.js"), "w") as f:
                            f.write(background_js)
                            
                        co.add_extension(plugin_path)
                        logger.info(f"Proxy extension created at {plugin_path}")
                        
                    else:
                        co.set_proxy(proxy_url)
                        
                except Exception as e:
                    logger.error(f"Failed to configure proxy extension: {e}")
                    co.set_proxy(proxy_url)
            
            # CRITICAL: AWS often needs this to handle shared memory
            co.set_argument('--disable-dev-shm-usage')

            self.browser = ChromiumPage(addr_or_opts=co)
            
            # Set a normal viewport size
            self.browser.set.window.size(1920, 1080)
            
            logger.info("Browser initialized.")

        except Exception as e:
            logger.error(f"Failed to init browser: {e}")
            raise e

    def _cleanup_browser_blocking(self):
        try:
            if self.browser:
                self.browser.quit()
        except:
            pass

    def _get_html_from_brightdata(self, url: str) -> Optional[tuple]:
        """
        Get HTML content from BrightData Unlocker API.
        Returns a tuple of (html_body, cookies_dict, user_agent) if successful, None otherwise.
        This is the primary method - we use BrightData's HTML directly instead of browser navigation.
        """
        if not config.BRIGHTDATA_UNLOCKER_ENABLED or not config.BRIGHTDATA_UNLOCKER_API_KEY:
            logger.warning("BrightData Unlocker not enabled or API key missing")
            return None
        
        try:
            # BrightData Unlocker API endpoint (correct format from documentation)
            unlocker_url = "https://api.brightdata.com/request"
            
            headers = {
                'Authorization': f'Bearer {config.BRIGHTDATA_UNLOCKER_API_KEY}',
                'Content-Type': 'application/json'
            }
            
            # BrightData Unlocker API payload (correct format from documentation)
            payload = {
                'zone': config.BRIGHTDATA_UNLOCKER_ZONE,  # Zone must be configured in BrightData dashboard
                'url': url,
                'format': 'json',  # Get structured response with cookies
                'method': 'GET',
                'country': 'us',  # Optional: specify country
            }
            
            logger.info(f"Requesting Cloudflare bypass from BrightData Unlocker (zone: {config.BRIGHTDATA_UNLOCKER_ZONE}) for {url}...")
            try:
                response = requests.post(unlocker_url, json=payload, headers=headers, timeout=180)
            except requests.exceptions.Timeout:
                logger.warning("BrightData Unlocker request timed out after 180 seconds")
                return None
            except requests.exceptions.RequestException as e:
                logger.warning(f"BrightData Unlocker request failed: {e}")
                return None
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    logger.info(f"BrightData response received. Keys: {list(data.keys())}")
                    
                    # BrightData returns: {status_code, headers, body}
                    # Cookies are in the headers field
                    headers = data.get('headers', {})
                    if isinstance(headers, str):
                        # Headers might be a string, try to parse it
                        import json
                        try:
                            headers = json.loads(headers)
                        except:
                            headers = {}
                    
                    # Extract cookies from Set-Cookie header
                    cookies_dict = {}
                    set_cookie = headers.get('Set-Cookie') or headers.get('set-cookie') or headers.get('SetCookie')
                    
                    if set_cookie:
                        # Set-Cookie can be a string or list
                        if isinstance(set_cookie, list):
                            cookie_strings = set_cookie
                        else:
                            cookie_strings = [set_cookie]
                        
                        for cookie_str in cookie_strings:
                            # Parse "name=value; domain=...; path=..."
                            parts = cookie_str.split(';')[0].split('=', 1)
                            if len(parts) == 2:
                                cookies_dict[parts[0].strip()] = parts[1].strip()
                    
                    # Also check for Cookie header (already set cookies)
                    cookie_header = headers.get('Cookie') or headers.get('cookie')
                    if cookie_header:
                        for cookie_pair in cookie_header.split(';'):
                            parts = cookie_pair.strip().split('=', 1)
                            if len(parts) == 2:
                                cookies_dict[parts[0].strip()] = parts[1].strip()
                    
                    # Extract user agent
                    user_agent = (
                        headers.get('User-Agent') or 
                        headers.get('user-agent') or
                        data.get('user_agent') or 
                        data.get('userAgent') or
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    )
                    
                    # Extract HTML body
                    html_body = data.get('body', '')
                    if isinstance(html_body, str) and len(html_body) > 100:
                        logger.info(f"Got HTML body from BrightData ({len(html_body)} chars). Extracted {len(cookies_dict)} cookies.")
                        return (html_body, cookies_dict, user_agent)
                    else:
                        logger.warning("BrightData returned empty or invalid HTML body")
                        return None
                        
                except ValueError as e:
                    # Response is not JSON
                    logger.warning(f"BrightData returned non-JSON response: {e}")
                    # Try to extract cookies from headers
                    cookies_dict = {}
                    if 'Set-Cookie' in response.headers:
                        cookie_header = response.headers.get('Set-Cookie', '')
                        for cookie_str in cookie_header.split(','):
                            parts = cookie_str.split(';')[0].split('=', 1)
                            if len(parts) == 2:
                                cookies_dict[parts[0].strip()] = parts[1].strip()
                    
                    # Try to get HTML from response text if not in JSON
                    html_body = response.text if response.text and len(response.text) > 100 else ''
                    if html_body:
                        logger.info(f"Got HTML from BrightData response text ({len(html_body)} chars)")
                        return (html_body, cookies_dict, 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
                    return None
            else:
                error_msg = response.text[:500] if response.text else f"Status {response.status_code}"
                logger.warning(f"BrightData Unlocker returned status {response.status_code}: {error_msg}")
                return None
                
        except requests.exceptions.RequestException as e:
            logger.warning(f"Failed to connect to BrightData Unlocker: {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting cookies from BrightData Unlocker: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    def _get_html_from_bypass_server(self, url: str) -> Optional[str]:
        """
        Get HTML from bypass servers using round-robin with auto-restart.
        Cycles through multiple bypass servers for better reliability.
        """
        if not config.CLOUDFLARE_BYPASS_ENABLED:
            return None
        
        num_servers = len(self._bypass_urls)
        max_attempts_per_server = 3  # Try each server up to 3 times
        total_attempts = num_servers * max_attempts_per_server
        
        logger.info(f"=== Round-Robin Bypass: {num_servers} servers, up to {total_attempts} attempts ===")
        
        for attempt in range(1, total_attempts + 1):
            # Get next server in round-robin
            bypass_base_url = self._get_next_bypass_url()
            bypass_endpoint = f"{bypass_base_url}/html"
            
            try:
                params = {'url': url, 'retries': 3}
                
                # Add a random proxy to the request
                proxy = self._get_random_proxy()
                if proxy:
                    params['proxy'] = proxy
                    proxy_masked = proxy.split('@')[1] if '@' in proxy else proxy
                    logger.info(f"Attempt {attempt}/{total_attempts}: Server {bypass_base_url}, proxy ...@{proxy_masked}")
                else:
                    logger.info(f"Attempt {attempt}/{total_attempts}: Server {bypass_base_url}, no proxy")
                
                response = requests.get(bypass_endpoint, params=params, timeout=120)
                
                if response.status_code == 200:
                    html = response.text
                    if html and len(html) > 1000:
                        logger.info(f"Got {len(html)} chars of HTML from {bypass_base_url}")
                        
                        # Mark success
                        self._mark_bypass_success(bypass_base_url)
                        if proxy:
                            self._last_successful_proxy = proxy
                        
                        return html
                    else:
                        logger.warning(f"Server {bypass_base_url} returned small/empty response")
                        self._mark_bypass_failure(bypass_base_url)
                else:
                    logger.warning(f"Server {bypass_base_url} returned status {response.status_code}")
                    self._mark_bypass_failure(bypass_base_url)
                    
            except requests.exceptions.Timeout:
                logger.warning(f"Server {bypass_base_url} timed out")
                self._mark_bypass_failure(bypass_base_url)
            except requests.exceptions.RequestException as e:
                logger.warning(f"Server {bypass_base_url} connection error: {e}")
                self._mark_bypass_failure(bypass_base_url)
            except Exception as e:
                logger.error(f"Server {bypass_base_url} error: {e}")
                self._mark_bypass_failure(bypass_base_url)
            
            # Short wait before trying next server
            if attempt < total_attempts:
                wait_time = 3  # Quick rotation between servers
                time.sleep(wait_time)
        
        logger.error(f"All bypass servers failed after {total_attempts} attempts")
        return None

    def _solve_with_solverify(self, url: str) -> Optional[Dict]:
        """
        Solve Cloudflare Interstitial using Solverify API.
        Returns solution dict with cookies and useragent, or None on failure.
        Cost: $0.20 per 1000 solves = $0.0002 per solve
        """
        if not config.SOLVERIFY_ENABLED or not config.SOLVERIFY_API_KEY:
            return None
        
        CREATE_TASK_URL = "https://solver.solverify.net/createTask"
        GET_RESULT_URL = "https://solver.solverify.net/getTaskResult"
        
        # Get a random proxy
        proxy = self._get_random_proxy()
        if not proxy:
            logger.error("Solverify requires a proxy but none available")
            return None
        
        # Parse proxy: http://user:pass@host:port
        try:
            proxy_clean = proxy.replace("http://", "").replace("https://", "")
            proxy_parts = proxy_clean.split("@")
            if len(proxy_parts) == 2:
                auth, host_port = proxy_parts
                username, password = auth.split(":")
                host, port = host_port.split(":")
            else:
                parts = proxy_parts[0].split(":")
                host = parts[0]
                port = parts[1]
                username = parts[2] if len(parts) > 2 else ""
                password = parts[3] if len(parts) > 3 else ""
        except Exception as e:
            logger.error(f"Failed to parse proxy for Solverify: {e}")
            return None
        
        logger.info(f"Solverify: Creating task for {url} via proxy {host}:{port}")
        
        # Create task
        payload = {
            "clientKey": config.SOLVERIFY_API_KEY,
            "task": {
                "type": "interstitial",
                "websiteURL": url,
                "proxyType": "http",
                "proxyAddress": host,
                "proxyPort": str(port),
                "proxyLogin": username,
                "proxyPassword": password
            }
        }
        
        try:
            response = requests.post(CREATE_TASK_URL, json=payload, timeout=60)  # Increased timeout
            if response.status_code != 200:
                logger.error(f"Solverify create task failed: {response.status_code} - {response.text}")
                return None
            
            data = response.json()
            if data.get("errorId") != 0:
                logger.error(f"Solverify API error: {data}")
                return None
            
            task_id = data.get("taskId")
            logger.info(f"Solverify task created: {task_id}")
            
        except Exception as e:
            logger.error(f"Solverify create task error: {e}")
            return None
        
        # Poll for result
        poll_payload = {
            "clientKey": config.SOLVERIFY_API_KEY,
            "taskId": task_id
        }
        
        start_time = time.time()
        timeout = 180  # 3 minutes max
        
        while time.time() - start_time < timeout:
            time.sleep(5)
            try:
                res = requests.post(GET_RESULT_URL, json=poll_payload, timeout=30)
                if res.status_code != 200:
                    continue
                
                res_data = res.json()
                status = res_data.get("status")
                
                if status == "completed":
                    solution = res_data.get("solution", {})
                    cookies = solution.get("cookies", {})
                    user_agent = solution.get("useragent", "")
                    
                    if "cf_clearance" in cookies:
                        logger.info(f"Solverify SUCCESS! Got cf_clearance cookie in {int(time.time() - start_time)}s")
                        # Store the proxy used for this solution
                        solution["_proxy"] = proxy
                        return solution
                    else:
                        logger.warning("Solverify completed but no cf_clearance cookie")
                        return None
                
                if res_data.get("errorId") != 0:
                    logger.error(f"Solverify polling error: {res_data}")
                    return None
                    
                logger.debug(f"Solverify status: {status}, waiting...")
                
            except Exception as e:
                logger.warning(f"Solverify polling error: {e}")
        
        logger.error(f"Solverify timed out after {timeout}s")
        return None

    def _get_html_with_solverify(self, url: str) -> Optional[str]:
        """
        Get HTML using Solverify to solve Cloudflare, then curl_cffi to fetch.
        This is the cheapest and most reliable method.
        """
        if not config.SOLVERIFY_ENABLED:
            return None
        
        logger.info("=== Attempting Solverify + curl_cffi ===")
        
        # Solve Cloudflare
        solution = self._solve_with_solverify(url)
        if not solution:
            return None
        
        cookies = solution.get("cookies", {})
        user_agent = solution.get("useragent", "")
        proxy = solution.get("_proxy")
        
        # Use curl_cffi to fetch with the solved cookies
        try:
            proxies = {"http": proxy, "https": proxy} if proxy else None
            
            logger.info(f"Fetching with cf_clearance cookie via curl_cffi...")
            
            response = cffi_requests.get(
                url,
                cookies=cookies,
                headers={"User-Agent": user_agent},
                proxies=proxies,
                impersonate="chrome",
                timeout=30
            )
            
            if response.status_code == 200:
                html = response.text
                
                # Check if we got past Cloudflare
                if "Checking your browser" in html or "<title>Just a moment" in html:
                    logger.warning("Solverify: Still got Cloudflare challenge page")
                    return None
                
                logger.info(f"Solverify SUCCESS! Got {len(html)} chars of HTML")
                return html
            else:
                logger.warning(f"Solverify fetch failed: status {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Solverify curl_cffi error: {e}")
            return None

    def _get_html_from_scrapeless(self, url: str) -> Optional[str]:
        """
        Get HTML from Scrapeless API.
        Reference implementation:
        {
            "actor": "unlocker.webunlocker",
            "proxy": { "country": "ANY" },
            "input": {
                "url": "...",
                "method": "GET",
                "redirect": False,
                "jsRender": {"enabled":false,"headless":true,...}
            }
        }
        """
        if not config.SCRAPELESS_API_KEY:
             logger.warning("Scrapeless API key missing")
             return None

        try:
            host = "api.scrapeless.com"
            api_url = f"https://{host}/api/v1/unlocker/request"
            
            headers = {
                "x-api-token": config.SCRAPELESS_API_KEY
            }
            
            json_payload = {
                "actor": "unlocker.webunlocker",
                "input": {
                    "url": url,
                    "method": "GET",
                    "redirect": True,
                    "jsRender": {
                        "headless": False,
                        "waitUntil": "networkidle0", # Wait for ALL network traffic to stop
                        "wait": 8000, # Longer wait for Turnstile
                        "stealth": True, # Explicitly enable stealth
                        "args": ["--window-size=1920,1080"] # Force desktop resolution
                    }
                },
                "proxy": {
                    "country": "US"
                }
            }
            
            logger.info(f"Requesting {url} via Scrapeless (Deep Stealth Mode)...")
            response = requests.post(api_url, headers=headers, json=json_payload, timeout=90)
            
            if response.status_code != 200:
                logger.warning(f"Scrapeless returned status {response.status_code}: {response.text}")
                return None
            
            # Parse JSON response
            try:
                data = response.json()
                html_content = data.get('data', '')
                
                # Check if it's a Challenge page
                if "Challenge - Upwork" in html_content or "challenge-platform" in html_content or "Enable JavaScript and cookies" in html_content:
                    logger.warning("Scrapeless returned a Challenge page (Not fully bypassed). Triggering fallback...")
                    # Return None to trigger fallback to Browser + Solverify
                    return None
                
                logger.info(f"Scrapeless success! Got {len(html_content)} chars of HTML")
                
                # DEBUG: Check for job keywords
                if "job-tile" in html_content or "JobTile" in html_content:
                    logger.info("DEBUG: Found 'job-tile' in HTML! Parsing should succeed.")
                else:
                    logger.info("DEBUG: 'job-tile' NOT found in HTML.")
                    # Save to file for inspection
                    with open("debug_scrapeless_response.html", "w", encoding="utf-8") as f:
                        f.write(html_content)
                    logger.info(f"Saved {len(html_content)} chars to debug_scrapeless_response.html")
                
                return html_content
                
            except Exception as e:
                logger.error(f"Failed to parse Scrapeless JSON: {e}")
                # Fallback: maybe it returned raw HTML?
                if "<html" in response.text:
                    return response.text
                return None
            
        except Exception as e:
            logger.error(f"Scrapeless request failed: {e}")
            return None

    def _inject_cookies_into_browser(self, cookies: Dict[str, str], url: str) -> bool:
        """
        Inject cookies into the browser session.
        Navigate to base domain first to set cookies properly.
        """
        try:
            if not self.browser:
                return False
            
            # Parse the domain from URL
            parsed_url = urllib.parse.urlparse(url)
            domain = parsed_url.netloc
            base_url = f"{parsed_url.scheme}://{domain}"
            
            # Navigate to base domain first (required for setting cookies)
            try:
                self.browser.get(base_url, timeout=5)
                time.sleep(1)  # Brief wait for page load
            except:
                pass  # Continue even if navigation fails
            
            # Set cookies using DrissionPage's cookie setting
            cookies_set = 0
            for name, value in cookies.items():
                try:
                    # Use DrissionPage's cookie setting method
                    cookie_obj = {
                        'name': name,
                        'value': value,
                        'domain': domain,
                        'path': '/',
                        'secure': True,
                        'sameSite': 'None'
                    }
                    self.browser.set.cookies(cookie_obj)
                    cookies_set += 1
                except Exception as e:
                    logger.debug(f"Failed to set cookie {name} via DrissionPage: {e}")
                    # Fallback: use JavaScript (requires page to be loaded)
                    try:
                        # Escape value for JavaScript
                        value_escaped = value.replace("'", "\\'").replace('"', '\\"')
                        self.browser.run_js(f"""
                            document.cookie = '{name}={value_escaped}; domain={domain}; path=/; SameSite=None; Secure';
                        """)
                        cookies_set += 1
                    except Exception as e2:
                        logger.debug(f"Failed to set cookie {name} via JavaScript: {e2}")
            
            logger.info(f"Injected {cookies_set}/{len(cookies)} cookies into browser")
            return cookies_set > 0
            
        except Exception as e:
            logger.error(f"Failed to inject cookies: {e}")
            return False

    def _solve_cloudflare_with_2captcha(self, page_url: str) -> Optional[str]:
        """
        Solve Cloudflare Turnstile using 2captcha API.
        Returns the token if successful, None otherwise.
        """
        if not config.CAPTCHA_ENABLED or not config.CAPTCHA_API_KEY:
            return None
        
        try:
            # Extract site key from the page
            site_key = None
            
            # Method 1: Look for data-sitekey attribute
            try:
                site_key_elements = self.browser.eles('css:[data-sitekey]')
                if site_key_elements:
                    site_key = site_key_elements[0].attr('data-sitekey')
                    logger.info(f"Found site key in data-sitekey: {site_key[:20]}...")
            except:
                pass
            
            # Method 2: Extract from iframe src (most reliable for Turnstile)
            if not site_key:
                try:
                    iframes = self.browser.eles('tag:iframe')
                    for iframe in iframes:
                        src = iframe.attr('src') or ''
                        # Cloudflare Turnstile iframe URLs contain sitekey
                        if 'challenges.cloudflare.com' in src or 'turnstile' in src.lower() or 'cloudflare' in src.lower():
                            # Extract sitekey from URL parameters (multiple patterns)
                            patterns = [
                                r'sitekey=([^&"\']+)',
                                r'k=([^&"\']+)',  # Sometimes abbreviated
                                r'data-sitekey=([^&"\']+)',
                            ]
                            for pattern in patterns:
                                match = re.search(pattern, src, re.IGNORECASE)
                                if match:
                                    potential_key = match.group(1)
                                    # Decode URL encoding if needed
                                    potential_key = urllib.parse.unquote(potential_key)
                                    # Validate it looks like a site key
                                    if len(potential_key) >= 20 and re.match(r'^[a-zA-Z0-9_-]+$', potential_key):
                                        site_key = potential_key
                                        logger.info(f"Found site key in iframe URL: {site_key[:20]}...")
                                        break
                            if site_key:
                                break
                except Exception as e:
                    logger.debug(f"Failed to extract from iframe: {e}")
            
            # Method 3: Extract from page HTML with more patterns
            if not site_key:
                try:
                    html = self.browser.html
                    # Look for sitekey in various patterns
                    patterns = [
                        r'sitekey["\']?\s*[:=]\s*["\']([^"\']+)["\']',
                        r'data-sitekey=["\']([^"\']+)["\']',
                        r'cf-turnstile["\'][^>]*data-sitekey=["\']([^"\']+)["\']',
                        r'"sitekey"\s*:\s*"([^"]+)"',
                        r"'sitekey'\s*:\s*'([^']+)'",
                        r'sitekey=([a-zA-Z0-9_-]{20,})',  # Site keys are typically 20+ chars
                    ]
                    for pattern in patterns:
                        match = re.search(pattern, html, re.IGNORECASE)
                        if match:
                            potential_key = match.group(1)
                            # Validate it looks like a site key (alphanumeric, 20+ chars)
                            if len(potential_key) >= 20 and re.match(r'^[a-zA-Z0-9_-]+$', potential_key):
                                site_key = potential_key
                                logger.info(f"Found site key via regex: {site_key[:20]}...")
                                break
                except Exception as e:
                    logger.debug(f"Failed to extract site key from HTML: {e}")
            
            # Method 4: Try JavaScript evaluation
            if not site_key:
                try:
                    js_result = self.browser.run_js("""
                        (function() {
                            // Check for Turnstile widget
                            var widgets = document.querySelectorAll('[data-sitekey], [class*="turnstile"]');
                            if (widgets.length > 0) {
                                return widgets[0].getAttribute('data-sitekey');
                            }
                            // Check window variables
                            if (window.turnstile && window.turnstile.sitekey) {
                                return window.turnstile.sitekey;
                            }
                            // Check for sitekey in script tags
                            var scripts = document.querySelectorAll('script');
                            for (var i = 0; i < scripts.length; i++) {
                                var content = scripts[i].textContent || scripts[i].innerHTML;
                                var match = content.match(/sitekey["\']?\s*[:=]\s*["\']([^"\']+)["\']/i);
                                if (match) return match[1];
                            }
                            return null;
                        })();
                    """)
                    if js_result and len(js_result) >= 20:
                        site_key = js_result
                        logger.info(f"Found site key via JavaScript: {site_key[:20]}...")
                except Exception as e:
                    logger.debug(f"Failed to extract via JavaScript: {e}")
            
            # If no site key found, try Cloudflare method (doesn't require site key)
            if not site_key:
                logger.warning("Could not extract Cloudflare site key. Trying Cloudflare method without site key...")
                # Use 2captcha's "cloudflare" method which works with page tokens
                try:
                    # Get page token from Cloudflare challenge
                    page_token = None
                    html = self.browser.html
                    # Look for cf_clearance cookie or page token
                    token_patterns = [
                        r'__cf_bm=([^;]+)',
                        r'cf_clearance=([^;]+)',
                        r'data-ray=([^"\']+)',
                    ]
                    for pattern in token_patterns:
                        match = re.search(pattern, html)
                        if match:
                            page_token = match.group(1)
                            break
                    
                    # Get cookies from browser
                    cookies_dict = {}
                    try:
                        # DrissionPage cookies
                        browser_cookies = self.browser.cookies()
                        if browser_cookies:
                            for cookie in browser_cookies:
                                cookies_dict[cookie.get('name', '')] = cookie.get('value', '')
                        # Also try to get cookies via JavaScript
                        js_cookies = self.browser.run_js("document.cookie")
                        if js_cookies:
                            for cookie_pair in js_cookies.split(';'):
                                if '=' in cookie_pair:
                                    name, value = cookie_pair.strip().split('=', 1)
                                    cookies_dict[name] = value
                    except Exception as e:
                        logger.debug(f"Failed to extract cookies: {e}")
                    
                    # Format cookies string
                    cookies_str = '; '.join([f"{k}={v}" for k, v in cookies_dict.items()])
                    
                    # Get page HTML to send to 2captcha
                    page_html = self.browser.html
                    if not page_html or len(page_html) < 100:
                        # Fallback: try to get HTML via JavaScript
                        try:
                            page_html = self.browser.run_js("return document.documentElement.outerHTML;")
                        except:
                            page_html = self.browser.html
                    
                    # Try cloudflare method (works for managed challenges)
                    submit_url = "https://2captcha.com/in.php"
                    submit_params = {
                        'key': config.CAPTCHA_API_KEY,
                        'method': 'cloudflare',
                        'pageurl': page_url,
                        'json': 1
                    }
                    if cookies_str:
                        submit_params['cookies'] = cookies_str
                    if page_token:
                        submit_params['token'] = page_token
                    
                    # Send page HTML to 2captcha
                    # Try multiple file formats - 2captcha might expect specific format
                    files = None
                    if page_html:
                        # Try different file formats
                        formats_to_try = [
                            ('page.txt', 'text/plain'),
                            ('page', 'text/html'),  # No extension
                            ('captcha.html', 'text/html'),
                        ]
                        
                        for filename, content_type in formats_to_try:
                            try:
                                html_file = io.BytesIO(page_html.encode('utf-8'))
                                files = {'file': (filename, html_file, content_type)}
                                logger.info(f"Submitting to 2captcha using Cloudflare method (file: {filename}, HTML: {len(page_html)} chars, cookies: {len(cookies_str)} chars)...")
                                
                                response = requests.post(submit_url, data=submit_params, files=files, timeout=60)
                                result = response.json()
                                
                                # If it worked, break out of the loop
                                if result.get('status') == 1:
                                    break
                                elif 'WRONG_FILE' not in result.get('request', ''):
                                    # Different error, might be progress
                                    break
                                else:
                                    # Wrong file format, try next
                                    files = None
                                    continue
                            except Exception as e:
                                logger.debug(f"Failed with {filename}: {e}")
                                files = None
                                continue
                        
                        if not files:
                            logger.warning("All file format attempts failed, trying without file...")
                            response = requests.post(submit_url, data=submit_params, timeout=60)
                            result = response.json()
                        # If files was set, result is already defined from the loop
                    else:
                        logger.warning("No page HTML available to send")
                        response = requests.post(submit_url, data=submit_params, timeout=60)
                        result = response.json()
                    
                    if result.get('status') != 1:
                        error_msg = result.get('request', 'Unknown error')
                        logger.error(f"2captcha Cloudflare method failed: {error_msg}")
                        return None
                    
                    task_id = result.get('request')
                    logger.info(f"2captcha Cloudflare task created: {task_id}. Waiting for solution...")
                    
                    # Poll for result (same as Turnstile method)
                    max_attempts = 24
                    for attempt in range(max_attempts):
                        time.sleep(5)
                        
                        result_url = "https://2captcha.com/res.php"
                        result_params = {
                            'key': config.CAPTCHA_API_KEY,
                            'action': 'get',
                            'id': task_id,
                            'json': 1
                        }
                        
                        result_response = requests.get(result_url, params=result_params, timeout=30)
                        result_data = result_response.json()
                        
                        if result_data.get('status') == 1:
                            token = result_data.get('request')
                            logger.info("2captcha solved Cloudflare challenge (Cloudflare method)!")
                            return token
                        elif result_data.get('request') == 'CAPCHA_NOT_READY':
                            logger.debug(f"2captcha still processing... (attempt {attempt + 1}/{max_attempts})")
                            continue
                        else:
                            error_msg = result_data.get('request', 'Unknown error')
                            logger.error(f"2captcha error: {error_msg}")
                            return None
                    
                    logger.warning("2captcha Cloudflare method timeout")
                    return None
                    
                except Exception as e:
                    logger.error(f"2captcha Cloudflare method error: {e}")
                    return None
            
            # Continue with Turnstile method if site key was found
            
            logger.info(f"Submitting Cloudflare challenge to 2captcha (site key: {site_key[:20]}...)")
            
            # Submit to 2captcha
            submit_url = "https://2captcha.com/in.php"
            submit_params = {
                'key': config.CAPTCHA_API_KEY,
                'method': 'turnstile',
                'sitekey': site_key,
                'pageurl': page_url,
                'json': 1
            }
            
            response = requests.post(submit_url, data=submit_params, timeout=30)
            result = response.json()
            
            if result.get('status') != 1:
                error_msg = result.get('request', 'Unknown error')
                logger.error(f"2captcha submission failed: {error_msg}")
                return None
            
            task_id = result.get('request')
            logger.info(f"2captcha task created: {task_id}. Waiting for solution...")
            
            # Poll for result (max 2 minutes, check every 5 seconds)
            max_attempts = 24
            for attempt in range(max_attempts):
                time.sleep(5)
                
                result_url = "https://2captcha.com/res.php"
                result_params = {
                    'key': config.CAPTCHA_API_KEY,
                    'action': 'get',
                    'id': task_id,
                    'json': 1
                }
                
                result_response = requests.get(result_url, params=result_params, timeout=30)
                result_data = result_response.json()
                
                if result_data.get('status') == 1:
                    token = result_data.get('request')
                    logger.info("2captcha solved Cloudflare challenge!")
                    return token
                elif result_data.get('request') == 'CAPCHA_NOT_READY':
                    logger.debug(f"2captcha still processing... (attempt {attempt + 1}/{max_attempts})")
                    continue
                else:
                    error_msg = result_data.get('request', 'Unknown error')
                    logger.error(f"2captcha error: {error_msg}")
                    return None
            
            logger.warning("2captcha timeout: solution not ready after 2 minutes")
            return None
            
        except Exception as e:
            logger.error(f"2captcha integration error: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    def _inject_turnstile_token(self, token: str) -> bool:
        """
        Inject the 2captcha token into the page to solve Cloudflare.
        """
        try:
            # Inject token using JavaScript
            # Cloudflare Turnstile expects the token in a callback
            injection_script = f"""
            (function() {{
                // Find all Turnstile widgets and set their response
                var widgets = document.querySelectorAll('[data-sitekey], iframe[src*="challenges.cloudflare.com"]');
                
                // Method 1: Direct callback
                if (window.turnstile) {{
                    widgets.forEach(function(widget) {{
                        try {{
                            var sitekey = widget.getAttribute('data-sitekey');
                            if (sitekey) {{
                                window.turnstile.render(widget, {{
                                    sitekey: sitekey,
                                    callback: function(token) {{
                                        // Token is set automatically
                                    }}
                                }});
                            }}
                        }} catch(e) {{
                            console.log('Widget render error:', e);
                        }}
                    }});
                }}
                
                // Method 2: Set token directly in hidden input or callback
                var tokenInputs = document.querySelectorAll('input[name="cf-turnstile-response"]');
                tokenInputs.forEach(function(input) {{
                    input.value = '{token}';
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                }});
                
                // Method 3: Trigger callback if exists
                if (window.turnstileCallback) {{
                    window.turnstileCallback('{token}');
                }}
                
                // Method 4: Dispatch custom event
                var event = new CustomEvent('cf-turnstile-response', {{
                    detail: '{token}'
                }});
                document.dispatchEvent(event);
                
                return true;
            }})();
            """
            
            result = self.browser.run_js(injection_script)
            logger.info("Injected Turnstile token into page")
            time.sleep(3)  # Wait for Cloudflare to process
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to inject token: {e}")
            return False

    def _solve_cloudflare_with_solverify(self, url: str) -> Optional[Dict]:
        """
        Solve Cloudflare using Solverify.net Interstitial solver.
        Returns a dict with 'cookies' and 'useragent'.
        """
        if not config.SOLVERIFY_ENABLED or not config.SOLVERIFY_API_KEY:
            return None
            
        logger.info(f"Solving Cloudflare via Solverify for {url}...")
        
        try:
            # Prepare Proxy Info
            proxy_config = {}
            # DISABLED PROXY FOR SOLVERIFY TESTING - Force it to use its own IP
            # if config.PROXY_ENABLED and config.PROXY_URL:
            #     from urllib.parse import urlparse
            #     parsed = urlparse(config.PROXY_URL)
            #     proxy_config = {
            #         "proxyType": "http", # Solverify supports http/socks5
            #         "proxyAddress": parsed.hostname,
            #         "proxyPort": str(parsed.port),
            #     }
            #     if parsed.username and parsed.password:
            #         proxy_config["proxyLogin"] = parsed.username
            #         proxy_config["proxyPassword"] = parsed.password
            
            # 1. Create Task
            create_url = "https://solver.solverify.net/createTask"
            
            # Use browser's actual UA to ensure consistency
            current_ua = self.browser.user_agent if self.browser else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            
            payload = {
                "clientKey": config.SOLVERIFY_API_KEY,
                "task": {
                    "type": "interstitial",
                    "websiteURL": url,
                    "useragent": current_ua,
                    **proxy_config
                }
            }
            
            resp = requests.post(create_url, json=payload, timeout=30)
            if resp.status_code != 200:
                logger.error(f"Solverify CreateTask failed: {resp.text}")
                return None
                
            task_data = resp.json()
            if task_data.get("errorId") != 0:
                logger.error(f"Solverify error: {task_data}")
                return None
                
            task_id = task_data.get("taskId")
            logger.info(f"Solverify Task ID: {task_id}")
            
            # 2. Get Result
            result_url = f"https://solver.solverify.net/getTaskResult/{task_id}"
            params = {
                "clientKey": config.SOLVERIFY_API_KEY
            }
            
            # Poll for result
            for _ in range(60): # Try for 180 seconds
                time.sleep(3)
                resp = requests.get(result_url, params=params, timeout=30)
                if resp.status_code != 200:
                    continue
                    
                result_data = resp.json()
                
                if result_data.get("status") == "ready" or result_data.get("status") == "completed":
                    solution = result_data.get("solution", {})
                    cookies = solution.get("cookies", {})
                    ua = solution.get("useragent")
                    
                    logger.info("Solverify solved challenge!")
                    return {"cookies": cookies, "useragent": ua}
                
                if result_data.get("errorId") != 0:
                    logger.error(f"Solverify processing error: {result_data}")
                    return None
                    
            logger.warning("Solverify timeout")
            return None
            
        except Exception as e:
            logger.error(f"Solverify exception: {e}")
            return None

    def _solve_cloudflare_with_scrapeless_captcha(self, page_url: str, site_key: str) -> Optional[str]:
        """
        Solve Cloudflare Turnstile using Scrapeless 'captcha.turnstile' actor.
        """
        if not config.SCRAPELESS_ENABLED or not config.SCRAPELESS_API_KEY:
            return None
            
        logger.info(f"Solving Cloudflare via Scrapeless CAPTCHA for {page_url}...")
        
        try:
            create_url = "https://api.scrapeless.com/api/v1/createTask"
            headers = {"x-api-token": config.SCRAPELESS_API_KEY}
            
            payload = {
                "actor": "captcha.turnstile",
                "input": {
                    "pageURL": page_url,
                    "siteKey": site_key
                }
            }
            
            resp = requests.post(create_url, headers=headers, json=payload, timeout=30)
            if resp.status_code != 200:
                logger.error(f"Scrapeless Task Create failed: {resp.text}")
                return None
                
            task_data = resp.json()
            task_id = task_data.get("taskId")
            logger.info(f"Scrapeless Task ID: {task_id}")
            
            # Poll for result
            result_url = f"https://api.scrapeless.com/api/v1/getTaskResult/{task_id}"
            
            for _ in range(40): # Try for ~120s
                time.sleep(3)
                resp = requests.get(result_url, headers=headers, timeout=30)
                if resp.status_code != 200:
                    continue
                    
                result_data = resp.json()
                if result_data.get("success"):
                    solution = result_data.get("solution", {})
                    token = solution.get("token")
                    logger.info("Scrapeless solved CAPTCHA!")
                    return token
                    
                if result_data.get("state") == "error":
                    logger.error(f"Scrapeless processing error: {result_data.get('message')}")
                    return None
                    
            logger.warning("Scrapeless CAPTCHA timeout")
            return None
            
        except Exception as e:
            logger.error(f"Scrapeless CAPTCHA exception: {e}")
            return None

    def _solve_cloudflare(self):
        """
        Attempt to solve Cloudflare challenge.
        Prioritizes Solverify (Interstitial) -> Scrapeless (Captcha) -> Manual Click -> 2captcha.
        """
        logger.info("Attempting to solve Cloudflare challenge...")
        
        # 1. Try Solverify (Best for Interstitial)
        if config.SOLVERIFY_ENABLED:
            solution = self._solve_cloudflare_with_solverify(self.browser.url)
            if solution:
                cookies = solution.get("cookies", {})
                if self._inject_cookies_into_browser(cookies, self.browser.url):
                    logger.info("Injected Solverify cookies. Reloading page...")
                    self.browser.refresh()
                    time.sleep(5)
                    if "challenge-platform" not in self.browser.url and "just a moment" not in self.browser.title.lower():
                        logger.info("Cloudflare solved via Solverify!")
                        return

        # Extract Site Key (needed for Scrapeless/2captcha)
        site_key = None
        try:
            logger.info("DEBUG: Attempting to extract site_key (Looping)...")
            
            # Loop for up to 30 seconds to wait for Turnstile to appear
            for attempt in range(15):
                # Method 1: Look for data-sitekey attribute (Standard)
                try:
                    site_key_elements = self.browser.eles('css:[data-sitekey]')
                    if site_key_elements:
                        site_key = site_key_elements[0].attr('data-sitekey')
                        logger.info(f"Found site key in data-sitekey: {site_key[:20]}...")
                        break
                except:
                    pass
                
                # Method 2: Extract from iframe src
                if not site_key:
                    try:
                        iframes = self.browser.eles('tag:iframe')
                        if attempt % 5 == 0: # Log every 5th attempt
                            logger.info(f"DEBUG (Attempt {attempt+1}): Found {len(iframes)} iframes.")
                            
                        for iframe in iframes:
                            src = iframe.attr('src') or ''
                            if 'challenges.cloudflare.com' in src or 'turnstile' in src.lower():
                                match = re.search(r'sitekey=([^&"\']+)', src, re.IGNORECASE)
                                if match:
                                    site_key = urllib.parse.unquote(match.group(1))
                                    logger.info(f"Found site key in iframe: {site_key[:20]}...")
                                    break
                    except:
                        pass
                
                if site_key:
                    break
                    
                # Method 3: Deep Search in Scripts (Shadow DOM simulation)
                if not site_key:
                    try:
                        js_code = """
                            (function() {
                                try {
                                    // 1. Check global turnstile config
                                    if (window.turnstile && window.turnstile.sitekey) return window.turnstile.sitekey;
                                    
                                    // 2. Check Cloudflare config object
                                    if (window._cf_chl_opt && window._cf_chl_opt.cRay) return "CF_OPT_FOUND"; 
                                    
                                    // 3. Search all script tags
                                    var scripts = document.getElementsByTagName('script');
                                    for (var i = 0; i < scripts.length; i++) {
                                        var html = scripts[i].innerHTML;
                                        if (html.includes('sitekey')) {
                                            var match = html.match(/sitekey["']?: ?["']([^"']+)["']/);
                                            if (match) return match[1];
                                        }
                                    }
                                    
                                    // 4. Check for the specific Turnstile widget container
                                    var widget = document.querySelector('.cf-turnstile');
                                    if (widget && widget.dataset.sitekey) return widget.dataset.sitekey;
                                    
                                    return null;
                                } catch (e) { return null; }
                            })();
                        """
                        result = self.browser.run_js(js_code)
                        
                        if result == "CF_OPT_FOUND":
                            logger.info("DEBUG: Found window._cf_chl_opt (Cloudflare Config). The challenge is active.")
                            # We might be able to extract more from this object if we knew the structure
                            
                        elif result:
                            site_key = result
                            logger.info(f"Found site key via JS Deep Search: {site_key[:20]}...")
                            break
                    except:
                        pass
                
                time.sleep(2)
                
        except Exception as e:
            logger.error(f"Error extracting site key: {e}")

        try:
            # If site key found, try Scrapeless CAPTCHA first
            if site_key and config.SCRAPELESS_ENABLED:
                 token = self._solve_cloudflare_with_scrapeless_captcha(self.browser.url, site_key)
                 if token:
                     if self._inject_turnstile_token(token):
                         # Wait and verify
                         time.sleep(5)
                         if "challenge-platform" not in self.browser.url:
                             logger.info("Cloudflare solved via Scrapeless CAPTCHA!")
                             return

            # 2. Try to find and click the Turnstile checkbox
            # ... existing click logic ...
            pass
            
            # ... (site key extraction logic) ...
            
            # If site key found, try Scrapeless CAPTCHA first
            if site_key and config.SCRAPELESS_ENABLED:
                 token = self._solve_cloudflare_with_scrapeless_captcha(self.browser.url, site_key)
                 if token:
                     if self._inject_turnstile_token(token):
                         # Wait and verify
                         time.sleep(5)
                         if "challenge-platform" not in self.browser.url:
                             logger.info("Cloudflare solved via Scrapeless CAPTCHA!")
                             return

            # Fallback to 2captcha
            # ... existing 2captcha logic ...

            # Look for common checkbox selectors
            checkbox_selectors = [
                '#challenge-stage iframe',
                'iframe[src*="cloudflare"]',
                'div.cb-i'
            ]
            
            for selector in checkbox_selectors:
                try:
                    # Wait a bit for the element to be stable
                    time.sleep(2)
                    
                    # Check if element exists
                    if self.browser.ele(selector):
                        logger.info(f"Found Cloudflare checkbox ({selector}). Attempting to click...")
                        
                        # Move mouse randomly before clicking
                        self.browser.actions.move_to(selector).wait(0.5).click()
                        
                        # Wait for potential solve
                        time.sleep(5)
                        
                        # Check if we passed
                        if "challenge-platform" not in self.browser.url and "just a moment" not in self.browser.title.lower():
                            logger.info("Cloudflare solved via click!")
                            return
                except:
                    pass
            
            # 2. If clicking failed, try 2captcha as fallback
            logger.warning("Click attempt failed. Falling back to 2captcha...")
            
            # Check if we are actually blocked
            title = self.browser.title.lower()
            page_html = self.browser.html.lower()
            
            if ("verify" not in title and 
                "just a moment" not in title and
                "checking your browser" not in page_html and
                "challenge-platform" not in page_html):
                return

            logger.warning("Cloudflare detected. Using 2captcha to solve...")
            time.sleep(2)  # Brief wait for page to stabilize

            # 2. Always use 2captcha if enabled
            if config.CAPTCHA_ENABLED and config.CAPTCHA_API_KEY:
                current_url = self.browser.url
                token = self._solve_cloudflare_with_2captcha(current_url)
                
                if token:
                    if self._inject_turnstile_token(token):
                        # Wait and verify
                        time.sleep(5)
                        title_final = self.browser.title.lower()
                        html_final = self.browser.html.lower()
                        if ("verify" not in title_final and 
                            "just a moment" not in title_final and
                            "checking your browser" not in html_final):
                            logger.info("Cloudflare solved with 2captcha!")
                            return
                        else:
                            logger.warning("Token injected but Cloudflare still present")
                    else:
                        logger.warning("Failed to inject 2captcha token")
                else:
                    logger.warning("2captcha failed to solve challenge")
            else:
                logger.warning("2captcha not enabled or API key missing. Cannot solve Cloudflare challenge.")

            if not (config.CAPTCHA_ENABLED and config.CAPTCHA_API_KEY):
                logger.error("Cloudflare challenge detected but 2captcha is not configured. Please set CAPTCHA_API_KEY in .env")
            else:
                logger.warning("Could not solve Cloudflare challenge with 2captcha.")
            
        except Exception as e:
            logger.error(f"Cloudflare solver error: {e}")
            import traceback
            logger.debug(traceback.format_exc())

    def _verify_connection(self):
        """Verify Scrapeless or BrightData connection"""
        try:
            # 1. Try Scrapeless (Primary - Paid but Cheap)
            if config.SCRAPELESS_ENABLED:
                result = self._get_html_from_scrapeless('https://www.upwork.com/nx/search/jobs/')
                if result:
                    logger.info("Connection verified via Scrapeless")
                    return True

            # 2. Try Bypass Server (Secondary - Free)
            if config.CLOUDFLARE_BYPASS_ENABLED:
                result = self._get_cloudflare_cookies_from_bypass_server('https://www.upwork.com/nx/search/jobs/')
                if result:
                    logger.info("Connection verified via Bypass Server")
                    return True

            # 3. Try BrightData (Tertiary - Paid)
            if config.BRIGHTDATA_UNLOCKER_ENABLED:
                result = self._get_html_from_brightdata('https://www.upwork.com/nx/search/jobs/')
                if result and isinstance(result, tuple) and len(result) == 3:
                    html_body, cookies_dict, user_agent = result
                    if html_body and len(html_body) > 100:
                        logger.info("BrightData connection verified - HTML received")
                        return True
            
            # 4. Fallback to assuming Browser + Proxy might work
            if config.PROXY_ENABLED:
                 return True

            logger.warning("No scraping method verified")
            return False
        except Exception as e:
            logger.debug(f"Connection verification error: {e}")
            return False

    def _scan_jobs_blocking(self):
        """
        Scan Strategy (Priority Order):
        1. Solverify + curl_cffi (CHEAPEST: $0.0002/solve, most reliable)
        2. Bypass Server with round-robin (FREE but needs Docker)
        3. BrightData as paid fallback
        """
        logger.info("=== Starting Scan ===")

        # --- Method 1: Solverify (CHEAPEST & MOST RELIABLE) ---
        if config.SOLVERIFY_ENABLED:
            try:
                html = self._get_html_with_solverify(config.UPWORK_SEARCH_URL)
                if html:
                    # Dump for debugging
                    with open("debug_solverify_html.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    
                    # Check if we got past Cloudflare
                    html_lower = html.lower()
                    is_challenge = (
                        "<title>challenge" in html_lower or
                        "just a moment" in html_lower or
                        "checking your browser" in html_lower
                    )
                    
                    if not is_challenge:
                        logger.info("SUCCESS! Solverify returned valid HTML!")
                        return self._parse_jobs_from_html(html)
                    else:
                        logger.warning("Solverify returned Cloudflare challenge page")
            except Exception as e:
                logger.error(f"Solverify error: {e}")
                import traceback
                logger.debug(traceback.format_exc())

        # --- Method 2: Bypass Server (maintains internal browser session) ---
        if config.CLOUDFLARE_BYPASS_ENABLED:
            try:
                logger.info("=== Attempting Cloudflare Bypass Server (10 retries) ===")
                html = self._get_html_from_bypass_server(config.UPWORK_SEARCH_URL)
                if html:
                    # Dump for debugging
                    with open("debug_bypass_html.html", "w", encoding="utf-8") as f:
                        f.write(html)
                    
                    # Check if we got past Cloudflare
                    html_lower = html.lower()
                    is_challenge = (
                        "<title>challenge" in html_lower or
                        "just a moment" in html_lower or
                        "verify you are human" in html_lower or
                        "checking your browser" in html_lower
                    )
                    
                    if not is_challenge:
                        logger.info("SUCCESS! Bypass Server returned valid HTML!")
                        return self._parse_jobs_from_html(html)
                    else:
                        logger.warning("Bypass server returned Cloudflare challenge page")
                else:
                    logger.warning("Bypass server returned no HTML")
            except Exception as e:
                logger.error(f"Bypass Server error: {e}")
                import traceback
                logger.debug(traceback.format_exc())

        # --- Method 2: BrightData Unlocker (Paid Fallback) ---
        if config.BRIGHTDATA_UNLOCKER_ENABLED:
            try:
                logger.info("=== Attempting BrightData Unlocker ===")
                result = self._get_html_from_brightdata(config.UPWORK_SEARCH_URL)
                if result and isinstance(result, tuple) and len(result) == 3:
                    html_body, _, _ = result
                    if html_body and len(html_body) > 1000:
                        logger.info(f"SUCCESS! BrightData returned {len(html_body)} chars")
                        return self._parse_jobs_from_html(html_body)
                    else:
                        logger.warning("BrightData returned empty or small response")
            except Exception as e:
                logger.error(f"BrightData error: {e}")

        # No methods worked
        logger.error("ALL SCRAPING METHODS FAILED. Check your configuration.")
        logger.error("Ensure CLOUDFLARE_BYPASS_ENABLED=true and Docker container is running on port 8001")
        return []

    def _parse_jobs_from_html(self, html_content: str) -> List[Dict]:
        """Shared parsing logic for both Browser and BrightData HTML"""
        if not html_content:
            return []
            
        try:
            soup = BeautifulSoup(html_content, 'lxml')
            jobs = []
            
            # Selectors
            cards = soup.select('article.job-tile')
            if not cards: cards = soup.select('section.air3-card-section')
            if not cards: cards = soup.select('article[class*="job"], article[class*="tile"]')
            
            logger.info(f"Parsing HTML: Found {len(cards)} job cards.")
            
            for card in cards:
                try:
                    # Title & Link extraction
                    if card.name == 'a':
                        title_link = card
                    else:
                        title_link = card.select_one('h3 a, h2 a, a[href*="/jobs/"]')
                    
                    if not title_link:
                        title_link = card.find('a', href=re.compile(r'/jobs/'))
                        
                    if not title_link: continue
                    
                    title = title_link.get_text(strip=True)
                    link = title_link.get('href', '')
                    
                    if not link or not title: continue
                    if link.startswith('/'): link = f"https://www.upwork.com{link}"
                    
                    # Extract job info from the info list
                    job_info = card.select_one('[data-test="JobInfo"]')
                    job_type = "Unknown"
                    experience_level = "Unknown"
                    budget_raw = None
                    budget_min = 0
                    budget_max = 0
                    
                    if job_info:
                        # Job type (Fixed/Hourly)
                        job_type_el = job_info.select_one('[data-test="job-type-label"]')
                        if job_type_el:
                            job_type_text = job_type_el.get_text(strip=True)
                            if 'Hourly' in job_type_text:
                                job_type = "Hourly"
                                # Extract hourly rate: "Hourly: $50.00 - $80.00"
                                hourly_match = re.search(r'\$(\d+(?:\.\d+)?)\s*-\s*\$(\d+(?:\.\d+)?)', job_type_text)
                                if hourly_match:
                                    budget_min = int(float(hourly_match.group(1)))
                                    budget_max = int(float(hourly_match.group(2)))
                                    budget_raw = f"${budget_min}-${budget_max}/hr"
                            else:
                                job_type = "Fixed"
                        
                        # Experience level
                        exp_el = job_info.select_one('[data-test="experience-level"]')
                        if exp_el:
                            experience_level = exp_el.get_text(strip=True)
                        
                        # Fixed price budget
                        budget_el = job_info.select_one('[data-test="is-fixed-price"]')
                        if budget_el:
                            budget_text = budget_el.get_text(strip=True)
                            # Extract: "Est. budget: $500.00"
                            budget_match = re.search(r'\$(\d{1,3}(?:,\d{3})*(?:\.\d+)?)', budget_text)
                            if budget_match:
                                budget_val = budget_match.group(1).replace(',', '')
                                budget_min = budget_max = int(float(budget_val))
                                budget_raw = f"${budget_min}"
                    
                    # Extract description
                    desc_el = card.select_one('[data-test="JobDescription"] p')
                    description = desc_el.get_text(strip=True)[:500] if desc_el else ""
                    
                    # Extract skills/tags
                    tags = []
                    skill_tokens = card.select('[data-test="token"]')
                    for token in skill_tokens[:6]:
                        tag_text = token.get_text(strip=True)
                        if tag_text and not tag_text.startswith('+'):
                            tags.append(tag_text)
                    
                    # Extract posted time
                    posted_el = card.select_one('[data-test="job-pubilshed-date"]')
                    posted_text = posted_el.get_text(strip=True) if posted_el else ""
                    
                    jobs.append({
                        'id': hashlib.md5(f"{link}".encode('utf-8')).hexdigest(),
                        'title': title,
                        'link': link,
                        'summary': description or card.get_text(separator=' ', strip=True)[:300] + "...",
                        'description': description,
                        'budget': budget_raw or "N/A",
                        'budget_min': budget_min,
                        'budget_max': budget_max,
                        'job_type': job_type,
                        'experience_level': experience_level,
                        'tags': tags,
                        'posted': posted_text,
                        'published': datetime.now().isoformat()
                    })
                except Exception as e:
                    logger.debug(f"Error parsing job card: {e}")
                    continue
                    
            return jobs
        except Exception as e:
            logger.error(f"HTML parsing error: {e}")
            return []

    def _extract_budget(self, text: str) -> Optional[str]:
        # Improved Regex for Hourly and Fixed
        match = re.search(r'(\$\d{1,3}(?:,\d{3})*(?:\.\d+)?\s*-\s*\$\d{1,3}(?:,\d{3})*(?:\.\d+)?(?:\s*/hr)?)|(\$\d{1,3}(?:,\d{3})*(?:\.\d+)?(?:\s*/hr)?)', text)
        return match.group(0) if match else "N/A"

    def _extract_tags(self, text: str) -> List[str]:
        # Just grab the skills pill elements if possible, otherwise crude text search
        # This is a fallback list
        common_skills = ['Python', 'JavaScript', 'React', 'Node.js', 'AWS', 'Django', 'Flask', 'AI', 'Machine Learning', 'Data Entry']
        return [s for s in common_skills if s.lower() in text.lower()][:4]