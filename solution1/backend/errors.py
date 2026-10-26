"""领域错误：携带稳定错误码，供适配层转成结构化响应。"""


class RequestError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message

    def response(self):
        return {'status': 'error', 'code': self.code, 'message': self.message}
