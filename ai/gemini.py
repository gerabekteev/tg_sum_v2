import logging
import asyncio
import hashlib
import time
import json
import httpx
import config

logger = logging.getLogger(__name__)

SUMMARIZER_PROMPT = (
    "Ты — ИИ-ассистент, который анализирует переписку из учебного/рабочего чата и формирует краткую выжимку (саммари).\n"
    "Твоя задача — извлечь только действительно важные учебные, организационные или рабочие события, отфильтровав флуд, мемы, новости, бытовое и личное общение.\n\n"
    "ПРАВИЛА ОЦЕНКИ И ФОРМАТИРОВАНИЯ:\n"
    "1. Если в переписке нет важных учебных/организационных событий (дедлайнов, задач, тестов, анонсов, важных материалов), то выведи:\n"
    "   🚫 **Нет важной информации.**\n\n"
    "   💬 **О чем шла речь (краткий флуд-радар):**\n"
    "   - [Тезис 1: кратко, о какой общей/неформальной теме шла речь]\n"
    "   - [Тезис 2: кратко, о какой общей/неформальной теме шла речь]\n\n"
    "2. Если важная информация есть, структурируй ответ следующим образом (выводи ТОЛЬКО те подразделы подробностей, для которых есть реальные факты):\n\n"
    "   ⚡ **КРАТКАЯ ВЫЖИМКА (TL;DR)**:\n"
    "      - 2-3 ключевых факта одной строкой.\n\n"
    "   📝 **ПОДРОБНОСТИ:**\n"
    "   - 📅 **Дедлайны, Задачи и Тесты**: (суть и дедлайн)\n"
    "   - 📚 **Материалы и ссылки**: (ссылки, книги, документы)\n"
    "   - 🔄 **Изменения расписания**: (время, перенос встреч)\n"
    "   - 📢 **Важные объявления**: (информация от старост/руководителей)\n"
    "   - 💬 **Контекст чата**: (1 короткое предложение о главной теме флуда/обсуждения)\n\n"
    "КРИТИЧЕСКИ ВАЖНО:\n"
    "- Если важной информации нет, используй СТРОГО формат пункта 1.\n"
    "- Если важная информация есть, используй формат пункта 2 и исключай любые пустые подразделы из подробностей."
)

# Список бесплатных моделей в порядке приоритета
DEFAULT_MODELS_QUEUE = [
    "google/gemma-4-31b-it:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "qwen/qwen3-coder:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "meta-llama/llama-3.2-3b-instruct:free",
]

# ─── Кеширование контекста (Improvement #4) ───
_context_cache: dict = {}   # {log_id: {"text": str, "expires": float}}
_summary_cache: dict = {}   # {text_hash: {"summary": str, "model": str, "expires": float}}
CACHE_TTL = 1800            # 30 минут
MAX_CACHE_SIZE = 10


def get_cached_context(log_id: int) -> str | None:
    """Получает контекст чата из кеша, если он ещё не истёк."""
    entry = _context_cache.get(log_id)
    if entry and time.time() < entry["expires"]:
        return entry["text"]
    if entry:
        del _context_cache[log_id]
    return None


def set_cached_context(log_id: int, text: str):
    """Сохраняет контекст чата в кеш с TTL. При превышении лимита — LRU-вытеснение."""
    if len(_context_cache) >= MAX_CACHE_SIZE and log_id not in _context_cache:
        oldest_key = min(_context_cache, key=lambda k: _context_cache[k]["expires"])
        del _context_cache[oldest_key]
    _context_cache[log_id] = {"text": text, "expires": time.time() + CACHE_TTL}


def _get_cached_summary(text_hash: str) -> tuple[str, str] | None:
    """Проверяет кеш суммаризаций по хешу текста."""
    entry = _summary_cache.get(text_hash)
    if entry and time.time() < entry["expires"]:
        return entry["summary"], entry["model"]
    if entry:
        del _summary_cache[text_hash]
    return None


def _set_cached_summary(text_hash: str, summary: str, model: str):
    """Сохраняет результат суммаризации в кеш."""
    if len(_summary_cache) >= MAX_CACHE_SIZE and text_hash not in _summary_cache:
        oldest_key = min(_summary_cache, key=lambda k: _summary_cache[k]["expires"])
        del _summary_cache[oldest_key]
    _summary_cache[text_hash] = {"summary": summary, "model": model, "expires": time.time() + CACHE_TTL}


