import driver
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement

from selenium_stealth import stealth

import pyperclip


class ChromeDriver(driver.Driver):

    def __init__(self):
        self.options = self.getOptions()
        self.driver = self.getDriver(self.options)

    def getOptions(self) -> Options:
        options = Options()

        # headless 옵션 설정
        options.add_argument(
            "--headless=new"
        )  # 'new'를 사용하여 새로운 headless 모드를 활성화
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-extensions")
        options.add_experimental_option("useAutomationExtension", False)

        # 브라우저 윈도우 사이즈
        options.add_argument("window-size=1920x1080")
        options.add_argument("--start-maximized")

        # 사람처럼 보이게 하는 옵션들
        options.add_argument("disable-gpu")  # 가속 사용 x
        options.add_argument("lang=ko_KR")  # 가짜 플러그인 탑재
        options.add_argument(
            "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/61.0.3163.100 Safari/537.36"
        )  # user-agent 이름 설정

        # 브라우저 꺼짐 방지
        options.add_experimental_option("detach", True)

        # 불필요한 에러메시지 노출 방지
        options.add_experimental_option("excludeSwitches", ["enable-logging"])

        return options

    def getDriver(self, options) -> webdriver.Chrome:
        driver = webdriver.Chrome(options=options)
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """
            },
        )
        driver.execute_script(
            "Object.defineProperty(navigator, 'plugins', {get: function() {return[1, 2, 3, 4, 5];},});"
        )
        driver.execute_script(
            "Object.defineProperty(navigator, 'languages', {get: function() {return ['ko-KR', 'ko']}})"
        )
        driver.execute_script(
            "const getParameter = WebGLRenderingContext.getParameter;WebGLRenderingContext.prototype.getParameter = function(parameter) {if (parameter === 37445) {return 'NVIDIA Corporation'} if (parameter === 37446) {return 'NVIDIA GeForce GTX 980 Ti OpenGL Engine';}return getParameter(parameter);};"
        )

        stealth(
            driver,
            languages=["ko-KR", "ko"],
            vendor="Google Inc.",
            platform="Win64",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )
        return driver

    def close(self):
        if self.driver:
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

    def getPageSource(self):
        return self.driver.page_source

    def findChildElementsByXpath(self, element: WebElement, selector):
        return element.find_elements(By.XPATH, selector)

    def findChildElement(self, element: WebElement, selector) -> WebElement:
        return element.find_element(By.TAG_NAME, selector)

    def wait(self, seconds):
        self.driver.implicitly_wait(seconds)
