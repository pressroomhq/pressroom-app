"""AI Visibility — query multiple LLM providers to see if they mention/cite the org."""

import json
import logging
import os
import re
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select, desc

from api.auth import get_authenticated_data_layer
from models import AIVisibilityQuestion, AIVisibilityResult
from services.data_layer import DataLayer
from services.token_tracker import log_token_usage

log = logging.getLogger("pressroom")

router = APIRouter(prefix="/api/ai-visibility", tags=["ai_visibility"])

# Default questions for DreamFactory demo
DREAMFACTORY_QUESTIONS = [
    "How do I auto-generate a REST API from a database without writing code?",
    "What is the best API management platform for enterprise?",
    "How do I connect MySQL to a REST API?",
    "What tools exist for building an API gateway?",
]


def _score_response(response_text: str, org_name: str, domain: str) -> dict:
    """Score whether the org is cited, mentioned, or absent in the LLM response."""
    response_lower = response_text.lower()
    name_lower = org_name.lower()
    domain_clean = domain.lower().replace("https://", "").replace("http://", "").rstrip("/")

    has_name = name_lower in response_lower
    has_domain = domain_clean in response_lower
    has_link = f"http" in response_lower and domain_clean in response_lower

    # Find excerpt with the mention
    excerpt = ""
    if has_name:
        # Find the sentence containing the name
        sentences = re.split(r'[.!?]\s+', response_text)
        for s in sentences:
            if name_lower in s.lower():
                excerpt = s.strip()[:300]
                break

    if has_name and (has_domain or has_link):
        return {"score": "cited", "excerpt": excerpt}
    elif has_name:
        return {"score": "mentioned", "excerpt": excerpt}
    else:
        return {"score": "absent", "excerpt": ""}


async def _query_claude(question: str, org_id: int | None) -> str:
    """Query Anthropic Claude."""
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return ""
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=key)
        response = await client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1000,
            messages=[{"role": "user", "content": question}],
        )
        await log_token_usage(org_id, "ai_visibility_claude", response)
        return response.content[0].text
    except Exception as e:
        log.warning("Claude query failed: %s", e)
        return ""


