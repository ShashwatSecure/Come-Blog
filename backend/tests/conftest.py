import pytest

from app.graph.state import OrchestratorOutput, SectionEvaluation, SectionPlan


class FakeStructuredLLM:
    """Stands in for `ChatOllama(...).with_structured_output(Schema)`."""

    def __init__(self, response):
        self._response = response

    def invoke(self, _messages):
        return self._response


class FakeMessage:
    def __init__(self, content: str):
        self.content = content


class FakeLLM:
    """Stands in for a plain `ChatOllama(...)` instance used by worker/reducer."""

    def __init__(self, text: str = "Fake generated content."):
        self._text = text

    def invoke(self, _messages):
        return FakeMessage(self._text)

    def with_structured_output(self, schema):
        if schema is OrchestratorOutput:
            return FakeStructuredLLM(
                OrchestratorOutput(
                    title="Fake Blog Title",
                    sections=[
                        SectionPlan(
                            id="intro_topic",
                            title="First Section",
                            brief="Cover the basics.",
                            key_points=["point a", "point b"],
                        ),
                        SectionPlan(
                            id="second_topic",
                            title="Second Section",
                            brief="Cover advanced bits.",
                            key_points=["point c"],
                        ),
                    ],
                )
            )
        if schema is SectionEvaluation:
            return FakeStructuredLLM(
                SectionEvaluation(score=0.9, passed=True, feedback="Looks good.")
            )
        raise ValueError(f"Unexpected schema {schema}")


@pytest.fixture
def fake_llm(monkeypatch):
    llm = FakeLLM()
    monkeypatch.setattr("app.graph.nodes.get_llm", lambda temperature=None: llm)
    return llm
