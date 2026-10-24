# auth.py
import base64
import json
import os
import time
from typing import Optional, Tuple
from playwright.sync_api import sync_playwright

TOKEN_FILE = "session_tokens.json"


def is_jwt_expired(token: str, buffer_seconds: int = 300) -> bool:
  """Memeriksa kedaluwarsa JWT dari klaim 'exp' dengan buffer pengaman."""
  if not token or token.count(".") != 2:
    return True
  try:
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
    payload = json.loads(base64.b64decode(payload_b64).decode("utf-8"))
    exp = payload.get("exp")
    if not exp:
      return False
    return time.time() > (exp - buffer_seconds)
  except Exception:
    return True


def load_stored_tokens() -> Tuple[str, str]:
  """Membaca bearer token dan cf_clearance tersimpan dari berkas lokal."""
  if os.path.exists(TOKEN_FILE):
    try:
      with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data.get("bearer_token", ""), data.get("cf_clearance", "")
    except Exception:
      pass
  return "", ""


def save_stored_tokens(token: str, cookie: Optional[str]) -> None:
  """Menyimpan bearer token dan cf_clearance ke berkas lokal."""
  try:
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
      json.dump(
          {"bearer_token": token, "cf_clearance": cookie or ""}, f, indent=2
      )
  except Exception:
    pass


def _fetch_fresh_credentials(
    username: str, password: str, headless: bool = False
) -> Tuple[str, Optional[str]]:
  """Menjalankan Playwright untuk login ke BMKGSoft dan menangkap kredensial."""
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

    def handle_request(request):
      headers = request.headers
      auth_header = headers.get("authorization") or headers.get("Authorization")
      if auth_header and "bearer" in auth_header.lower():
        token_val = (
            auth_header.replace("Bearer ", "").replace("bearer ", "").strip()
        )
        if token_val:
          captured_token["value"] = token_val

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
      page.goto(
          "https://bmkgsatu.bmkg.go.id/",
          wait_until="domcontentloaded",
          timeout=45000,
      )

      user_selector = "input[type='text'], input[name='username']"
      pass_selector = "input[type='password'], input[name='password']"
      page.wait_for_selector(user_selector, state="visible", timeout=30000)

      page.fill(user_selector, username)
      page.fill(pass_selector, password)

      submit_button = (
          "button[type='submit'], button:has-text('Sign in'),"
          " button:has-text('Login')"
      )
      page.click(submit_button)
      page.wait_for_timeout(7000)

      bearer_token = captured_token["value"]

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

      cookies = context.cookies()
      cf_clearance = None
      for c in cookies:
        if c["name"] == "cf_clearance":
          cf_clearance = c["value"]
          break

      browser.close()

      if not bearer_token:
        raise RuntimeError(
            "Login UI berhasil, namun token otorisasi tidak ditemukan."
        )

      save_stored_tokens(bearer_token, cf_clearance)
      return bearer_token, cf_clearance

    except Exception as e:
      browser.close()
      raise RuntimeError(f"Playwright session fetch failed: {str(e)}")


def get_bmkg_credentials(
    username: str,
    password: str,
    headless: bool = False,
    force_refresh: bool = False,
) -> Tuple[str, Optional[str]]:
  """Mengembalikan kredensial BMKG dari cache lokal atau login baru."""
  cached_token, cached_cookie = load_stored_tokens()

  if (
      not force_refresh
      and cached_token
      and not is_jwt_expired(cached_token, buffer_seconds=300)
  ):
    return cached_token, cached_cookie

  return _fetch_fresh_credentials(username, password, headless=headless)