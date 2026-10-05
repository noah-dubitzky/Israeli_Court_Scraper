from dataclasses import dataclass, field
from typing import Any


@dataclass
class case:
    type: str
    number: str
    name: str
    interest: str
    court: str
    status: str
    ID: str

    details: dict[str, Any] = field(default_factory=dict)

    def print(self) -> None:
        print("Case type:        ", self.type)
        print("Case number:      ", self.number)
        print("Case name:        ", self.name)
        print("Case interest:    ", self.interest)
        print("Court:            ", self.court)
        print("Status:           ", self.status)
        print("Internal case ID: ", self.ID)

        if self.details:
            print("Details:          ", self.details)