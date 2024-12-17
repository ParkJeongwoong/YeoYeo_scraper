import logging


def info(*messages):
    msg = " ".join(map(str, messages))
    logging.info(msg)


def error(message: str, e: Exception):
    logging.error(message)
    if e is not None:
        logging.exception(str(e))