def _build_models_queue(preferred_model: str = None) -> list[str]:
    """Строит очередь моделей с учётом предпочтения пользователя."""
    models = DEFAULT_MODELS_QUEUE.copy()
    if preferred_model and preferred_model in models:
        models.remove(preferred_model)
        models.insert(0, preferred_model)
    elif preferred_model:
        models.insert(0, preferred_model)
    return models


def _get_request_headers() -> dict:
    """Стандартные заголовки для OpenRouter API."""
    return {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/gerabekteev/tg_sum_v2",
        "X-Title": "TG Summarizer V2",
    }


def _parse_retry_after(response_text: str) -> int | None:
    """Извлекает retry_after_seconds из JSON-ответа OpenRouter."""
    try:
        data = json.loads(response_text)
        metadata = data.get("error", {}).get("metadata", {})
        retry_after = metadata.get("retry_after_seconds")
        if retry_after is not None:
            return int(retry_after)
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return None


# ─── Improvement #1: Умный retry + exponential backoff ───

async def _smart_request(
    messages: list[dict],
    preferred_model: str = None,
    timeout: float = 120.0,
    max_retries_per_model: int = 2,
) -> tuple[str, str]:
    """
    Умный запрос к OpenRouter с:
    - Retry-After для 429 (если ≤ 30 с — ждёт и повторяет ту же модель)
    - Экспоненциальный backoff для других ошибок
    - Failover на следующие модели в очереди
    Возвращает (ответ, модель).
    """
    if not config.OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY не задан в конфигурации.")

    models = _build_models_queue(preferred_model)
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = _get_request_headers()
    last_error = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        for model in models:
            retries = 0
            base_delay = 2.0

            while retries <= max_retries_per_model:
                logger.info(f"Запрос к модели {model} (попытка {retries + 1}/{max_retries_per_model + 1})")
                data = {"model": model, "messages": messages}

                try:
                    response = await client.post(url, headers=headers, json=data)

                    if response.status_code == 200:
                        result = response.json()
                        choices = result.get("choices")
                        if not choices:
                            last_error = f"Пустые choices от {model}: {result}"
                            logger.warning(last_error)
                            break  # К следующей модели
                        content = choices[0]["message"]["content"].strip()
                        logger.info(f"Успешный ответ от {model}")
                        return content, model

                    elif response.status_code == 429:
                        retry_after = _parse_retry_after(response.text)
                        if retry_after and retry_after <= 30 and retries < max_retries_per_model:
                            logger.warning(f"429 от {model}. Retry-After={retry_after}с. Ожидаю...")
                            await asyncio.sleep(retry_after)
                            retries += 1
                            continue
                        else:
                            last_error = f"429 от {model}, retry_after={retry_after}с"
                            logger.warning(f"{last_error} — переход к следующей модели")
                            break

                    else:
                        last_error = f"Код {response.status_code} от {model}: {response.text[:300]}"
                        logger.warning(last_error)
                        if retries < max_retries_per_model:
                            delay = min(base_delay * (2 ** retries), 60)
                            logger.info(f"Backoff {delay}с перед повтором {model}")
                            await asyncio.sleep(delay)
                            retries += 1
                            continue
                        break

                except httpx.TimeoutException:
                    last_error = f"Таймаут {timeout}с для {model}"
                    logger.warning(last_error)
                    break
                except Exception as e:
                    last_error = f"Исключение {model}: {e}"
                    logger.warning(last_error)
                    if retries < max_retries_per_model:
                        delay = min(base_delay * (2 ** retries), 60)
                        await asyncio.sleep(delay)
                        retries += 1
                        continue
                    break

    raise RuntimeError(f"Все модели OpenRouter завершились ошибкой. Последняя: {last_error}")


# ─── Публичный API ───

