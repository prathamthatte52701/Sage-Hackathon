import json
from typing import Any

from groq import Groq
from pydantic import BaseModel, Field


class AIAnalysisResult(BaseModel):
    confirmed: bool = False
    severity: str = "info"
    reason: str = ""
    recommendation: str = ""
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
    )


class AIReasoner:
    def __init__(
        self,
        api_key: str,
        model: str = "openai/gpt-oss-120b",
    ) -> None:

        if not api_key:
            raise ValueError(
                "Groq API key is required"
            )

        # Support:
        #
        # GROQ_KEYS=key1,key2,key3
        #
        # as well as:
        #
        # GROQ_KEYS=key1
        self.api_keys = [
            key.strip()
            for key in api_key.split(",")
            if key.strip()
        ]

        if not self.api_keys:
            raise ValueError(
                "No valid Groq API keys found"
            )

        self.model = model
        self._current_key_index = 0

    def _get_client(self, key: str) -> Groq:
        return Groq(api_key=key)

    def analyze(
        self,
        code: str,
        standard: str,
    ) -> AIAnalysisResult:

        if not code.strip():
            raise ValueError(
                "code cannot be empty"
            )

        if not standard.strip():
            raise ValueError(
                "standard cannot be empty"
            )

        system_prompt = """
You are a senior software security reviewer.

Analyze the supplied code against the supplied
engineering standard.

Return ONLY valid JSON.

The JSON must contain exactly:

{
  "confirmed": boolean,
  "severity": "info" | "low" | "medium" | "high" | "critical",
  "reason": "short explanation",
  "recommendation": "specific remediation",
  "confidence": number between 0 and 1
}

Rules:

1. Do not invent vulnerabilities.
2. Only confirm a violation when the supplied
   code provides sufficient evidence.
3. If the code does not violate the standard,
   confirmed must be false.
4. Confidence must represent certainty.
5. Keep the recommendation practical.
6. Return JSON only.
"""

        user_prompt = f"""
ENGINEERING STANDARD:

{standard}

CODE:

{code}

Determine whether the code violates the standard.
"""

        last_error: Exception | None = None

        # Try each configured Groq key.
        for offset in range(len(self.api_keys)):

            index = (
                self._current_key_index
                + offset
            ) % len(self.api_keys)

            key = self.api_keys[index]

            try:

                client = self._get_client(
                    key
                )

                response = (
                    client.chat.completions.create(
                        model=self.model,
                        temperature=0,
                        messages=[
                            {
                                "role": "system",
                                "content": system_prompt,
                            },
                            {
                                "role": "user",
                                "content": user_prompt,
                            },
                        ],
                    )
                )

                # Remember the successful key.
                self._current_key_index = index

                raw = (
                    response
                    .choices[0]
                    .message
                    .content
                )

                if not raw:
                    raise RuntimeError(
                        "Groq returned an empty response"
                    )

                data = self._parse_json(
                    raw
                )

                return AIAnalysisResult.model_validate(
                    data
                )

            except Exception as exc:

                last_error = exc

                print(
                    f"[AIReasoner] Groq key "
                    f"{index + 1}/{len(self.api_keys)} "
                    f"failed: {type(exc).__name__}"
                )

                continue

        raise RuntimeError(
            "All configured Groq API keys failed"
        ) from last_error

    @staticmethod
    def _parse_json(
        raw: str,
    ) -> dict[str, Any]:

        text = raw.strip()

        # Remove Markdown code fences if the model
        # accidentally returns them.
        if text.startswith("```"):

            lines = text.splitlines()

            if (
                lines
                and lines[0].startswith("```")
            ):
                lines = lines[1:]

            if (
                lines
                and lines[-1].strip() == "```"
            ):
                lines = lines[:-1]

            text = "\n".join(
                lines
            ).strip()

        try:

            data = json.loads(text)

        except json.JSONDecodeError as exc:

            raise RuntimeError(
                f"Groq returned invalid JSON: {raw}"
            ) from exc

        if not isinstance(data, dict):

            raise RuntimeError(
                "Groq response must be a JSON object"
            )

        return data