async def _query_openai(question: str, model: str = "gpt-4o",
                         base_url: str | None = None,
                         api_key_env: str = "OPENAI_API_KEY",
                         provider_name: str = "gpt4o") -> str:
    """Query OpenAI-compatible API (GPT-4o, Perplexity, Grok)."""
    key = os.environ.get(api_key_env, "")
    if not key:
        return ""
    try:
        from openai import OpenAI
        kwargs = {"api_key": key}
        if base_url:
            kwargs["base_url"] = base_url
        client = OpenAI(**kwargs)
        response = client.chat.completions.create(
            model=model,
            max_tokens=1000,
            messages=[{"role": "user", "content": question}],
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        log.warning("%s query failed: %s", provider_name, e)
        return ""


async def _query_gemini(question: str) -> str:
    """Query Google Gemini."""
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return ""
    try:
        import google.generativeai as genai
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(question)
        return response.text or ""
    except Exception as e:
        log.warning("Gemini query failed: %s", e)
        return ""


PROVIDERS = {
    "claude": lambda q, org_id: _query_claude(q, org_id),
    "gpt4o": lambda q, org_id: _query_openai(q, model="gpt-4o", api_key_env="OPENAI_API_KEY", provider_name="gpt4o"),
    "perplexity": lambda q, org_id: _query_openai(q, model="sonar", base_url="https://api.perplexity.ai", api_key_env="PERPLEXITY_API_KEY", provider_name="perplexity"),
    "gemini": lambda q, org_id: _query_gemini(q),
    "grok": lambda q, org_id: _query_openai(q, model="grok-2-latest", base_url="https://api.x.ai/v1", api_key_env="GROK_API_KEY", provider_name="grok"),
}


@router.post("/scan")
async def scan_visibility(dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Run all questions against all providers, score results."""
    org_id = dl.org_id

    # Load questions for this org
    q = select(AIVisibilityQuestion).where(
        AIVisibilityQuestion.org_id == org_id
    ).order_by(AIVisibilityQuestion.position)
    questions = (await dl.db.execute(q)).scalars().all()

    if not questions:
        # Seed default questions
        for i, qt in enumerate(DREAMFACTORY_QUESTIONS):
            qobj = AIVisibilityQuestion(org_id=org_id, question=qt, position=i + 1)
            dl.db.add(qobj)
        await dl.db.commit()
        questions = (await dl.db.execute(q)).scalars().all()

    # Get org name and domain for scoring
    settings = await dl.get_all_settings()
    org_name = settings.get("onboard_company_name", "")
    domain = settings.get("onboard_domain", "")

    results = []
    for question in questions:
        q_results = []
        for provider_name, query_fn in PROVIDERS.items():
            response_text = await query_fn(question.question, org_id)
            if not response_text:
                q_results.append({
                    "provider": provider_name,
                    "response": "",
                    "score": "skipped",
                    "excerpt": "",
                })
                continue

            scoring = _score_response(response_text, org_name, domain)

            # Save result
            result = AIVisibilityResult(
                org_id=org_id,
                question=question.question,
                provider=provider_name,
                response=response_text[:5000],
                score=scoring["score"],
                excerpt=scoring["excerpt"][:500],
            )
            dl.db.add(result)

            q_results.append({
                "provider": provider_name,
                "response": response_text[:2000],
                "score": scoring["score"],
                "excerpt": scoring["excerpt"],
            })

        results.append({
            "question": question.question,
            "results": q_results,
        })

    await dl.db.commit()

    return {"scanned_at": datetime.utcnow().isoformat(), "questions": results}


@router.get("/{org_id}")
async def get_visibility(org_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Return latest scan results for this org."""
    q = (
        select(AIVisibilityResult)
        .where(AIVisibilityResult.org_id == dl.org_id)
        .order_by(desc(AIVisibilityResult.scanned_at))
        .limit(100)
    )
    rows = (await dl.db.execute(q)).scalars().all()

    # Group by question
    by_question = {}
    for row in rows:
        if row.question not in by_question:
            by_question[row.question] = []
        # Only keep latest per provider per question
        providers_seen = {r["provider"] for r in by_question[row.question]}
        if row.provider not in providers_seen:
            by_question[row.question].append({
                "provider": row.provider,
                "response": row.response[:2000],
                "score": row.score,
                "excerpt": row.excerpt,
            })

    return {
        "questions": [
            {"question": q, "results": results}
            for q, results in by_question.items()
        ]
    }


@router.get("/{org_id}/questions")
async def get_questions(org_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Get the visibility questions for this org."""
    q = select(AIVisibilityQuestion).where(
        AIVisibilityQuestion.org_id == dl.org_id
    ).order_by(AIVisibilityQuestion.position)
    questions = (await dl.db.execute(q)).scalars().all()
    return {"questions": [{"id": q.id, "question": q.question, "position": q.position} for q in questions]}


class QuestionsUpdate(BaseModel):
    questions: list[str]


@router.put("/{org_id}/questions")
async def update_questions(org_id: int, req: QuestionsUpdate, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Update the visibility questions for this org."""
    # Delete existing
    existing = (await dl.db.execute(
        select(AIVisibilityQuestion).where(AIVisibilityQuestion.org_id == dl.org_id)
    )).scalars().all()
    for q in existing:
        await dl.db.delete(q)

    # Insert new
    for i, qt in enumerate(req.questions[:4]):
        qobj = AIVisibilityQuestion(org_id=dl.org_id, question=qt.strip(), position=i + 1)
        dl.db.add(qobj)

    await dl.db.commit()
    return {"status": "ok", "count": min(len(req.questions), 4)}


@router.post("/{org_id}/questions/generate")
async def generate_questions(org_id: int, dl: DataLayer = Depends(get_authenticated_data_layer)):
    """Generate org-specific AI visibility questions using Claude."""
    # Note: org_id path param is ignored — we use dl.org_id from auth
    settings = await dl.get_all_settings()
    company_name = settings.get("onboard_company_name", "")
    domain = settings.get("onboard_domain", "")
    description = settings.get("onboard_description", "") or settings.get("company_description", "")

    if not company_name and not domain:
        return {"questions": DREAMFACTORY_QUESTIONS}

    try:
        from config import settings as app_settings
        key = app_settings.anthropic_api_key
        if not key:
            return {"questions": DREAMFACTORY_QUESTIONS}
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=key)
        context = f"Company: {company_name}\nDomain: {domain}"
        if description:
            context += f"\nDescription: {description[:400]}"

        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system="""Generate exactly 4 search questions that a buyer or researcher would ask an AI assistant when looking for solutions like this company.

Rules:
- Questions must be generic (don't name the company) — written as if the asker doesn't know the company yet
- Questions should match real search intent for this product category
- Each question on its own line, no numbering, no bullets, no explanation
- Output only the 4 questions, nothing else""",
            messages=[{"role": "user", "content": context}],
        )
        await log_token_usage(org_id, "ai_visibility_generate", response)
        lines = [l.strip() for l in response.content[0].text.strip().splitlines() if l.strip()]
        questions = lines[:4]
        if not questions:
            questions = DREAMFACTORY_QUESTIONS
        return {"questions": questions}
    except Exception as e:
        log.warning("Question generation failed: %s", e)
        return {"questions": DREAMFACTORY_QUESTIONS}
