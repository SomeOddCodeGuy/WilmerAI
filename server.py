from Middleware.core.open_ai_api import WilmerApi
from Middleware.utilities.logging_utils import set_verbose

if __name__ == '__main__':
    api = WilmerApi()
    api.run_api()
    set_verbose()
