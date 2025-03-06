from abc import *


class Driver(metaclass=ABCMeta):

    @abstractmethod
    def getOptions(self):
        pass

    @abstractmethod
    def getDriver(self):
        pass

    @abstractmethod
    def close(self):
        pass

    @abstractmethod
    def goTo(self):
        pass

    @abstractmethod
    def findBySelector(self):
        pass

    @abstractmethod
    def findByID(self):
        pass

    @abstractmethod
    def findByXpath(self):
        pass

    @abstractmethod
    def copyPaste(self):
        pass

    @abstractmethod
    def login(self):
        pass

    @abstractmethod
    def getPageSource(self):
        pass

    @abstractmethod
    def executeScript(self):
        pass

    @abstractmethod
    def findChildElementsByXpath(self):
        pass

    @abstractmethod
    def findChildElement(self):
        pass

    @abstractmethod
    def wait(self):
        pass