async def summarize_messages(messages_text: str, preferred_model: str = None) -> tuple[str, str]:
    """
    Суммаризация с умным retry, failover и кешированием (#1, #4).
    Возвращает (summary, model_used).
    """
    text_hash = hashlib.md5(messages_text.encode()).hexdigest()
    cached = _get_cached_summary(text_hash)
    if cached:
        logger.info("Суммаризация взята из кеша")
        return cached

    msgs = [
        {"role": "system", "content": SUMMARIZER_PROMPT},
        {"role": "user", "content": f"ТЕКСТ ПЕРЕПИСКИ ДЛЯ АНАЛИЗА:\n{messages_text}"},
    ]
    summary, model = await _smart_request(msgs, preferred_model)
    _set_cached_summary(text_hash, summary, model)
    return summary, model


# ─── Improvement #8: Потоковая генерация (streaming) ───

async def summarize_messages_stream(messages_text: str, preferred_model: str = None):
    """
    Потоковая суммаризация. Async-генератор, yield'ящий (accumulated_text, model_name).
    Использует SSE stream от OpenRouter.
    """
    if not config.OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY не задан в конфигурации.")

    models = _build_models_queue(preferred_model)
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = _get_request_headers()
    last_error = None

    msgs = [
        {"role": "system", "content": SUMMARIZER_PROMPT},
        {"role": "user", "content": f"ТЕКСТ ПЕРЕПИСКИ ДЛЯ АНАЛИЗА:\n{messages_text}"},
    ]

    async with httpx.AsyncClient(timeout=120.0) as client:
        for model in models:
            retries = 0
            while retries <= 2:
                logger.info(f"Streaming к {model} (попытка {retries + 1}/3)")
                data = {"model": model, "messages": msgs, "stream": True}

                try:
                    async with client.stream("POST", url, headers=headers, json=data) as response:
                        if response.status_code == 429:
                            body = await response.aread()
                            retry_after = _parse_retry_after(body.decode())
                            if retry_after and retry_after <= 30 and retries < 2:
                                logger.warning(f"429 stream от {model}. Retry-After={retry_after}с")
                                await asyncio.sleep(retry_after)
                                retries += 1
                                continue
                            last_error = f"429 stream от {model}"
                            break

                        if response.status_code != 200:
                            body = await response.aread()
                            last_error = f"Код {response.status_code} от {model}: {body.decode()[:200]}"
                            logger.warning(last_error)
                            break

                        accumulated = ""
                        async for line in response.aiter_lines():
                            if not line.startswith("data: "):
                                continue
                            payload = line[6:]
                            if payload.strip() == "[DONE]":
                                break
                            try:
                                chunk = json.loads(payload)
                                delta = chunk.get("choices", [{}])[0].get("delta", {})
                                content = delta.get("content", "")
                                if content:
                                    accumulated += content
                                    yield accumulated, model
                            except json.JSONDecodeError:
                                continue

                        if accumulated:
                            text_hash = hashlib.md5(messages_text.encode()).hexdigest()
                            _set_cached_summary(text_hash, accumulated, model)
                            return
                        else:
                            last_error = f"Пустой streaming-ответ от {model}"
                            break

                except httpx.TimeoutException:
                    last_error = f"Streaming таймаут для {model}"
                    logger.warning(last_error)
                    break
                except Exception as e:
                    last_error = str(e)
                    logger.warning(f"Streaming исключение {model}: {e}")
                    break

    raise RuntimeError(f"Все модели завершились ошибкой (stream). Последняя: {last_error}")


async def ask_llm_about_chat(chat_text: str, question: str, preferred_model: str = None) -> tuple[str, str]:
    """Q&A по тексту чата с умным retry и failover."""
    qa_prompt = (
        "Ты — полезный ИИ-помощник. Тебе предоставлен фрагмент переписки из группового чата.\n"
        "Твоя задача — ответить на вопрос пользователя, основываясь СТРОГО на предоставленной переписке.\n"
        "Если в переписке нет ответа на этот вопрос, так и скажи: 'В переписке нет информации об этом.'\n"
        "Отвечай кратко, емко, вежливо и на русском языке."
    )
    msgs = [
        {"role": "system", "content": qa_prompt},
        {"role": "user", "content": f"ТЕКСТ ПЕРЕПИСКИ ЧАТА:\n{chat_text}\n\nВОПРОС ПОЛЬЗОВАТЕЛЯ: {question}"},
    ]
    return await _smart_request(msgs, preferred_model)
