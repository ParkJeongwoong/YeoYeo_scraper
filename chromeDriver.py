import driver
import time
import os
import undetected_chromedriver as uc
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from dotenv import load_dotenv

import pyperclip

load_dotenv()


class ChromeDriver(driver.Driver):

    def __init__(self):
        self.debug_mode = os.getenv("DEBUG_MODE", "False").lower() == "true"
        self.options = self.getOptions()
        self.driver = self.getDriver(self.options)
        self.driver.implicitly_wait(0)

    def getOptions(self) -> uc.ChromeOptions:
        options = uc.ChromeOptions()

        # headless 옵션 설정 (디버그 모드에서는 비활성화)
        if not self.debug_mode:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        # 브라우저 윈도우 사이즈
        options.add_argument("--window-size=1920,1080")

        # 사람처럼 보이게 하는 옵션들
        options.add_argument("--disable-gpu")
        options.add_argument("--lang=ko_KR")

        # 불필요한 에러메시지 노출 방지
        options.add_argument("--log-level=3")

        # 크롬 사용자 프로필 재사용
        chrome_profile_path = os.getenv("CHROME_PROFILE_PATH")
        if chrome_profile_path:
            options.add_argument(f"--user-data-dir={chrome_profile_path}")

        return options

    def getDriver(self, options) -> uc.Chrome:
        driver = uc.Chrome(options=options, use_subprocess=True, version_main=146)
        return driver

    def close(self):
        if self.driver:
            # 디버그 모드에서는 브라우저를 자동으로 닫지 않음
            if not self.debug_mode:
                self.driver.quit()
                self.driver = None

    def goTo(self, url):
        self.driver.get(url)
        self.wait(3)  # 페이지가 완전히 로딩되도록 3초동안 기다림

    def findBySelector(self, value):
        return self.driver.find_element(By.CSS_SELECTOR, value)

    def findByID(self, value):
        return self.driver.find_element(By.ID, value)

    def findByXpath(self, value):
        return self.driver.find_element(By.XPATH, value)

    def copyPaste(self, text):
        pyperclip.copy(text)
        ActionChains(self.driver).key_down(Keys.CONTROL).send_keys("v").key_up(
            Keys.CONTROL
        ).perform()

    def login(self, id, pw):
        # 페이지가 완전히 로드될 때까지 대기
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.ID, "id"))
        )

        self.driver.execute_script(
            f"document.querySelector('input[id=\"id\"]').setAttribute('value', '{id}')"
        )
        self.wait(1)
        self.driver.execute_script(
            f"document.querySelector('input[id=\"pw\"]').setAttribute('value', '{pw}')"
        )
        self.wait(1)

        # 로그인 상태 유지 체크박스 클릭
        try:
            keep_login_checkbox = self.driver.find_element(By.ID, "keep")
            if not keep_login_checkbox.is_selected():
                keep_login_checkbox.click()
                self.wait(0.5)
        except Exception:
            pass  # 체크박스가 없거나 이미 선택된 경우 무시

    def getPageSource(self):
        return self.driver.page_source

    def findChildElementsByXpath(self, element: WebElement, selector):
        return element.find_elements(By.XPATH, selector)

    def findChildElement(self, element: WebElement, selector) -> WebElement:
        return element.find_element(By.TAG_NAME, selector)

    def wait(self, seconds):
        time.sleep(seconds)

    def waitForDocumentReady(self, timeout=10):
        return WebDriverWait(self.driver, timeout).until(
            lambda current_driver: current_driver.execute_script(
                "return document.readyState"
            )
            == "complete"
        )

    def waitForAnySelector(self, selectors, timeout=10):
        def find_matching_selector(current_driver):
            for selector in selectors:
                elements = current_driver.find_elements(By.CSS_SELECTOR, selector)
                if len(elements) > 0:
                    return {
                        "selector": selector,
                        "count": len(elements),
                    }
            return False

        return WebDriverWait(self.driver, timeout).until(find_matching_selector)

    def getCurrentUrl(self):
        return self.driver.current_url

    def getTitle(self):
        return self.driver.title

    def saveScreenshot(self, path):
        return self.driver.save_screenshot(path)

    def saveFullPageScreenshot(self, path):
        """전체 페이지 스크린샷 (스크롤 포함)"""
        # 원래 윈도우 사이즈 저장
        originalSize = self.driver.get_window_size()
        
        # 전체 페이지 크기 계산
        totalWidth = self.driver.execute_script("return document.body.scrollWidth")
        totalHeight = self.driver.execute_script("return document.body.scrollHeight")
        
        # 윈도우 사이즈를 전체 페이지 크기로 변경
        self.driver.set_window_size(totalWidth, totalHeight)
        time.sleep(0.5)  # 리사이즈 완료 대기
        
        # 스크린샷 촬영
        result = self.driver.save_screenshot(path)
        
        # 원래 윈도우 사이즈로 복원
        self.driver.set_window_size(originalSize['width'], originalSize['height'])
        
        return result

    def getBrowserInfo(self):
        capabilities = self.driver.capabilities
        chrome_info = capabilities.get("chrome", {})
        chromedriver_version = chrome_info.get("chromedriverVersion", "")
        if chromedriver_version:
            chromedriver_version = chromedriver_version.split(" ")[0]
        return {
            "browserName": capabilities.get("browserName"),
            "browserVersion": capabilities.get("browserVersion"),
            "chromedriverVersion": chromedriver_version,
            "platformName": capabilities.get("platformName"),
            "seleniumVersion": uc.__version__,
            "headless": any(
                argument.startswith("--headless") for argument in self.options.arguments
            ),
        }

    def executeScript(self, script, *args):
        return self.driver.execute_script(script, *args)
