"""Second-manufacturer substitution fixture; not allowlisted in production."""
from chamber_web.adapters.fake import FakeBackend
from chamber_web.domain.chamber import ChamberCapabilities, ChamberIdentity


class AlternateStubBackend(FakeBackend):
    def __init__(self, chamber_id: str):
        super().__init__(chamber_id, minimum=-10, maximum=50)
        self._identity = ChamberIdentity(chamber_id, "alternate_stub", "ExampleCo",
                                         "NoGradient-50", "TEST-ONLY", True)
        self._caps = ChamberCapabilities(-10, 50, True, True, True)
