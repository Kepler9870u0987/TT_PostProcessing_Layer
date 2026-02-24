"""
PipelineVersion — frozen dataclass for deterministic reproducibility.

Every pipeline run logs the full PipelineVersion for audit and backtesting.
v3: includes model_type (chat vs reasoning).
"""
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class PipelineVersion:
    """Contract of version to guarantee repeatability."""

    dictionaryversion: int
    modelversion: str                                       # e.g. "gpt-4o-2025-11-20"
    model_type: Literal["chat", "reasoning"] = "chat"       # v3: distinguishes chat vs reasoning
    parserversion: str = "email-parser-1.3.0"
    stoplistversion: str = "stopwords-it-2025.2"
    nermodelversion: str = "it_core_news_lg-3.8.2"
    schemaversion: str = "json-schema-v3.3"
    toolcallingversion: str = "openai-tool-calling-2026"

    def to_dict(self) -> dict:
        return {
            "dictionaryversion": self.dictionaryversion,
            "modelversion": self.modelversion,
            "model_type": self.model_type,
            "parserversion": self.parserversion,
            "stoplistversion": self.stoplistversion,
            "nermodelversion": self.nermodelversion,
            "schemaversion": self.schemaversion,
            "toolcallingversion": self.toolcallingversion,
        }

    def __repr__(self) -> str:
        return f"Pipeline-{self.dictionaryversion}-{self.modelversion}"
