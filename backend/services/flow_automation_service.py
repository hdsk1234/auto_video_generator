import os
import time
import asyncio
from typing import List, Dict

async def run_flow_automation_async(
    prompt: str,
    output_dir: str,
    target_url: str = "https://labs.google/fx/tools/flow",
    headless: bool = False
) -> List[Dict]:
    """
    Playwright automation for Flow AI video generation with detailed step-by-step console logging.
    """
    print(f"🚀 [Flow Auto] 자동화 시작 | Target URL: {target_url} | Headless: {headless}")
    print(f"📝 [Flow Auto] 입력 프롬프트: {prompt[:80]}...")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        print("❌ [Flow Auto] Playwright 모듈이 설치되어 있지 않습니다.")
        raise RuntimeError("Playwright가 설치되어 있지 않습니다. 'pip install playwright && playwright install chromium' 실행이 필요합니다.")

    os.makedirs(output_dir, exist_ok=True)
    saved_videos = []

    async with async_playwright() as p:
        user_data_dir = os.path.expanduser("~/.flow_automation_profile")
        print(f"🌐 [Flow Auto] 구글 로그인 우회 모드로 Chrome 브라우저 실행 중... (Profile: {user_data_dir})")
        
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars"
        ]
        user_agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

        try:
            # Try launching with installed system Chrome first for best Google Auth compatibility
            try:
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=headless,
                    channel="chrome",
                    viewport={"width": 1280, "height": 800},
                    accept_downloads=True,
                    user_agent=user_agent,
                    ignore_default_args=["--enable-automation"],
                    args=args
                )
            except Exception:
                # Fallback to default chromium if system chrome is not installed
                context = await p.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    headless=headless,
                    viewport={"width": 1280, "height": 800},
                    accept_downloads=True,
                    user_agent=user_agent,
                    ignore_default_args=["--enable-automation"],
                    args=args
                )
            print("✅ [Flow Auto] 봇 탐지 우회 브라우저 세션 오픈 완료.")
        except Exception as launch_err:
            print(f"❌ [Flow Auto] 브라우저 실행 실패: {launch_err}")
            raise launch_err

        page = context.pages[0] if context.pages else await context.new_page()
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        try:
            print(f"🔗 [Flow Auto] 페이지 이동 중: {target_url}")
            await page.goto(target_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)
            print(f"✅ [Flow Auto] 페이지 로드 완료 | 현재 URL: {page.url}")
        except Exception as nav_err:
            print(f"❌ [Flow Auto] 페이지 이동 실패: {nav_err}")
            await context.close()
            raise nav_err

        # Check if login is required
        prompt_selector = "textarea:not([name*='recaptcha']):visible, div[contenteditable='true']:visible, [contenteditable='true']:visible, input[placeholder*='prompt']:visible"
        login_btn = await page.query_selector("a:has-text('Sign in'), button:has-text('Sign in'), a:has-text('로그인'), button:has-text('로그인')")
        
        if login_btn or "accounts.google.com" in page.url or not (await page.query_selector(prompt_selector)):
            print("🔑 [Flow Auto] ⚠️ 구글/Flow 계정이 로그인되어 있지 않습니다!")
            print("👉 화면에 표시된 크롬 브라우저 창에서 구글 계정 로그인을 진행해 주세요 (최초 1회 저장 후 세션 유지됨).")
            print("⏳ 로그인 완료 대기 중 (최대 90초)...")
            
            for _ in range(90):
                await asyncio.sleep(1)
                pages = context.pages
                page = pages[-1] if pages else page
                
                textarea_check = await page.query_selector(prompt_selector)
                if textarea_check and "accounts.google.com" not in page.url:
                    print("🎉 [Flow Auto] 로그인 완료 감지! 3초 후 이동합니다...")
                    await asyncio.sleep(3)
                    break

        # Re-sync active page after login redirect
        pages = context.pages
        if pages:
            page = pages[-1]
            
        if "labs.google" not in page.url:
            print(f"🔗 [Flow Auto] Flow 메인 페이지로 다시 이동: {target_url}")
            await page.goto(target_url, wait_until="domcontentloaded")
            await asyncio.sleep(2)

        # Look for visible text area or input field for prompt (excluding hidden recaptcha elements)
        print("🔍 [Flow Auto] 프롬프트 입력창 탐색 중...")
        try:
            textarea = await page.wait_for_selector(prompt_selector, timeout=20000, state="visible")
            if textarea:
                print("✅ [Flow Auto] 프롬프트 입력창 발견. 포커스 및 텍스트 입력 중...")
                await textarea.click()
                await asyncio.sleep(0.5)
                
                try:
                    await textarea.fill(prompt)
                except Exception:
                    # Fallback to type if fill isn't supported on contenteditable
                    await page.keyboard.type(prompt)
                
                await asyncio.sleep(1)
                print("✅ [Flow Auto] 프롬프트 텍스트 입력 완료.")

                # Locate generate button
                print("🔍 [Flow Auto] 생성 버튼 탐색 중 (Generate / 생성 / Submit)...")
                generate_btn = await page.query_selector("button:has-text('Generate'), button:has-text('생성'), button:has-text('Submit'), button[type='submit']")
                if generate_btn:
                    print("✅ [Flow Auto] 생성 버튼 발견! 클릭 실행...")
                    await generate_btn.click()
                    print("✅ [Flow Auto] 생성 버튼 클릭 완료. 영상 다운로드 이벤트 대기 중 (최대 120초)...")
                else:
                    print("⚠️ [Flow Auto] 생성 버튼을 찾지 못했습니다. 엔터(Enter) 키 입력으로 대체 시도...")
                    await textarea.press("Enter")

                # Wait for download event
                try:
                    async with page.expect_download(timeout=120000) as download_info:
                        download = await download_info.value
                        print(f"📥 [Flow Auto] 다운로드 시작 감지됨: {download.suggested_filename}")
                        filename = f"flow_auto_{int(time.time())}.mp4"
                        save_path = os.path.join(output_dir, filename)
                        await download.save_as(save_path)

                        folder_name = os.path.basename(os.path.dirname(output_dir))
                        saved_videos.append({
                            "video_name": filename,
                            "video_path": save_path,
                            "video_url": f"/result/{folder_name}/flow_videos/{filename}"
                        })
                        print(f"🎉 [Flow Auto] 영상 저장 성공! 저장 위치: {save_path}")
                except Exception as dl_err:
                    print(f"❌ [Flow Auto] 다운로드 대기 타임아웃 또는 실패: {dl_err}")
            else:
                print("❌ [Flow Auto] 프롬프트 입력창을 20초 내에 찾지 못했습니다.")
        except Exception as e:
            print(f"❌ [Flow Auto] 페이지 상호작용 단계 에러 발생: {e}")

        print("🚪 [Flow Auto] 브라우저 세션 3초 후 완료 및 종료...")
        await asyncio.sleep(3)
        await context.close()

    print(f"🏁 [Flow Auto] 자동화 작업 종료 | 저장된 영상 수: {len(saved_videos)}")
    return saved_videos

def run_flow_automation(prompt: str, output_dir: str, target_url: str = "https://labs.google/fx/tools/flow", headless: bool = False) -> List[Dict]:
    return asyncio.run(run_flow_automation_async(prompt, output_dir, target_url, headless))
