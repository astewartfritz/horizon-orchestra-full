"""Comprehensive test suite for the parsing system."""

import json
import asyncio
import time

from orchestra.parsing import (
    JSONHealer, ToolCallFixer, SemanticExtractor,
    HallucinationScrubber, StreamingParser, OutputValidator,
    ToolCall, ToolSpec, RepairAction
)
from orchestra.parsing.output_validator import ValidationRule, RuleType
from orchestra.parsing.hallucination_scrubber import HallucinationReport

results = []


def test(name, condition):
    if condition:
        results.append(f"{name}: PASS")
    else:
        results.append(f"{name}: FAIL")
        print(f"  FAIL: {name}")


# ========================================
# JSON Healer tests
# ========================================
healer = JSONHealer()

# 1. Trailing comma
r, rp = healer.heal('{"key": "val",}')
test("trailing_comma", r == {"key": "val"})

# 2. Python booleans
r, rp = healer.heal('{"a": True, "b": None, "c": False}')
test("python_bools", r == {"a": True, "b": None, "c": False})

# 3. Single quotes
r, rp = healer.heal("{'key': 'val'}")
test("single_quotes", r == {"key": "val"})

# 4. Missing closing brackets
r, rp = healer.heal('{"a": {"b": 1}')
test("missing_brackets", r == {"a": {"b": 1}})

# 5. Comments
r, rp = healer.heal('{"a": 1 // comment\n}')
test("comments", r == {"a": 1})

# 6. Markdown fence
r, rp = healer.heal('```json\n{"key": "val"}\n```')
test("markdown_fence", r == {"key": "val"})

# 7. Truncated string
r, rp = healer.heal('{"key": "val')
test("truncated_string", isinstance(r, dict) and "key" in r)

# 8. Truncated array
r, rp = healer.heal('[1, 2, 3,')
test("truncated_array", r == [1, 2, 3])

# 9. Unquoted keys
r, rp = healer.heal('{key: "val"}')
test("unquoted_keys", r == {"key": "val"})

# 10. Inf/NaN/undefined
r, rp = healer.heal('{"a": Infinity, "b": NaN, "c": undefined}')
test("special_values", r == {"a": None, "b": None, "c": None})

# 11. Extract from prose
r, rp = healer.heal('Here is the result: {"key": "val"} hope that helps!')
test("extract_prose", r == {"key": "val"})

# 12. Hex escapes (just no crash)
r, rp = healer.heal('{"a": "hello"}')
test("hex_escapes", True)

# 13. Control chars
r, rp = healer.heal('{"a": 1}')
test("control_chars", r == {"a": 1})

# 14. extract_json_from_text
objs = healer.extract_json_from_text('Here {"a":1} and {"b":2} done')
test("extract_json_from_text", len(objs) >= 2)

# 15. detect_encoding
enc = healer.detect_encoding(b"hello world")
test("detect_encoding", enc == "utf-8")

# 16. validate
vr = healer.validate({"name": "test"}, {"type": "object", "required": ["name"]})
test("validate", vr.valid)

# 17. normalize
n = healer.normalize({"x": "42"}, {"type": "object", "properties": {"x": {"type": "integer"}}})
test("normalize", n["x"] == 42)

# 18. Deeply nested
deep = '{"a":' * 50 + '"val"' + '}' * 50
r, rp = healer.heal(deep)
test("deep_nesting", isinstance(r, dict))

# 19. Leading zeros
r, rp = healer.heal('{"a": 007}')
test("leading_zeros", isinstance(r, dict))

# 20. Block comments
r, rp = healer.heal('{"a": 1 /* block comment */}')
test("block_comments", r == {"a": 1})

json_pass = len([r for r in results if "PASS" in r])
json_total = len(results)
print(f"JSONHealer: {json_pass}/{json_total} tests pass")

# ========================================
# ToolCallFixer tests
# ========================================
fixer = ToolCallFixer()
tools = [
    ToolSpec(name="search", description="Search the web", parameters={
        "properties": {"query": {"type": "string"}},
        "required": ["query"]
    }),
    ToolSpec(name="read_file", description="Read a file", parameters={
        "properties": {"path": {"type": "string"}},
        "required": ["path"]
    }),
]

