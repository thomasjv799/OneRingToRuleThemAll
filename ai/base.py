from abc import ABC, abstractmethod


class AIProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        ...
