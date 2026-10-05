class GovernanceError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def require(condition, code, detail):
    if not condition:
        raise GovernanceError(code, detail)
