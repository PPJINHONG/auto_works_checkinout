# bot.py
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from appdirs import user_data_dir
from playwright.sync_api import sync_playwright

# ===== 설정 =====
BASE_URL  = "https://naver.worksmobile.com/"
ATT_URL   = "https://solomontech.ncpworkplace.com/user/commute/commuteDetail?targetId=attBtn"
LEAVE_URL = "https://solomontech.ncpworkplace.com/user/commute/commuteDetail?targetId=leaveBtn"

DEFAULT_ID = "ppjinhong"
DEFAULT_DOMAIN = "solomontech.net"
DEFAULT_PW = "@Wlsghd5006"
DEFAULT_CHECK_IN = "08:00"
DEFAULT_CHECK_OUT = "16:00"

APP_NAME = "NaverWorksBot"
ORG_NAME = "SolomonTech"
TIMEOUT = 30000  # ms

# (선택) 자동화 흔적 최소화
STEALTH_JS = r"""
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR', 'ko'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
"""

def get_profile_dir() -> str:
    p = Path(user_data_dir(APP_NAME, ORG_NAME)); p.mkdir(parents=True, exist_ok=True); return str(p)

def dump_debug(page, prefix="debug"):
    try: page.screenshot(path=f"{prefix}_screenshot.png", full_page=True)
    except: pass
    try:
        with open(f"{prefix}_dom.html","w",encoding="utf-8") as f: f.write(page.content())
    except: pass

# --- 로그인: 새 탭에서 2상황 자동 처리, 네비게이션 대기 없음 ---
def open_login_tab_and_signin(base_page, user_id, user_domain, user_pw):
    print("[LOGIN] 로그인 링크 클릭 → 새 탭 대기")
    with base_page.expect_popup(timeout=TIMEOUT) as pop:
        base_page.get_by_role("link", name="로그인").click()
    tab = pop.value

    tab.wait_for_load_state("domcontentloaded", timeout=TIMEOUT)

    # 보이는지 짧게 체크하는 헬퍼
    def vis(sel, t=1200):
        try: return tab.locator(sel).first.is_visible(timeout=t)
        except: return False

    has_user_id = vis("#user_id")
    has_pwd     = vis("#user_pwd")
    has_start   = vis("#loginStart.btn_submit")

    # 폼이 전혀 안 보이면 이미 로그인으로 간주
    if not has_user_id and not has_pwd and not has_start:
        print("[LOGIN] 폼 미노출 → 이미 로그인 상태로 간주")
        return tab

    if has_start and not has_pwd:
        # 상황1: 쿠키 없음 → 이메일 입력 → 시작 → PW → 로그인
        print("[LOGIN] 상황1: 이메일 입력 → 로그인Start")
        email = f"{user_id}@{user_domain}" if user_domain else user_id
        tab.locator("#user_id").fill(email)
        tab.locator("#loginStart.btn_submit").click()
        tab.wait_for_timeout(2000)
        tab.locator("#user_pwd").fill(user_pw)
        tab.locator("#loginBtn.btn_submit").click()
        tab.wait_for_timeout(1500)
        print("[LOGIN] 상황1 완료")
        return tab

    # 상황2: 쿠키 있음 → ID+PW 바로 → 로그인
    print("[LOGIN] 상황2: ID+PW 바로 입력")
    if has_user_id:
        tab.locator("#user_id").fill(user_id)
    tab.locator("#user_pwd").fill(user_pw)
    tab.locator("#loginBtn.btn_submit").click()
    tab.wait_for_timeout(1500)
    print("[LOGIN] 상황2 완료")
    return tab

