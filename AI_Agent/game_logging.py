from datetime import datetime
from typing import Optional


class GameLogger:
    def __init__(self, log_file: Optional[str] = None):
        self.log_file = log_file

    def log(self, message: str) -> None:
        """Log to both console and file."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        print(formatted)

        if self.log_file:
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(formatted + "\n")
            except Exception:
                pass


_game_logger: Optional[GameLogger] = None


def set_game_logger(logger: GameLogger) -> None:
    global _game_logger
    _game_logger = logger


def game_log(message: str) -> None:
    """Global logging function."""
    if _game_logger:
        _game_logger.log(message)
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