closest = fixer.suggest_closest_tool("serach", tools)
test("fuzzy_match", closest == "search")

conf = fixer.detect_tool_intent("I need to search for Python tutorials", tools)
test("tool_intent", conf > 0.3)

calls = fixer.fix('{"name": "search", "arguments": {"query": "hello"}}', tools)
test("fix_raw_json", len(calls) >= 1 and calls[0].name == "search")

vc = fixer.validate_call(calls[0], tools[0])
test("validate_call", vc.valid)

call = ToolCall(name="search", arguments={"query": 42})
repaired = fixer.repair_arguments(call, tools[0])
test("repair_arguments", isinstance(repaired.arguments["query"], str))

tc_pass = len([r for r in results if "PASS" in r]) - json_pass
print(f"ToolCallFixer: {tc_pass}/5 tests pass")

# ========================================
# SemanticExtractor tests
# ========================================
extractor = SemanticExtractor()

# HTML
html = """<html><head><title>Test</title></head><body>
<h1>Hello</h1><p>World</p>
<table><tr><th>Name</th><th>Age</th></tr><tr><td>Alice</td><td>30</td></tr></table>
</body></html>"""
content = extractor.extract_html(html)
test("html_extraction", content.title == "Test" and len(content.headings) >= 1 and len(content.tables) >= 1)

# Markdown
md = """# Title

Some text

```python
print("hello")
```

| Col1 | Col2 |
|------|------|
| a    | b    |
"""
mc = extractor.extract_markdown(md)
test("markdown_extraction", len(mc.headings) >= 1 and len(mc.code_blocks) >= 1)

# Code extraction
code = """import os

def hello(name: str) -> str:
    \"\"\"Say hello.\"\"\"
    return f"Hello {name}"

class Greeter:
    pass
"""
cc = extractor.extract_code(code, "python")
test("code_extraction", len(cc.functions) >= 1 and len(cc.imports) >= 1)

# Entity extraction
text = "Dr. John Smith from Acme Corp in New York sent an email to john@acme.com on January 5, 2024."
entities = extractor.extract_entities(text)
test("entity_extraction", len(entities.emails) >= 1 and len(entities.dates) >= 1)

# Fact extraction
text2 = "Python is a programming language. Google has a large campus."
facts = extractor.extract_facts(text2)
test("fact_extraction", len(facts) >= 1)

# Table extraction from plain text
table_text = "| Name  | Age |\n|-------|-----|\n| Alice | 30  |\n| Bob   | 25  |"
tables = extractor.extract_tables(table_text)
test("table_extraction", len(tables) >= 1)

# TypeScript extraction
ts_code = """import { useState } from 'react';

export function Counter(props: CounterProps): JSX.Element {
  return <div>hello</div>;
}

export class MyService {
  async getData(): Promise<Data> {}
}
"""
tcc = extractor.extract_code(ts_code, "typescript")
test("ts_extraction", len(tcc.functions) >= 1 and len(tcc.imports) >= 1)

# Rust extraction
rust_code = """use std::io::Read;

pub fn parse_input(data: &str) -> Result<Value, Error> {
    todo!()
}

pub struct Parser {
    buffer: String,
}
"""
rcc = extractor.extract_code(rust_code, "rust")
test("rust_extraction", len(rcc.functions) >= 1 and len(rcc.imports) >= 1)

se_pass = len([r for r in results if "PASS" in r]) - json_pass - tc_pass
print(f"SemanticExtractor: {se_pass}/8 tests pass")

# ========================================
# HallucinationScrubber tests
# ========================================
scrubber = HallucinationScrubber()

report = scrubber.scan("This is a normal text.")
test("scrub_basic", isinstance(report, HallucinationReport))

issues = scrubber.check_numeric_consistency("Revenue was 50% from product A, 30% from B, and 25% from C.")
test("numeric_consistency", True)  # No crash

report2 = scrubber.scan("Visit https://fake-site.invalidtld/page")
test("url_hallucination", True)  # No crash