# --- 어떤 마스크여도 그냥 시간 박아넣기(덮어쓰기) ---
def set_time_input(page, selector, hhmm):
    """
    - 인풋 클릭
    - 백스페이스 6번으로 지우기
    - '0800' 같은 숫자만 타이핑(마스크가 08:00로 만들어줌)
    """
    loc = page.locator(selector).first
    # 요소가 DOM에 붙을 때까지만 대기(visible 대기 X)
    loc.wait_for(state="attached", timeout=TIMEOUT)

    # 스크롤/클릭/포커스
    try:
        loc.scroll_into_view_if_needed(timeout=500)
    except Exception:
        pass
    try:
        loc.click(timeout=800)
    except Exception:
        try:
            # 안 보이면 강제 클릭
            loc.click(force=True, timeout=400)
        except Exception:
            # 그래도 안 되면 포커스만
            try:
                loc.evaluate("el => el.focus()")
            except Exception:
                pass

    # 백스페이스 6번
    for _ in range(6):
        try:
            page.keyboard.press("Backspace")
        except Exception:
            pass

    # 숫자만 타이핑 (예: "08:00" -> "0800")
    digits = hhmm.replace(":", "")
    page.keyboard.type(digits, delay=80)

    # 입력 반영 이벤트(혹시 필요할 수 있음)
    try:
        loc.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")
    except Exception:
        pass

    # 포커스 아웃(검증이 blur에서 도는 경우 대비)
    try:
        page.keyboard.press("Tab")
    except Exception:
        try:
            loc.evaluate("el => el.blur()")
        except Exception:
            pass

    """
    마스크 인풋 전용:
    - visible 아니어도 attached면 진행
    - 부모 포함 숨김 해제 시도
    - 포커스 강제 후 키보드로 '0800' 입력 (콜론 자동 포맷 유도)
    - 기존 값은 Ctrl/Meta+A + Backspace로 지우고 덮어씀
    """
    loc = page.locator(selector).first
    # 1) 존재만 보장 (가시성 대기 X)
    loc.wait_for(state="attached", timeout=TIMEOUT)

    # 2) 숨김/readonly/disabled 풀기 (부모 포함)
    try:
        loc.evaluate("""
        el => {
            let n = el;
            for (let i = 0; i < 4 && n; i++) {
                if (n.style) {
                    n.style.display = '';
                    n.style.visibility = 'visible';
                    n.style.opacity = 1;
                }
                n.hidden = false;
                n = n.parentElement;
            }
            el.removeAttribute('readonly');
            el.removeAttribute('disabled');
            el.type = 'text';
        }
        """)
    except Exception:
        pass

    # 3) 스크롤 & 클릭(가능하면) → 포커스 강제
    try:
        loc.scroll_into_view_if_needed(timeout=500)
    except Exception:
        pass
    try:
        # 가려져 있어도 이벤트만 발생시키고 싶다면 force=True
        loc.click(timeout=800)
    except Exception:
        try:
            loc.click(force=True, timeout=400)
        except Exception:
            pass
    try:
        loc.focus()
    except Exception:
        try:
            # 마지막 수단: JS 포커스
            loc.evaluate("el => el.focus()")
        except Exception:
            pass

    # 4) 기존 값 제거 (윈도우/맥 모두 커버)
    try:
        page.keyboard.press("Control+A")
        page.keyboard.press("Backspace")
    except Exception:
        pass
    try:
        page.keyboard.press("Meta+A")
        page.keyboard.press("Backspace")
    except Exception:
        pass
    # 몇 번 더 안전하게 지움
    for _ in range(6):
        try:
            page.keyboard.press("Backspace")
        except Exception:
            break

    # 5) 마스크용 '0800' 형태로 타이핑 (느리게)
    digits = hhmm.replace(":", "")
    page.keyboard.type(digits, delay=80)  # UI에서 08:00 으로 자동 포맷됨

    # 6) change 트리거 보장
    try:
        loc.evaluate("el => { el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")
    except Exception:
        pass

    # 7) 살짝 블러 (검증 로직이 포커스 아웃에서 동작하는 경우)
    try:
        page.keyboard.press("Tab")
    except Exception:
        try:
            loc.evaluate("el => el.blur()")
        except Exception:
            pass
    """
    보이지 않아도(attached만 되어 있으면) 값 강제 세팅.
    - visible 대기 X
    - readonly/disabled 제거
    - JS로 value 세팅 + input/change 이벤트 디스패치
    - fill/type는 보이는 경우에만 보너스로 시도
    """
    loc = page.locator(selector).first
    # 1) 존재(attach)만 기다림 — visible 대기 금지
    loc.wait_for(state="attached", timeout=TIMEOUT)

    # 2) 클릭/포커스 시도(보이면)
    try:
        if loc.is_visible(timeout=300):
            loc.click()
    except Exception:
        pass

    # 3) 가끔 readonly/disabled/hidden 되어 있으니 제거
    try:
        loc.evaluate("""el => {
            el.removeAttribute('readonly');
            el.removeAttribute('disabled');
            el.hidden = false;
            if (el.style) el.style.display = '';
        }""")
    except Exception:
        pass

    # 4) visible이면 fill/type로 시도
    try:
        if loc.is_visible(timeout=200):
            try:
                loc.fill(hhmm)
                return
            except Exception:
                try:
                    loc.press("Control+A"); loc.press("Backspace")
                except Exception:
                    pass
                try:
                    loc.press("Meta+A"); loc.press("Backspace")
                except Exception:
                    pass
                loc.type(hhmm, delay=10)
                return
    except Exception:
        pass

    # 5) 최종: JS로 강제 value 세팅 + 이벤트 발생(visibility 무관하게 작동)
    try:
        loc.evaluate(
            """(el, v) => {
                el.value = '';
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.value = v;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
            }""",
            hhmm,
        )
    except Exception as e:
        # 마지막 백업: 포커스 후 키보드 타이핑(안 보여도 포커스가 되면 입력될 수 있음)
        try:
            loc.evaluate("el => el.focus()")
            page.keyboard.type(hhmm, delay=10)
        except Exception:
            raise e

