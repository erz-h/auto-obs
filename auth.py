# auth.py
from playwright.sync_api import sync_playwright


def get_bmkg_credentials(username, password, headless=False):
  """Automates BMKGSoft login and captures (bearer_token, cf_clearance) by intercepting outgoing API request headers and storage."""
  with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=headless,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
        ],
    )

    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            " (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        viewport={"width": 1280, "height": 720},
    )
    page = context.new_page()

    captured_token = {"value": None}

    # METHOD 1: Intercept outgoing 'Authorization' headers sent by BMKGSoft
    def handle_request(request):
      headers = request.headers
      auth_header = headers.get("authorization") or headers.get("Authorization")
      if auth_header and "bearer" in auth_header.lower():
        token_val = (
            auth_header.replace("Bearer ", "").replace("bearer ", "").strip()
        )
        if token_val:
          captured_token["value"] = token_val

    # METHOD 2: Intercept API login response payloads
    def handle_response(response):
      if captured_token["value"]:
        return
      try:
        if (
            "json" in response.headers.get("content-type", "")
            and response.status == 200
        ):
          data = response.json()

          def search_dict(d):
            if isinstance(d, dict):
              for k, v in d.items():
                if k.lower() in [
                    "token",
                    "access_token",
                    "bearer",
                    "jwt",
                ] and isinstance(v, str):
                  return v
                res = search_dict(v)
                if res:
                  return res
            elif isinstance(d, list):
              for item in d:
                res = search_dict(item)
                if res:
                  return res
            return None

          found = search_dict(data)
          if found:
            captured_token["value"] = found
      except Exception:
        pass

    page.on("request", handle_request)
    page.on("response", handle_response)

    try:
      # 1. Open portal
      page.goto(
          "https://bmkgsatu.bmkg.go.id/",
          wait_until="domcontentloaded",
          timeout=45000,
      )

      # 2. Fill login details
      user_selector = "input[type='text'], input[name='username']"
      pass_selector = "input[type='password'], input[name='password']"
      page.wait_for_selector(user_selector, state="visible", timeout=30000)

      page.fill(user_selector, username)
      page.fill(pass_selector, password)

      # 3. Click Sign in
      submit_button = (
          "button[type='submit'], button:has-text('Sign in'),"
          " button:has-text('Login')"
      )
      page.click(submit_button)

      # 4. Wait for post-login API requests to fire
      page.wait_for_timeout(7000)

      bearer_token = captured_token["value"]

      # METHOD 3: Fallback scan of browser storage
      if not bearer_token:
        bearer_token = page.evaluate("""() => {
                    function scan(storage) {
                        for (let i = 0; i < storage.length; i++) {
                            let k = storage.key(i);
                            let v = storage.getItem(k);
                            if (!v) continue;
                            if (v.startsWith('Bearer ')) return v.replace('Bearer ', '');
                            if (k.toLowerCase().includes('token') || k.toLowerCase().includes('auth') || k.toLowerCase().includes('user')) {
                                if (typeof v === 'string' && v.length > 20) return v;
                            }
                        }
                        return null;
                    }
                    return scan(localStorage) || scan(sessionStorage);
                }""")

      if bearer_token:
        bearer_token = (
            bearer_token.replace("Bearer ", "").replace("bearer ", "").strip()
        )

      # Extract cf_clearance cookie
      cookies = context.cookies()
      cf_clearance = None
      for c in cookies:
        if c["name"] == "cf_clearance":
          cf_clearance = c["value"]
          break

      browser.close()

      if not bearer_token:
        raise RuntimeError(
            "Login UI succeeded, but no Authorization token was detected in"
            " outgoing API requests or storage."
        )

      return bearer_token, cf_clearance

    except Exception as e:
      browser.close()
      raise RuntimeError(f"Playwright session fetch failed: {str(e)}")