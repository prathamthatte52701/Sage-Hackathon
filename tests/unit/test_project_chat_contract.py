import pytest

from models.schemas import ChatRequest
from routers import projects


@pytest.mark.asyncio
async def test_project_chat_hides_internal_retrieval_metadata(monkeypatch):
    async def fake_get_owned_project(project_id, owner_user_id):
        return {
            "_id": project_id,
            "project": {"name": "demo", "languages": ["python"], "frameworks": []},
            "files": [{"path": "app.py", "content": "print('hi')"}],
        }

    def fake_retrieve_relevant_files(project, question, top_k=5):
        return [{"path": "app.py", "snippet": "print('hi')"}]

    async def fake_retrieve_knowledge(*_args, **_kwargs):
        return {"mode": "hybrid", "available": True, "records": [{"id": "KB-1"}]}

    async def fake_retrieve_semantic_project_context(*_args, **_kwargs):
        return [{"name": "other-project", "similarity": 0.99, "method": "vector"}]

    async def fake_answer_project_question(question, retrieved, knowledge, semantic_context):
        return {"answer": "Use the cited file.", "cited_files": ["app.py"]}

    monkeypatch.setattr(projects, "get_owned_project", fake_get_owned_project)
    monkeypatch.setattr(projects, "retrieve_relevant_files", fake_retrieve_relevant_files)
    monkeypatch.setattr(projects, "retrieve_knowledge", fake_retrieve_knowledge)
    monkeypatch.setattr(projects, "retrieve_semantic_project_context", fake_retrieve_semantic_project_context)
    monkeypatch.setattr(projects, "answer_project_question", fake_answer_project_question)

    result = await projects.chat_about_project(
        "p1",
        ChatRequest(question="How should I improve validation?"),
        current_user={"_id": "test-user"},
    )

    assert result == {
        "answer": "Use the cited file.",
        "cited_files": ["app.py"],
        "retrieved_files": ["app.py"],
    }
    assert "knowledge_retrieval" not in result
    assert "semantic_project_context" not in result