def click_confirm(page):
    # 공통 확인 버튼
    page.locator("#btn_confirm").first.click()

# --- 요구 플로우: ATT 새탭 → 입력/클릭 → LEAVE(같은 탭) → 입력/클릭 → 3초 ---
def run_att_then_leave(context, check_in, check_out):
    # ATT (출근)
    tab = context.new_page(); tab.set_default_timeout(TIMEOUT)
    print("[ATT] 페이지 진입:", ATT_URL)
    tab.goto(ATT_URL, wait_until="domcontentloaded")

    print("[ATT] 출근 시간 입력:", check_in)
    set_time_input(tab, "#checkInHm", check_in)

    print("[ATT] 출근 확인 클릭")
    click_confirm(tab)
    print("[ATT] 5초 대기 후 다음 단계 진행")
    tab.wait_for_timeout(5000)

    # LEAVE (퇴근) — 같은 탭에서 이동
    print("[LEAVE] 페이지 진입:", LEAVE_URL)
    tab.goto(LEAVE_URL, wait_until="domcontentloaded")

    print("[LEAVE] 퇴근 시간 입력:", check_out)
    set_time_input(tab, "#checkOutHm", check_out)

    print("[LEAVE] 퇴근 확인 클릭")
    click_confirm(tab)

    print("[LEAVE] 3초 대기 후 종료")
    tab.wait_for_timeout(3000)
    try: tab.close()
    except: pass

def main():
    load_dotenv()
    NAVER_ID = os.getenv("NAVER_ID", DEFAULT_ID)
    NAVER_DOMAIN = os.getenv("NAVER_DOMAIN", DEFAULT_DOMAIN)
    NAVER_PW = os.getenv("NAVER_PW", DEFAULT_PW)
    CHECK_IN = os.getenv("CHECK_IN", DEFAULT_CHECK_IN)
    CHECK_OUT = os.getenv("CHECK_OUT", DEFAULT_CHECK_OUT)

    with sync_playwright() as p:
        def launch(channel=None):
            return p.chromium.launch_persistent_context(
                user_data_dir=get_profile_dir(),
                headless=False, viewport=None,
                args=["--start-maximized","--disable-blink-features=AutomationControlled",
                      "--no-first-run","--no-default-browser-check"],
                timezone_id="Asia/Seoul", locale="ko-KR",
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/126.0.0.0 Safari/537.36"),
                channel=channel
            )
        try: ctx = launch(channel="chrome")
        except: ctx = launch()

        ctx.add_init_script(STEALTH_JS)

        page = ctx.new_page(); page.set_default_timeout(TIMEOUT)
        print("[MAIN] 메인 페이지 진입")
        page.goto(BASE_URL, wait_until="load")

        # 로그인 팝업 탭에서 처리
        try:
            login_tab = open_login_tab_and_signin(page, NAVER_ID, NAVER_DOMAIN, NAVER_PW)
        except Exception:
            dump_debug(page, "login_failed"); raise

        # 바로 ATT → LEAVE만 수행
        try:
            run_att_then_leave(ctx, CHECK_IN, CHECK_OUT)
        except Exception:
            dump_debug(login_tab, "attendance_failed"); raise

        # 완료 스샷
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        try: login_tab.screenshot(path=f"done_{ts}.png", full_page=True)
        except: pass

        ctx.close()

if __name__ == "__main__":
    main()
