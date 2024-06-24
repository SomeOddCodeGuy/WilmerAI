class OpenAiApiPresets:
    def __init__(self, **kwargs):
        self.params = kwargs

    def to_json(self):
        return self.params
