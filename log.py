import logging


def getLogger(path: str) -> logging.Logger:
    logger = logging.getLogger()
    logHandler = logging.FileHandler(filename=path, encoding="utf-8")
    logHandler.setFormatter(logging.Formatter("%(asctime)s:%(levelname)s:%(message)s"))
    logger.addHandler(logHandler)
    return logger


def info(*messages):
    msg = " ".join(map(str, messages))
    logging.info(msg)


def error(message: str, e: Exception):
    logging.error(message)
    if e is not None:
        logging.exception(str(e))