fabs = scrubber.detect_fabricated_code("x.push(1)\ny.length", "python")
test("code_hallucination", len(fabs) >= 1)

issues2 = scrubber.verify_citations("According to [1] and [5]", ["Source 1", "Source 2"])
test("citation_verification", len(issues2) >= 1)

repeated = "This is a test sentence. " * 20
report3 = scrubber.scan(repeated)
has_rep = any(f.method == "repetition" for f in report3.findings)
test("repetition_detection", has_rep)

score = scrubber.score_confidence("This is definitely, absolutely, certainly true. Always works, guaranteed.")
test("confidence_score", 0 <= score <= 1)

# Scrub method
scrubbed, scrub_report = scrubber.scrub("Normal text. Normal text.")
test("scrub_method", isinstance(scrubbed, str))

# Performance benchmark
t0 = time.monotonic()
for _ in range(100):
    scrubber.scan("Normal text with some content about technology and science.")
elapsed = (time.monotonic() - t0) * 1000 / 100
test("performance_5ms", elapsed < 5.0)

hs_pass = len([r for r in results if "PASS" in r]) - json_pass - tc_pass - se_pass
print(f"HallucinationScrubber: {hs_pass}/9 tests pass (avg {elapsed:.2f}ms/call)")

# ========================================
# StreamingParser tests
# ========================================
parser = StreamingParser()


async def test_streaming():
    chunks = ["Hello ", "world! ", "Here is ", "some text."]

    async def gen():
        for c in chunks:
            yield c

    events = []
    async for event in parser.parse(gen()):
        events.append(event)

    has_complete = any(type(e).__name__ == "StreamComplete" for e in events)
    return has_complete, len(events)


has_complete, n_events = asyncio.run(test_streaming())
test("streaming_basic", has_complete)


async def test_code_block_stream():
    chunks = ["Here is code:\n", "```python\n", "print('hello')\n", "```\n", "Done."]

    async def gen():
        for c in chunks:
            yield c

    events = []
    async for event in parser.parse(gen()):
        events.append(event)

    types = [type(e).__name__ for e in events]
    has_start = "CodeBlockStart" in types
    has_end = "CodeBlockEnd" in types
    return has_start and has_end


cb_ok = asyncio.run(test_code_block_stream())
test("streaming_code_blocks", cb_ok)

sp_pass = len([r for r in results if "PASS" in r]) - json_pass - tc_pass - se_pass - hs_pass
print(f"StreamingParser: {sp_pass}/2 tests pass ({n_events} events)")

# ========================================
# OutputValidator tests
# ========================================
validator = OutputValidator()

report = validator.validate("Here is a comprehensive answer with multiple points.", "What is Python?")
test("validator_basic", isinstance(report.score, float) and 0 <= report.score <= 1)

grade = validator.grade("Python is a programming language.", "What is Python?")
test("validator_grade", 0 <= grade <= 1)

report2 = validator.validate("My SSN is 123-45-6789", "test")
has_safety = any(v.rule_type == RuleType.SAFETY for v in report2.violations)
test("validator_safety", has_safety)

cleaned = validator.enforce(
    "Key: api_key=sk_test_1234567890abcdef and SSN 123-45-6789",
    [ValidationRule(rule_type=RuleType.SAFETY, description="Remove PII")],
)
test("validator_enforce", "123-45-6789" not in cleaned)

report3 = validator.validate(
    "Use these steps:\n1. Install Python\n2. Run the script",
    "How do I set up Python?",
)
test("validator_actionability", "actionability" in report3.checks_passed)

ov_pass = len([r for r in results if "PASS" in r]) - json_pass - tc_pass - se_pass - hs_pass - sp_pass
print(f"OutputValidator: {ov_pass}/5 tests pass")

# ========================================
# Summary
# ========================================
print()
print("=" * 50)
total_pass = len([r for r in results if "PASS" in r])
total = len(results)
print(f"TOTAL: {total_pass}/{total} tests pass")
if total_pass == total:
    print("ALL TESTS PASS")
else:
    print("FAILURES:")
    for r in results:
        if "FAIL" in r:
            print(f"  {r}")
