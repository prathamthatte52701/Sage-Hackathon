import os
from dotenv import load_dotenv

load_dotenv()

from ai.llm import AIReasoner


code = """
app.post("/users", async (req, res) => {
    const user = await User.create(req.body);
    res.json(user);
});
"""


standard = """
External request data should be validated before
entering application business logic.
"""


api_key = os.getenv("GROQ_KEYS")

if not api_key:
    raise RuntimeError("GROQ_KEYS not found in .env")

model = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-120b"
)

reasoner = AIReasoner(
    api_key=api_key,
    model=model
)


# Actually ask the AI to analyze the code
result = reasoner.analyze(
    code=code,
    standard=standard
)

print(result.model_dump_json(indent=2))