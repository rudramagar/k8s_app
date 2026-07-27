class SoupConnectionError(Exception):
    def __init__(self, message="Soup Connection error occurred"):
        self.message = message
        super().__init__(self.message)

class FileReadError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)
