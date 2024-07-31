import driver
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement

import pyperclip

class FirefoxDriver(driver.Driver):

    def __init__(self):
        self.options = self.getOptions()
        self.driver = self.getDriver(self.options)

    def getOptions(self) -> Options:
        options = Options()

        # headless 옵션 설정
        options.add_argument('--headless')  # headless 모드 활성화
        options.add_argument('--no-sandbox')
        options.set_preference("dom.webdriver.enabled", False)
        options.set_preference('useAutomationExtension', False)

        # 브라우저 윈도우 사이즈
        options.add_argument('window-size=1920x1080')

        # 사람처럼 보이게 하는 옵션들
        options.set_preference("general.useragent.override", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_12_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/61.0.3163.100 Safari/537.36")  # user-agent 이름 설정

        # 브라우저 꺼짐 방지
        options.set_preference("browser.tabs.remote.autostart", False)

        # 불필요한 에러메시지 노출 방지
        options.set_preference("dom.webdriver.enabled", False)
        options.set_preference('toolkit.telemetry.reportingpolicy.firstRun', False)
        return options

    def getDriver(self, options) -> webdriver.Firefox:
        driver = webdriver.Firefox(options=options)
        driver.execute_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
        driver.execute_script("Object.defineProperty(navigator, 'plugins', {get: function() {return [1, 2, 3, 4, 5];},});")
        driver.execute_script("Object.defineProperty(navigator, 'languages', {get: function() {return ['ko-KR', 'ko']}});")
        
        return driver

    def close(self):
        if self.driver:
            self.driver.quit()
            self.driver = None

    def goTo(self, url):
        self.driver.get(url)
        self.wait(3) # 페이지가 완전히 로딩되도록 3초동안 기다림

    def findBySelector(self, value):
        return self.driver.find_element(By.CSS_SELECTOR, value)
    
    def findByID(self, value):
        return self.driver.find_element(By.ID, value)
    
    def findByXpath(self, value):
        return self.driver.find_element(By.XPATH, value)
    
    def copyPaste(self, text):
        pyperclip.copy(text)
        ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()

    def login(self, id, pw):
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