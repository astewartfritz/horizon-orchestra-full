"""Horizon Orchestra — World-Class Parsing System.

The most capable parsing layer in any agentic AI system.  Heals broken JSON,
fixes malformed tool calls, extracts structured data from any format, detects
hallucinations, parses streaming output in real time, and validates everything.

Modules:
    json_healer         — Repairs all 20 classes of broken LLM JSON output.
    tool_call_fixer     — Fixes broken tool calls with fuzzy matching.
    semantic_extractor  — Extracts structured data from HTML/MD/code/text.
    hallucination_scrubber — Detects hallucinations with 10 methods, <5ms.
    streaming_parser    — Emits structured events mid-stream in real time.
    output_validator    — Schema compliance, safety, coherence, quality scoring.
"""

from __future__ import annotations

from .json_healer import JSONHealer, RepairAction, ValidationResult as JSONValidationResult
from .tool_call_fixer import (
    ToolCallFixer,
    ToolCall,
    ToolSpec,
    ValidationResult as ToolValidationResult,
)
from .semantic_extractor import (
    SemanticExtractor,
    ExtractedContent,
    MarkdownContent,
    CodeContent,
    EntitySet,
    Fact,
)
from .hallucination_scrubber import (
    HallucinationScrubber,
    HallucinationReport,
    HallucinationFinding,
    CitationIssue,
    InconsistencyFound,
    FabricationFound,
)
from .streaming_parser import (
    StreamingParser,
    ParsedEvent,
    EventType,
    ThinkingChunk,
    AnswerChunk,
    ToolCallDetected,
    CodeBlockStart,
    CodeBlockEnd,
    JSONObjectComplete,
    RepetitionDetected,
    StreamComplete,
    StreamAborted,
)
from .output_validator import (
    OutputValidator,
    ValidationReport,
    ValidationRule,
    RuleType,
    Violation,
)

__all__ = [
    # json_healer
    "JSONHealer",
    "RepairAction",
    # tool_call_fixer
    "ToolCallFixer",
    "ToolCall",
    "ToolSpec",
    # semantic_extractor
    "SemanticExtractor",
    "ExtractedContent",
    "MarkdownContent",
    "CodeContent",
    "EntitySet",
    "Fact",
    # hallucination_scrubber
    "HallucinationScrubber",
    "HallucinationReport",
    "HallucinationFinding",
    "CitationIssue",
    "InconsistencyFound",
    "FabricationFound",
    # streaming_parser
    "StreamingParser",
    "ParsedEvent",
    "EventType",
    "ThinkingChunk",
    "AnswerChunk",
    "ToolCallDetected",
    "CodeBlockStart",
    "CodeBlockEnd",
    "JSONObjectComplete",
    "RepetitionDetected",
    "StreamComplete",
    "StreamAborted",
    # output_validator
    "OutputValidator",
    "ValidationReport",
    "ValidationRule",
    "RuleType",
    "Violation",
]
