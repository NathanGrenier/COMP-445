import logging


def setup_logger(name, color_code):
    class CustomFormatter(logging.Formatter):
        LEVEL_COLORS = {
            "WARNING": "\033[93m",  # Yellow
            "ERROR": "\033[91m",  # Red
            "INFO": "\033[97m",  # White
        }
        RESET = "\033[0m"

        def format(self, record):
            level_color = self.LEVEL_COLORS.get(record.levelname, self.RESET)
            return f"{color_code}[{name}]{self.RESET} {level_color}[{record.levelname}]{self.RESET} {record.getMessage()}"

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        ch = logging.StreamHandler()
        ch.setFormatter(CustomFormatter())
        logger.addHandler(ch)

    # Prevent log messages from bubbling up to the root logger
    logger.propagate = False

    return logger
