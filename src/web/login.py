import re

from playwright.sync_api import BrowserContext, Page


def _solve_math_expression(expression: str) -> int:
    # Supports simple BODMAS style puzzles with +, -, *, / and parentheses.
    sanitized = re.sub(r"[^0-9+\-*/(). ]", "", expression)
    if not sanitized.strip():
        raise ValueError(f"Could not parse captcha expression from: {expression}")
    result = eval(sanitized, {"__builtins__": {}}, {})  # nosec B307
    return int(round(float(result)))


def _handle_math_captcha_if_present(page: Page) -> None:
    captcha_text_locator = page.locator("text=/Math CAPTCHA:/i")
    if captcha_text_locator.count() == 0:
        return

    raw_text = captcha_text_locator.first.inner_text()
    expression_match = re.search(r"Math CAPTCHA:\s*([^\n=]+)", raw_text, flags=re.IGNORECASE)
    if not expression_match:
        raise ValueError(f"Math CAPTCHA text found but expression was not parsable: {raw_text}")
    answer = _solve_math_expression(expression_match.group(1))

    answer_selector_candidates = [
        'input[placeholder*="answer" i]',
        'input[name="captcha"]',
        'input[type="number"]',
        'input[type="text"]',
    ]
    for selector in answer_selector_candidates:
        if page.locator(selector).count() > 0:
            page.fill(selector, str(answer))
            break
    else:
        raise ValueError("Math CAPTCHA answer input field not found")

    if page.locator('button:has-text("Verify & Login")').count() > 0:
        page.click('button:has-text("Verify & Login")')
    else:
        page.click('button[type="submit"]')


def login(page: Page, *, base_url: str, username: str, password: str) -> None:
    page.goto(base_url, wait_until="domcontentloaded")
    username_selectors = [
        'input[name="username"]',
        'input[name="login"]',
        'input[placeholder="Login"]',
        'input[type="text"]',
    ]
    password_selectors = [
        'input[name="password"]',
        'input[type="password"]',
    ]

    for selector in username_selectors:
        if page.locator(selector).count() > 0:
            page.fill(selector, username)
            break
    else:
        raise ValueError("Could not find username/login input field on page")

    for selector in password_selectors:
        if page.locator(selector).count() > 0:
            page.fill(selector, password)
            break
    else:
        raise ValueError("Could not find password input field on page")

    if page.locator('button[type="submit"]').count() > 0:
        page.click('button[type="submit"]')
    elif page.locator('button:has-text("Sign In")').count() > 0:
        page.click('button:has-text("Sign In")')
    else:
        page.click('button:has-text("Login")')
    page.wait_for_load_state("networkidle")
    _handle_math_captcha_if_present(page)
    page.wait_for_load_state("networkidle")


def build_authenticated_page(context: BrowserContext, *, base_url: str, username: str, password: str) -> Page:
    page = context.new_page()
    login(page, base_url=base_url, username=username, password=password)
    return page
