"""Example: Review a piece of code using the CodeReviewer."""
import asyncio
import os

from code_agent.config import LLMConfig
from code_agent.reviewer import CodeReviewer


SAMPLE_CODE = """
def factorial(n):
    if n == 0:
        return 1
    return n * factorial(n - 1)

def process(data):
    result = []
    for i in range(len(data)):
        result.append(data[i] * 2)
    return result

def unsafe_delete(path):
    import os
    os.system(f"rm -rf {path}")
"""


async def main():
    reviewer = CodeReviewer(
        llm_config=LLMConfig(
            api_key=os.environ.get("OPENAI_API_KEY"),
        )
    )
    review = await reviewer.review(SAMPLE_CODE, context="Python utility functions")
    print(review)


if __name__ == "__main__":
    asyncio.run(main())
