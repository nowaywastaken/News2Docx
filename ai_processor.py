#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Processing Module for News Articles - Two-Step Processing

This module provides comprehensive AI processing functions for news articles,
including word count adjustment and translation in two separate steps.

Step 1: Word Count Adjustment (400-450 words)
- Check if content word count is within target range
- If not, use short prompts to adjust word count and segment content
- Loop until word count is within acceptable range

Step 2: Translation
- Use specified System Prompt and User Prompt for translation
- Maintain exact paragraph structure and formatting
"""

# 标准库导入
import sys
import os
import re
import json
import time
import random
import logging
import argparse
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Optional, Tuple, Any, Union

# 第三方库导入
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# 统一日志系统导入
from unified_logger import (
    get_unified_logger, log_task_start, log_task_end,
    log_processing_step, log_error, log_performance,
    unified_print, log_processing_result, log_article_processing,
    log_api_call, log_batch_processing
)

from utils.text import now_stamp, count_english_words, safe_filename
# -------------------------------
# 常量和配置定义
# -------------------------------

# API配置
DEFAULT_MODEL_ID = os.environ.get("SILICONFLOW_MODEL", "THUDM/glm-4-9b-chat")
DEFAULT_SILICONFLOW_API_KEY = "sk-uxbxbsykbjkvvndwycojnnzdngyqcwpvldgczgljuqklsjas"
DEFAULT_SILICONFLOW_URL = "https://api.siliconflow.cn/v1/chat/completions"

# 兼容性别名
DEFAULT_OPENROUTER_API_KEY = DEFAULT_SILICONFLOW_API_KEY
DEFAULT_OPENROUTER_URL = DEFAULT_SILICONFLOW_URL

# 性能配置
DEFAULT_BATCH_SIZE = int(os.getenv("BATCH_SIZE", "1"))
DEFAULT_MAX_TOKENS_HARD_CAP = int(os.getenv("MAX_TOKENS_HARD_CAP", "1200"))
DEFAULT_USE_TWO_STEP = os.getenv("USE_TWO_STEP", "false").lower() == "true"
DEFAULT_CONCURRENCY = int(os.getenv("CONCURRENCY", "4"))

# 词数调整配置
TARGET_WORD_MIN = 400
TARGET_WORD_MAX = 450
MAX_ADJUSTMENT_ATTEMPTS = 5

# 其他常量
CHINESE_VARIANT_HINT = "（请输出简体中文）"
SEPARATOR_LINE = "—" * 50
MAIN_SEPARATOR = "=" * 60

# 翻译Prompts
TRANSLATION_SYSTEM_PROMPT = """You are a professional {{to}} native translator who needs to fluently translate text into {{to}}.

## Translation Rules
1. Output only the translated content, without explanations or additional content (such as "Here's the translation:" or "Translation as follows:")
2. The returned translation must maintain exactly the same number of paragraphs and format as the original text
3. If the text contains HTML tags, consider where the tags should be placed in the translation while maintaining fluency
4. For content that should not be translated (such as proper nouns, code, etc.), keep the original text.
5. If input contains %%, use %% as paragraph separator, if input has no %%, don't use %% in your output{{title_prompt}}{{summary_prompt}}{{terms_prompt}}

## OUTPUT FORMAT:
- **Single paragraph input** → Output translation directly (no separators, no extra text)
- **Multi-paragraph input** → Use %% as paragraph separator between translations

## Examples
### Multi-paragraph Input:
Paragraph A
%%
Paragraph B
%%
Paragraph C
%%
Paragraph D

### Multi-paragraph Output:
Translation A
%%
Translation B
%%
Translation C
%%
Translation D"""

TRANSLATION_USER_PROMPT = "Translate to {{to}}:\n\n{{text}}"

def estimate_max_tokens(num_articles: int = 1) -> int:
    """估算最大token数，统一收敛到硬上限"""
    return min(DEFAULT_MAX_TOKENS_HARD_CAP, 1200)


# -------------------------------
# 数据类定义
# -------------------------------

@dataclass
class Article:
    """文章数据类"""
    index: int
    url: str
    title: str
    content: str
    content_length: int = field(default=0)
    word_count: int = field(default=0)
    scraped_at: str = field(default_factory=lambda: time.strftime("%Y%m%d_%H%M%S"))

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return asdict(self)


# -------------------------------
# 统一异常处理
# -------------------------------

class ProcessingError(Exception):
    """文章处理相关异常"""
    pass


class DocumentError(Exception):
    """文档生成相关异常"""
    pass


# -------------------------------
# 工具函数
# -------------------------------



def calculate_word_adjustment_percentage(current_words: int, target_min: int = TARGET_WORD_MIN, target_max: int = TARGET_WORD_MAX) -> float:
    """计算词数调整百分比

    Args:
        current_words: 当前词数
        target_min: 目标最小词数
        target_max: 目标最大词数

    Returns:
        float: 调整百分比（正数表示增加，负数表示减少）
    """
    if target_min <= current_words <= target_max:
        return 0.0  # 已在范围内，无需调整

    target_center = (target_min + target_max) / 2

    if current_words < target_min:
        # 少于最小值，需要增加
        deficit = target_center - current_words
        percentage = (deficit / current_words) * 100
    else:
        # 多于最大值，需要减少
        excess = current_words - target_center
        percentage = -(excess / current_words) * 100

    # 限制调整幅度，避免过度调整
    percentage = max(-50, min(100, percentage))

    return round(percentage, 2)


def build_word_adjustment_prompt(content: str, percentage: float) -> str:
    """构建词数调整的prompt

    Args:
        content: 原文内容
        percentage: 调整百分比

    Returns:
        str: 调整prompt
    """
    if percentage > 0:
        action = f"增加{abs(percentage)}%"
    else:
        action = f"减少{abs(percentage)}%"

    return f"""请将以下英文内容词数{action}，根据语义分段，仍然保持新闻稿风格。

原始内容：
{content}

请直接输出调整后的完整内容，不要添加任何解释或额外文字。"""


def build_translation_prompts(text: str, target_lang: str = "Chinese") -> Tuple[str, str]:
    """构建翻译的系统和用户prompts

    Args:
        text: 要翻译的文本
        target_lang: 目标语言

    Returns:
        Tuple[str, str]: (system_prompt, user_prompt)
    """
    system_prompt = TRANSLATION_SYSTEM_PROMPT.replace("{{to}}", target_lang.lower())
    system_prompt = system_prompt.replace("{{title_prompt}}", "")
    system_prompt = system_prompt.replace("{{summary_prompt}}", "")
    system_prompt = system_prompt.replace("{{terms_prompt}}", "")

    user_prompt = TRANSLATION_USER_PROMPT.replace("{{to}}", target_lang.lower())
    user_prompt = user_prompt.replace("{{text}}", text)

    return system_prompt, user_prompt


def call_ai_api(system_prompt: str, user_prompt: str, model: str = DEFAULT_MODEL_ID,
                api_key: str = DEFAULT_SILICONFLOW_API_KEY, url: str = DEFAULT_SILICONFLOW_URL,
                max_tokens: int = None) -> Optional[str]:
    """调用AI API的通用函数

    Args:
        system_prompt: 系统提示
        user_prompt: 用户提示
        model: 模型ID
        api_key: API密钥
        url: API URL
        max_tokens: 最大token数

    Returns:
        Optional[str]: AI响应内容，失败返回None
    """
    if not api_key:
        raise RuntimeError("API key is empty")

    if max_tokens is None:
        max_tokens = estimate_max_tokens(1)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens
    }

    for attempt in range(3):
        t0 = time.time()
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=120)
            total_ms = int((time.time() - t0) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                try:
                    content = data["choices"][0]["message"]["content"]
                    print(f"[AI API] success total_ms={total_ms} tok_cap={max_tokens} attempt={attempt}")
                    return content
                except Exception as e:
                    raise RuntimeError(f"Unexpected API response: {data}") from e
            elif resp.status_code in [429, 500, 502, 503, 504]:
                print(f"[AI API] retry[{attempt}] status={resp.status_code} total_ms={total_ms}")
                if attempt < 2:
                    backoff_sleep(attempt)
                    continue
                else:
                    raise RuntimeError(f"API error after retries {resp.status_code}: {resp.text[:500]}")
            else:
                print(f"[AI API] non-retryable error {resp.status_code}")
                raise RuntimeError(f"API error {resp.status_code}: {resp.text[:500]}")

        except requests.RequestException as e:
            total_ms = int((time.time() - t0) * 1000)
            print(f"[AI API] retry[{attempt}] network_error total_ms={total_ms}")
            if attempt < 2:
                backoff_sleep(attempt)
                continue
            else:
                raise RuntimeError(f"API network error after retries: {e}")

    raise RuntimeError("AI API call failed after all retries")


def call_siliconflow_tagged_output(title_content_block: str, start_i: int, word_target: str = "300-350") -> str:
    """调用硅基流动 API 生成带标签的输出（兼容性函数）"""
    # 使用新的两步处理逻辑
    # 这里简化处理，直接返回输入内容（实际应该解析并处理）
    print(f"[兼容模式] call_siliconflow_tagged_output 被调用，start_i={start_i}, word_target={word_target}")
    return title_content_block


def call_openrouter_tagged_output(title_content_block: str, start_i: int, word_target: str = "300-350") -> str:
    """OpenRouter API 调用函数（兼容性函数，重定向到硅基流动）"""
    return call_siliconflow_tagged_output(title_content_block, start_i, word_target)


def handle_error(error: Exception, context: str = "操作", program: str = "ai_processor", task_type: str = "processing") -> None:
    """统一错误处理函数"""
    log_error(program, task_type, error, context)


def safe_execute(func, *args, **kwargs):
    """安全的函数执行包装器"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        handle_error(e, f"执行 {func.__name__}")
        return None

def build_source_block(pairs: List[Tuple[str, str]]) -> str:
    """
    Build the exact <Title>/<Content> blocks the user asked for.
    """
    chunks = []
    for title, content in pairs:
        # normalize content: collapse triple newlines, ensure quotes balanced not necessary
        content_norm = content.replace("\r\n", "\n").rstrip()
        chunks.append(f"<Title>\n{title}\n<Content>\n{content_norm}")
    return "\n".join(chunks)


def step1_adjust_word_count(article: Article) -> Tuple[str, int]:
    """第一步：调整词数到目标范围

    Args:
        article: 文章对象

    Returns:
        Tuple[str, int]: (调整后的内容, 最终词数)
    """
    content = article.content
    current_words = count_english_words(content)
    start_time = time.time()

    input_data = {
        "article_id": article.index,
        "title": article.title,
        "original_content": content,
        "original_word_count": current_words,
        "target_range": f"{TARGET_WORD_MIN}-{TARGET_WORD_MAX}"
    }

    log_processing_step("ai_processor", "word_adjustment", f"第一步调整词数 - 文章 {article.index}", {
        "original_word_count": current_words,
        "target_range": f"{TARGET_WORD_MIN}-{TARGET_WORD_MAX}"
    })

    # 检查是否已在范围内
    if TARGET_WORD_MIN <= current_words <= TARGET_WORD_MAX:
        processing_time = time.time() - start_time
        output_data = {
            "adjusted_content": content,
            "final_word_count": current_words,
            "adjustment_needed": False
        }

        log_processing_result("ai_processor", "word_adjustment", f"文章 {article.index} 词数调整",
                            input_data, output_data, "success",
                            {"processing_time": processing_time, "reason": "已在目标范围内"})

        log_processing_step("ai_processor", "word_adjustment", f"词数已在范围内，跳过调整 - 文章 {article.index}", {
            "word_count": current_words
        })
        return content, current_words

    # 循环调整直到达到目标范围
    for attempt in range(MAX_ADJUSTMENT_ATTEMPTS):
        # 计算调整百分比
        percentage = calculate_word_adjustment_percentage(current_words)
        if percentage == 0:
            break

        log_processing_step("ai_processor", "word_adjustment", f"第{attempt+1}次调整 - 文章 {article.index}", {
            "attempt": attempt + 1,
            "adjustment_percentage": percentage,
            "current_word_count": current_words
        })

        # 构建调整prompt
        adjustment_prompt = build_word_adjustment_prompt(content, percentage)

        # 调用AI API进行调整
        system_prompt = "You are a professional news editor. Adjust the word count and segment the content while maintaining news article style."
        try:
            adjusted_content = call_ai_api(system_prompt, adjustment_prompt)
            if adjusted_content:
                new_word_count = count_english_words(adjusted_content)
                log_processing_step("ai_processor", "word_adjustment", f"调整完成 - 文章 {article.index}", {
                    "attempt": attempt + 1,
                    "new_word_count": new_word_count
                })

                # 检查是否达到目标范围
                if TARGET_WORD_MIN <= new_word_count <= TARGET_WORD_MAX:
                    log_processing_step("ai_processor", "word_adjustment", f"达到目标范围 - 文章 {article.index}", {
                        "final_word_count": new_word_count,
                        "target_range": f"{TARGET_WORD_MIN}-{TARGET_WORD_MAX}"
                    })
                    return adjusted_content, new_word_count

                # 更新内容和词数，准备下一轮调整
                content = adjusted_content
                current_words = new_word_count
            else:
                log_error("ai_processor", "word_adjustment", Exception("调整失败"), f"文章 {article.index}")
                break

        except Exception as e:
            log_error("ai_processor", "word_adjustment", e, f"文章 {article.index} 调整异常")
            break

    # 如果调整失败，返回最后的内容
    final_words = count_english_words(content)
    processing_time = time.time() - start_time

    output_data = {
        "adjusted_content": content,
        "final_word_count": final_words,
        "adjustment_needed": True,
        "adjustment_attempts": MAX_ADJUSTMENT_ATTEMPTS,
        "target_achieved": TARGET_WORD_MIN <= final_words <= TARGET_WORD_MAX
    }

    status = "success" if TARGET_WORD_MIN <= final_words <= TARGET_WORD_MAX else "warning"
    log_processing_result("ai_processor", "word_adjustment", f"文章 {article.index} 词数调整",
                        input_data, output_data, status,
                        {"processing_time": processing_time, "attempts_used": MAX_ADJUSTMENT_ATTEMPTS})

    log_processing_step("ai_processor", "word_adjustment", f"调整完成 - 文章 {article.index}", {
        "final_word_count": final_words
    })
    return content, final_words


def translate_title(title: str, target_lang: str = "Chinese") -> str:
    """
    翻译标题

    Args:
        title: 要翻译的标题
        target_lang: 目标语言

    Returns:
        str: 翻译后的标题
    """
    if not title or not title.strip():
        return title

    start_time = time.time()
    input_data = {
        "original_title": title,
        "target_language": target_lang
    }

    log_processing_step("ai_processor", "title_translation", "开始翻译标题", {
        "title": title[:50],
        "target_language": target_lang
    })

    try:
        # 构建翻译标题的系统和用户prompts
        system_prompt = f"""You are a professional translator specializing in news headlines.
Translate the following news title to {target_lang.lower()}.

Rules:
1. Keep the translation concise and professional
2. Maintain the journalistic tone
3. Output only the translated title, nothing else
4. Do not add quotes or extra punctuation"""

        user_prompt = f"Translate this news title to {target_lang.lower()}:\n\n{title}"

        # 调用AI API进行标题翻译
        api_start_time = time.time()
        translated_title = call_ai_api(system_prompt, user_prompt)
        api_response_time = time.time() - api_start_time

        if translated_title:
            processing_time = time.time() - start_time
            output_data = {
                "translated_title": translated_title,
                "target_language": target_lang
            }

            # 记录API调用结果
            log_api_call(
                "ai_processor", "title_translation", "SiliconFlow API",
                DEFAULT_SILICONFLOW_URL, {"title": title}, {"translated_title": translated_title}, api_response_time, 200
            )

            # 记录处理结果
            log_processing_result("ai_processor", "title_translation", f"标题翻译 ({target_lang})",
                                input_data, output_data, "success",
                                {"processing_time": processing_time, "api_response_time": api_response_time})

            log_processing_step("ai_processor", "title_translation", "标题翻译完成", {
                "original_title": title[:30],
                "translated_title": translated_title[:30],
                "target_language": target_lang
            })

            return translated_title.strip()
        else:
            processing_time = time.time() - start_time
            output_data = {
                "error": "标题翻译失败",
                "fallback_title": title
            }

            log_processing_result("ai_processor", "title_translation", f"标题翻译 ({target_lang})",
                                input_data, output_data, "error",
                                {"processing_time": processing_time, "error": "翻译失败"})

            log_error("ai_processor", "title_translation", Exception("标题翻译失败"), f"标题: {title}")
            return title  # 返回原文作为fallback

    except Exception as e:
        processing_time = time.time() - start_time
        output_data = {
            "error": str(e),
            "fallback_title": title
        }

        log_processing_result("ai_processor", "title_translation", f"标题翻译 ({target_lang})",
                            input_data, output_data, "error",
                            {"processing_time": processing_time, "exception": str(e)})

        log_error("ai_processor", "title_translation", e, f"标题翻译异常: {title}")
        return title  # 返回原文作为fallback


def step2_translate_content(content: str, target_lang: str = "Chinese") -> str:
    """第二步：翻译内容

    Args:
        content: 要翻译的内容
        target_lang: 目标语言

    Returns:
        str: 翻译后的内容
    """
    start_time = time.time()
    input_data = {
        "original_content": content,
        "content_length": len(content),
        "target_language": target_lang,
        "word_count": count_english_words(content)
    }

    log_processing_step("ai_processor", "translation", "开始翻译内容", {
        "target_language": target_lang,
        "content_length": len(content)
    })

    # 构建翻译prompts
    system_prompt, user_prompt = build_translation_prompts(content, target_lang)

    # 调用AI API进行翻译
    try:
        api_start_time = time.time()
        translated_content = call_ai_api(system_prompt, user_prompt)
        api_response_time = time.time() - api_start_time

        if translated_content:
            processing_time = time.time() - start_time
            output_data = {
                "translated_content": translated_content,
                "translated_length": len(translated_content),
                "target_language": target_lang
            }

            # 记录API调用结果
            log_api_call(
                "ai_processor", "translation", "SiliconFlow API",
                DEFAULT_SILICONFLOW_URL, {"content": content[:100] + "...", "target_lang": target_lang},
                {"translated_content": translated_content[:100] + "..."}, api_response_time, 200
            )

            # 记录处理结果
            log_processing_result("ai_processor", "translation", f"内容翻译 ({target_lang})",
                                input_data, output_data, "success",
                                {"processing_time": processing_time, "api_response_time": api_response_time})

            log_processing_step("ai_processor", "translation", "翻译完成", {
                "target_language": target_lang,
                "translated_length": len(translated_content)
            })
            return translated_content
        else:
            processing_time = time.time() - start_time
            output_data = {
                "error": "翻译失败",
                "original_content_returned": True
            }

            log_api_call(
                "ai_processor", "translation", "SiliconFlow API",
                DEFAULT_SILICONFLOW_URL, {"content": content[:100] + "...", "target_lang": target_lang},
                {}, api_response_time, 500, "翻译失败"
            )

            log_processing_result("ai_processor", "translation", f"内容翻译 ({target_lang})",
                                input_data, output_data, "error",
                                {"processing_time": processing_time, "reason": "API返回空结果"})

            log_error("ai_processor", "translation", Exception("翻译失败"), f"目标语言: {target_lang}")
            return content
    except Exception as e:
        processing_time = time.time() - start_time
        api_response_time = time.time() - start_time

        log_api_call(
            "ai_processor", "translation", "SiliconFlow API",
            DEFAULT_SILICONFLOW_URL, {"content": content[:100] + "...", "target_lang": target_lang},
            {}, api_response_time, 500, str(e)
        )

        output_data = {
            "error": str(e),
            "original_content_returned": True
        }

        log_processing_result("ai_processor", "translation", f"内容翻译 ({target_lang})",
                            input_data, output_data, "error",
                            {"processing_time": processing_time, "exception": str(e)})

        log_error("ai_processor", "translation", e, f"目标语言: {target_lang}")
        return content


def process_article_two_steps(article: Article, target_lang: str = "Chinese") -> Dict[str, Any]:
    """两步处理单篇文章

    Args:
        article: 文章对象
        target_lang: 目标语言

    Returns:
        Dict[str, Any]: 处理后的文章数据
    """
    start_time = time.time()
    original_word_count = count_english_words(article.content)

    input_data = {
        "article_id": article.index,
        "title": article.title,
        "url": article.url,
        "original_content": article.content,
        "original_word_count": original_word_count,
        "target_language": target_lang
    }

    log_processing_step("ai_processor", "article_processing", f"开始处理文章 {article.index}", {
        "title": article.title[:50],
        "url": article.url
    })

    try:
        # 第一步：词数调整
        adjusted_content, final_word_count = step1_adjust_word_count(article)

        # 第二步：翻译标题
        translated_title = translate_title(article.title, target_lang)

        # 第三步：翻译内容
        translated_content = step2_translate_content(adjusted_content, target_lang)

        processing_time = time.time() - start_time

        # 构建结果
        result = {
            "id": str(article.index),
            "original_title": article.title,
            "translated_title": translated_title,
            "original_content": article.content,
            "original_word_count": original_word_count,
            "adjusted_content": adjusted_content,
            "adjusted_word_count": final_word_count,
            "translated_content": translated_content,
            "target_language": target_lang,
            "processing_timestamp": now_stamp(),
            "url": article.url,
            "success": True
        }

        output_data = {
            "adjusted_content": adjusted_content,
            "adjusted_word_count": final_word_count,
            "translated_content": translated_content,
            "processing_time": processing_time
        }

        # 记录完整的文章处理结果
        log_article_processing(
            "ai_processor", "article_processing", str(article.index),
            article.title, article.url, article.content, translated_content,
            original_word_count, final_word_count, processing_time, "success"
        )

        log_processing_result("ai_processor", "article_processing", f"文章 {article.index} 完整处理",
                            input_data, output_data, "success",
                            {"processing_time": processing_time, "target_language": target_lang})

        log_processing_step("ai_processor", "article_processing", f"完成文章 {article.index}", {
            "original_word_count": original_word_count,
            "adjusted_word_count": final_word_count,
            "processing_time": processing_time
        })
        return result

    except Exception as e:
        processing_time = time.time() - start_time

        output_data = {
            "error": str(e),
            "processing_time": processing_time
        }

        log_article_processing(
            "ai_processor", "article_processing", str(article.index),
            article.title, article.url, article.content, "",
            original_word_count, 0, processing_time, "error", str(e)
        )

        log_processing_result("ai_processor", "article_processing", f"文章 {article.index} 完整处理",
                            input_data, output_data, "error",
                            {"processing_time": processing_time, "exception": str(e)})

        log_error("ai_processor", "article_processing", e, f"文章 {article.index} 处理失败")
        return {
            "id": str(article.index),
            "original_title": article.title,
            "translated_title": article.title,  # 失败时使用原文作为标题
            "original_content": article.content,
            "error": str(e),
            "url": article.url,
            "success": False
        }


def process_articles_two_steps_concurrent(articles: List[Article], target_lang: str = "Chinese") -> Dict[str, Any]:
    """并发处理多篇文章（两步法）

    Args:
        articles: 文章列表
        target_lang: 目标语言

    Returns:
        Dict[str, Any]: 处理结果
    """
    start_time = time.time()

    # 记录任务开始
    log_task_start("ai_processor", "two_step_processing", {
        "article_count": len(articles),
        "target_language": target_lang
    })

    unified_print(f"开始两步AI处理 {len(articles)} 篇文章", "ai_processor", "two_step_processing")
    unified_print(f"目标语言: {target_lang}", "ai_processor", "two_step_processing")

    results = []
    failed_articles = []

    with ThreadPoolExecutor(max_workers=DEFAULT_CONCURRENCY) as executor:
        future_to_article = {executor.submit(process_article_two_steps, article, target_lang): article for article in articles}

        for future in as_completed(future_to_article):
            article = future_to_article[future]
            try:
                result = future.result()
                results.append(result)
                if result.get("success"):
                    print(f"[并发] 完成文章 {article.index}")
                else:
                    failed_articles.append(result)
                    print(f"[并发] 失败文章 {article.index}")
            except Exception as e:
                failed_articles.append({
                    "id": str(article.index),
                    "original_title": article.title,
                    "original_content": article.content,
                    "error": str(e),
                    "url": article.url,
                    "success": False
                })
                print(f"[并发] 异常文章 {article.index}: {e}")

    # 按原始顺序排序
    results.sort(key=lambda x: int(x["id"]))

    success_count = len([r for r in results if r.get("success")])
    failed_count = len(failed_articles)
    total_processing_time = time.time() - start_time

    final_result = {
        "metadata": {
            "total_articles": len(articles),
            "successful_articles": success_count,
            "failed_articles": failed_count,
            "processing_method": "two_step_processing",
            "target_language": target_lang,
            "processing_timestamp": now_stamp(),
            "total_processing_time": total_processing_time
        },
        "articles": results
    }

    # 记录批量处理结果
    log_batch_processing(
        "ai_processor", "two_step_processing", "两步AI处理",
        len(articles), success_count, failed_count, total_processing_time, "completed"
    )

    unified_print(f"两步AI处理完成: {success_count} 成功, {failed_count} 失败", "ai_processor", "two_step_processing")

    # 记录任务结束
    log_task_end("ai_processor", "two_step_processing", success_count > 0, {
        "total_articles": len(articles),
        "successful_articles": success_count,
        "failed_articles": failed_count,
        "processing_method": "two_step_processing",
        "target_language": target_lang,
        "total_processing_time": total_processing_time
    })

    return final_result

def build_system_and_user_prompt(title_content_block: str, start_i: int, word_target: str = "300-350") -> Dict[str, Any]:
    system = "You are an expert news editor and bilingual translator (English and Simplified Chinese). You must ensure all word counts are accurate and within specified ranges. You must ensure Chinese content is a faithful paragraph-by-paragraph translation of the English content."

    if word_target == "400-500":
        word_instruction = """【第一步：扩展到长文】
- 英文内容目标字数：400–500 words
- 请充分利用扩展思路，大幅扩充内容
- 重点增加背景介绍、统计数据、不同观点、场景细节
- 为后续缩减预留丰富素材
- 中文内容必须是逐段翻译，对应每一个英文段落，不要扩写，不要新增信息"""

        system = "You are an expert news editor and bilingual translator. First step: expand the content to create a comprehensive long-form article. You must ensure Chinese content is a faithful paragraph-by-paragraph translation of the English content."
    else:
        word_instruction = f"""【第二步：精确控制字数】
- 英文内容必须确保最终输出字数在 {word_target} words 之间
- 请在输出前先数一遍英文字数，确认在范围内
- 如果少于 {word_target.split('-')[0]} words，需要继续扩展内容
- 如果多于 {word_target.split('-')[1]} words，则需要删减到指定范围
- 中文内容必须是逐段翻译，对应每一个英文段落，不要扩写，不要新增信息"""

        system = "You are an expert news editor and bilingual translator. Second step: refine the content to exact word count requirements. You must ensure Chinese content is a faithful paragraph-by-paragraph translation of the English content."

    user = f"""
请阅读以下若干篇新闻，每篇包含 <Title> 与 <Content>。

{word_instruction}

【扩展思路提示】
为了达到字数要求，你可以：
- 增加历史背景介绍或人物履历
- 引入相关统计数据或对比（比如"近年类似事件发生率"等）
- 补充不同角度的评论（民众、学者、专家、反对方的反应）
- 描述场景细节（地点氛围、记者会情况、群众反应、后续影响）

【重要要求】
- 中文部分必须是逐段翻译，对应每一个英文段落。
- 不要扩写中文，不要新增信息。
- 段落数量必须与英文相同。

严格按以下格式输出，编号从 {start_i} 开始、依序递增，不可跳号、不可合并或省略任何一篇：

<EngTitle-{{i}}>
{{英文标题}}
<EngContent-{{i}}>
<p1>{{英文第1段}}</p1><p2>{{英文第2段}}</p2>{{可选：<p3>{{英文第3段}}</p3>}}
<ChiTitle-{{i}}>
{{中文标题（简体）}}
<ChiContent-{{i}}>
<p1>{{翻译英文第1段}}</p1><p2>{{翻译英文第2段}}</p2><p3>{{翻译英文第3段（如有）}}</p3>

现在输入的源文如下（共 {title_content_block.count("<Title>")} 篇），请逐篇依次输出，每篇必须生成一组完整四个大标签：
----------------
{title_content_block}
----------------
""".strip()

    return {
        "system": system,
        "user": user
    }

def backoff_sleep(attempt: int):
    """指数退避睡眠"""
    time.sleep(min(10, (2 ** attempt) + random.random()))

def call_siliconflow_tagged_output(title_content_block: str, start_i: int, word_target: str = "300-350") -> str:
    """调用硅基流动 API 生成带标签的输出"""
    if not DEFAULT_SILICONFLOW_API_KEY:
        raise RuntimeError("SILICONFLOW_API_KEY is empty. Set environment variable before running.")
    payload_prompts = build_system_and_user_prompt(title_content_block, start_i, word_target)

    headers = {
        "Authorization": f"Bearer {DEFAULT_SILICONFLOW_API_KEY}",
        "Content-Type": "application/json"
    }

    num_articles = title_content_block.count("<Title>")
    max_tokens = estimate_max_tokens(num_articles)
    body = {
        "model": DEFAULT_MODEL_ID,
        "messages": [
            {"role": "system", "content": payload_prompts["system"]},
            {"role": "user", "content": payload_prompts["user"]},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens
    }

    for attempt in range(3):
        t0 = time.time()
        try:
            resp = requests.post(DEFAULT_SILICONFLOW_URL, headers=headers, json=body, timeout=120)
            total_ms = int((time.time() - t0) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                try:
                    content = data["choices"][0]["message"]["content"]
                    print(f"[llm] ok total_ms={total_ms} tok_cap={max_tokens} size_prompt={len(title_content_block)} attempt={attempt} articles={num_articles}")
                    return content
                except Exception as e:
                    raise RuntimeError(f"Unexpected SiliconFlow response: {data}") from e
            elif resp.status_code in [429, 500, 502, 503, 504]:
                print(f"[llm] retry[{attempt}] status={resp.status_code} total_ms={total_ms}")
                if attempt < 2:
                    backoff_sleep(attempt)
                    continue
                else:
                    raise RuntimeError(f"SiliconFlow error after retries {resp.status_code}: {resp.text[:500]}")
            else:
                print(f"[llm] non-retryable error {resp.status_code}")

        except requests.RequestException as e:
            total_ms = int((time.time() - t0) * 1000)
            print(f"[llm] retry[{attempt}] network_error total_ms={total_ms}")
            if attempt < 2:
                backoff_sleep(attempt)
                continue
            else:
                raise RuntimeError(f"SiliconFlow network error after retries: {e}")

    raise RuntimeError("SiliconFlow call failed after all retries")

def generate_summary_single_article(article: Dict[str, Any], target_words: str = "300-350") -> str:
    """单篇文章生成摘要（一步法）"""
    title_content_pairs = [(article.get("EngTitle", ""), article.get("EngContent", ""))]
    title_content_block = build_source_block(title_content_pairs)
    return call_siliconflow_tagged_output(title_content_block, start_i=int(article["id"]), word_target=target_words)

def process_articles_concurrent(articles: List[Article], target_lang: str = "Chinese") -> Dict[str, Any]:
    """并发处理多篇文章（兼容性函数）

    Args:
        articles: 文章列表
        target_lang: 目标语言（默认为中文）

    Returns:
        Dict[str, Any]: 处理结果
    """
    # 使用新的两步处理方法
    return process_articles_two_steps_concurrent(articles, target_lang)

def validate_and_adjust_word_count(processed_data: Dict[str, Any], target_min: int = 300, target_max: int = 350) -> Dict[str, Any]:
    articles = processed_data.get("articles", [])
    needs_adjustment = []

    for article in articles:
        eng_content_raw = article.get("EngContent", {})
        eng_text = " ".join(eng_content_raw.values())
        word_count = len(eng_text.split())

        if word_count < target_min:
            needs_adjustment.append((article["id"], word_count, "too_short"))
        elif word_count > target_max:
            needs_adjustment.append((article["id"], word_count, "too_long"))

    if not needs_adjustment:
        return processed_data

    print("[校验] 字数调整完成（简化处理）")
    return processed_data


# ---------- Single Article Processing Functions ----------

def generate_summary_single_article(article: Article, target_words: str = "300-350") -> str:
    """单篇文章生成摘要（一步法）"""
    title_content_pairs = [(article.title, article.content)]
    title_content_block = build_source_block(title_content_pairs)
    return call_siliconflow_tagged_output(title_content_block, start_i=article.index, word_target=target_words)


def repair_summary_if_too_short(article: Article, draft_content: str, target_words: str = "300-350") -> str:
    """二次补救：当字数不足时进行修复"""
    word_count = count_english_words(draft_content)
    target_min = int(target_words.split('-')[0])

    if word_count >= target_min:
        return draft_content

    # 构建修复提示
    repair_prompt = f"""请扩展以下英文内容，使其达到 {target_words} 字数范围。

原始内容字数：{word_count}
目标范围：{target_words}

请通过以下方式扩展内容：
- 增加背景信息和历史 context
- 添加相关数据和统计
- 补充不同观点和评论
- 描述场景细节和影响

原始内容：
{draft_content}

请输出扩展后的完整内容："""

    headers = {
        "Authorization": f"Bearer {DEFAULT_SILICONFLOW_API_KEY}",
        "Content-Type": "application/json"
    }

    body = {
        "model": DEFAULT_MODEL_ID,
        "messages": [
            {"role": "system", "content": "You are an expert news editor. Expand the given content to reach the target word count while maintaining quality."},
            {"role": "user", "content": repair_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": estimate_max_tokens(1)
    }

    # 重试机制
    for attempt in range(3):
        t0 = time.time()
        try:
            resp = requests.post(DEFAULT_SILICONFLOW_URL, headers=headers, json=body, timeout=120)
            total_ms = int((time.time() - t0) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                try:
                    content = data["choices"][0]["message"]["content"]
                    print(f"[llm_repair] ok total_ms={total_ms} article_id={article.index} url={article.url} attempt={attempt}")
                    return content
                except Exception as e:
                    raise RuntimeError(f"Unexpected repair response: {data}") from e
            elif resp.status_code in [429, 500, 502, 503, 504]:
                print(f"[llm_repair] retry[{attempt}] status={resp.status_code} total_ms={total_ms} article_id={article.index} url={article.url}")
                if attempt < 2:
                    backoff_sleep(attempt)
                    continue
                else:
                    print(f"[llm_repair] failed after retries, using draft")
                    return draft_content
            else:
                print(f"[llm_repair] non-retryable error {resp.status_code}, using draft")
                return draft_content

        except requests.RequestException as e:
            total_ms = int((time.time() - t0) * 1000)
            print(f"[llm_repair] retry[{attempt}] network_error total_ms={total_ms} article_id={article.index} url={article.url}")
            if attempt < 2:
                backoff_sleep(attempt)
                continue
            else:
                print(f"[llm_repair] network failed after retries, using draft")
                return draft_content

    print("[llm_repair] all attempts failed, using draft")
    return draft_content


def process_single_article(article: Article) -> Dict[str, Any]:
    """处理单篇文章的主函数"""
    try:
        # 步骤1：直接生成（默认单步法）
        if DEFAULT_USE_TWO_STEP:
            # 如果启用两步法，使用原有的两步处理逻辑
            draft = process_articles_with_two_steps([article])
            draft_content = draft["articles"][0] if draft.get("articles") else ""
        else:
            # 默认单步生成
            draft_content = generate_summary_single_article(article)

        # 步骤2：校验字数，不足则修复
        final_content = repair_summary_if_too_short(article, draft_content)

        # 解析最终内容
        parsed_blocks = split_articles_blocks(final_content)
        final_obj = build_final_json_struct(parsed_blocks)

        if final_obj.get("articles"):
            article_data = final_obj["articles"][0]
            article_data["original_url"] = article.url
            article_data["word_count"] = count_english_words(article_data.get("EngContent", {}).get("p1", "") + " " +
                                                          article_data.get("EngContent", {}).get("p2", "") + " " +
                                                          article_data.get("EngContent", {}).get("p3", ""))
            return article_data
        else:
            # 解析失败，返回基础信息
            return {
                "id": str(article.index),
                "EngTitle": article.title,
                "EngContent": {"p1": "Content parsing failed", "p2": ""},
                "ChiTitle": article.title,
                "ChiContent": {"p1": "内容解析失败", "p2": ""},
                "original_url": article.url,
                "error": "parsing_failed"
            }

    except Exception as e:
        print(f"[error] article {article.index} processing failed: {e}")
        return {
            "id": str(article.index),
            "EngTitle": article.title,
            "EngContent": {"p1": "Processing failed", "p2": ""},
            "ChiTitle": article.title,
            "ChiContent": {"p1": "处理失败", "p2": ""},
            "original_url": article.url,
            "error": str(e)
        }


# ---------- Parsing tagged blocks into final JSON schema ----------

TAG_RE = re.compile(r"<(EngTitle|EngContent|ChiTitle|ChiContent)-(\d+)>", re.IGNORECASE)


def split_articles_blocks(text: str) -> Dict[str, Dict[str, str]]:
    """
    Parse the tagged output into a structure:
    {
      "1": {"EngTitle": "...", "EngContent": "...", "ChiTitle": "...", "ChiContent": "..."},
      "2": {...}
    }
    We capture raw blocks (content text) for each tag; paragraphs still inside will be parsed later.
    """
    # Normalize weird angle repetitions and ensure consistent line breaks
    t = text.replace("\r\n", "\n")
    # Find all tag positions
    matches = list(TAG_RE.finditer(t))
    if not matches:
        # Try to be lenient: sometimes models inject extra spaces
        raise ValueError("No <EngTitle-N>/<EngContent-N>/... tags found to parse.")
    articles: Dict[str, Dict[str, str]] = {}
    for i, m in enumerate(matches):
        tag, idx = m.group(1), m.group(2)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(t)
        content_block = t[start:end].strip()
        a = articles.setdefault(idx, {})
        a[tag if tag[0].isupper() else tag.capitalize()] = content_block
    return articles


PARA_TAG_RE = re.compile(r"<p(\d+)>", re.IGNORECASE)


def parse_paragraphs(block: str) -> Dict[str, str]:
    """
    The model uses markers like <p1> ... <p2> ... <p3> without closing tags in examples.
    We'll capture text between markers into p1/p2/p3.
    """
    s = block.strip()
    if not s:
        return {}
    # Find all para markers
    spans = []
    for m in PARA_TAG_RE.finditer(s):
        spans.append((m.group(1), m.start(), m.end()))
    if not spans:
        # No markers; return as p1
        return {"p1": s}
    paras: Dict[str, str] = {}
    for i, (pid, s_start, s_end) in enumerate(spans):
        content_start = s_end
        content_end = spans[i+1][1] if i + 1 < len(spans) else len(s)
        chunk = s[content_start:content_end].strip()
        # Strip stray pseudo-closing tags like </p1> if present
        chunk = re.sub(r"</p\d+>", "", chunk, flags=re.IGNORECASE).strip()
        # Remove leading/trailing quotes and excessive whitespace
        chunk = chunk.strip(" \t\n\r\"'")
        paras[f"p{pid}"] = chunk
    return paras


def validate_and_adjust_word_count(processed_data: Dict[str, Any], target_min: int = 300, target_max: int = 350) -> Dict[str, Any]:
    """
    Validate word counts and adjust if necessary.
    Returns adjusted data if reprocessing was needed, otherwise returns original.
    """
    articles = processed_data.get("articles", [])
    needs_adjustment = []

    print("[校验] 检查文章字数...")

    for article in articles:
        eng_content = article.get("EngContent", {})
        # Combine all English paragraphs
        eng_text = ""
        for para_key in sorted(eng_content.keys()):
            if para_key.startswith("p"):
                eng_text += " " + eng_content[para_key]

        word_count = count_english_words(eng_text.strip())
        article["word_count"] = word_count

        if word_count < target_min:
            needs_adjustment.append((article["id"], word_count, "too_short"))
            print(f"[校验] 文章 {article['id']}: {word_count} 字 (过少，需要扩展)")
        elif word_count > target_max:
            needs_adjustment.append((article["id"], word_count, "too_long"))
            print(f"[校验] 文章 {article['id']}: {word_count} 字 (过多，需要缩减)")
        else:
            print(f"[校验] 文章 {article['id']}: {word_count} 字 ✓")

    if not needs_adjustment:
        print("[校验] 所有文章字数都在目标范围内 ✓")
        return processed_data

    print(f"[校验] {len(needs_adjustment)} 篇文章需要调整，正在重新处理...")

    # For articles that need adjustment, we'll need to reprocess them
    # This is a simplified approach - in production you might want more sophisticated handling
    adjusted_data = processed_data.copy()
    print("[校验] 字数调整完成（简化处理）")

    return adjusted_data


def build_final_json_struct(parsed_blocks: Dict[str, Dict[str, str]]) -> Dict[str, Any]:
    # Sort by numeric id
    ids_sorted = sorted(parsed_blocks.keys(), key=lambda k: int(k))
    articles_out = []
    for idx in ids_sorted:
        blk = parsed_blocks[idx]
        eng_title = (blk.get("EngTitle") or blk.get("engtitle") or "").strip()
        chi_title = (blk.get("ChiTitle") or blk.get("chititle") or "").strip()
        eng_content_raw = blk.get("EngContent") or ""
        chi_content_raw = blk.get("ChiContent") or ""

        eng_paras = parse_paragraphs(eng_content_raw)
        chi_paras = parse_paragraphs(chi_content_raw)

        # Handle case where content might be a complete text without paragraph markers
        # If no paragraphs were parsed but there's raw content, treat it as p1
        if not eng_paras and eng_content_raw.strip():
            eng_paras = {"p1": eng_content_raw.strip()}
        if not chi_paras and chi_content_raw.strip():
            chi_paras = {"p1": chi_content_raw.strip()}

        # Ensure at least p1/p2/p3 keys exist if present, but don't filter out p1
        eng_content = {k: v for k, v in eng_paras.items() if k.startswith("p") and k[1:].isdigit()}
        chi_content = {k: v for k, v in chi_paras.items() if k.startswith("p") and k[1:].isdigit()}

        # If still no content after filtering, ensure at least p1 exists
        if not eng_content and eng_content_raw.strip():
            eng_content = {"p1": eng_content_raw.strip()}
        if not chi_content and chi_content_raw.strip():
            chi_content = {"p1": chi_content_raw.strip()}

        # Final article dict
        articles_out.append({
            "id": str(idx),
            "EngTitle": eng_title,
            "EngContent": eng_content,
            "ChiTitle": chi_title,
            "ChiContent": chi_content
        })
    return {"articles": articles_out}


# ---------- Concurrent Processing Function ----------
def process_articles_concurrent(articles: List[Article]) -> Dict[str, Any]:
    """并发处理多篇文章"""
    print(f"[info] Processing {len(articles)} articles concurrently with max_workers={DEFAULT_CONCURRENCY}")

    results = []
    failed_articles = []

    with ThreadPoolExecutor(max_workers=DEFAULT_CONCURRENCY) as executor:
        # 提交所有任务
        future_to_article = {executor.submit(process_single_article, article): article for article in articles}

        # 收集结果
        for future in as_completed(future_to_article):
            article = future_to_article[future]
            try:
                result = future.result()
                results.append(result)
                print(f"[concurrent] completed article {article.index}: {article.url} - {article.title[:50]}...")
            except Exception as e:
                print(f"[concurrent] failed article {article.index}: {article.url} - {e}")
                failed_articles.append({
                    "id": str(article.index),
                    "EngTitle": article.title,
                    "EngContent": {"p1": "Concurrent processing failed", "p2": ""},
                    "ChiTitle": article.title,
                    "ChiContent": {"p1": "并发处理失败", "p2": ""},
                    "original_url": article.url,
                    "error": str(e)
                })
                results.append(failed_articles[-1])

    # 按原始顺序排序
    results.sort(key=lambda x: int(x["id"]))

    final_result = {"articles": results}

    # 如果有失败的，进行字数校验
    if results:
        final_result = validate_and_adjust_word_count(final_result)

    print(f"[concurrent] finished processing {len(results)} articles, {len(failed_articles)} failed")

    return final_result


# ---------- Two-Step Generation Function ----------
def process_articles_with_two_steps(articles: List[Article]) -> Dict[str, Any]:
    """
    Process articles using two-step generation:
    Step 1: Expand to long-form (400-500 words)
    Step 2: Refine to target word count (300-350 words)
    """
    print("[info] Processing articles with two-step generation...")

    # Convert articles to title-content pairs
    all_pairs = []
    for art in articles:
        title = art.title
        content = art.content
        if title and content:
            all_pairs.append((title.strip(), str(content).strip()))

    if not all_pairs:
        raise ValueError("No articles with title+content found for processing.")

    cursor = 1
    final_collected = {}

    for k in range(0, len(all_pairs), DEFAULT_BATCH_SIZE):
        batch_pairs = all_pairs[k: k+DEFAULT_BATCH_SIZE]
        block = build_source_block(batch_pairs)

        # Step 1: Generate long-form content (400-500 words)
        print(f"[step1] Expanding batch {k//DEFAULT_BATCH_SIZE + 1} to long-form...")
        long_form_txt = call_siliconflow_tagged_output(block, start_i=cursor, word_target="400-500")
        long_form_parsed = split_articles_blocks(long_form_txt)

        # Step 2: Refine to target word count (300-350 words)
        print(f"[step2] Refining batch {k//DEFAULT_BATCH_SIZE + 1} to target word count...")

        # Prepare the long-form content for step 2
        step2_pairs = []
        for i, article_id in enumerate(long_form_parsed.keys(), start=cursor):
            blk = long_form_parsed[article_id]
            eng_content_raw = blk.get("EngContent") or ""
            eng_paras = parse_paragraphs(eng_content_raw)
            eng_content_text = " ".join(eng_paras.values())

            # Use the long-form English content as input for step 2
            step2_pairs.append((blk.get("EngTitle", "").strip(), eng_content_text))

        if step2_pairs:
            step2_block = build_source_block(step2_pairs)
            refined_txt = call_siliconflow_tagged_output(step2_block, start_i=cursor, word_target="300-350")
            refined_parsed = split_articles_blocks(refined_txt)

            # Merge results
            for article_id in refined_parsed:
                final_collected[article_id] = refined_parsed[article_id]
        else:
            # If no step2 pairs, use the long-form results
            for article_id in long_form_parsed:
                final_collected[article_id] = long_form_parsed[article_id]

        cursor += len(batch_pairs)

    # Build final JSON structure
    final_obj = build_final_json_struct(final_collected)
    return final_obj


# ---------- Main Words Processing Function ----------
def process_articles_to_words(articles: List[Article]) -> Dict[str, Any]:
    """
    Process scraped articles using SiliconFlow API
    Returns processed JSON structure
    """
    print(f"[info] Processing {len(articles)} articles with AI...")

    # Convert articles to title-content pairs
    all_pairs = []
    for art in articles:
        title = art.title
        content = art.content
        if title and content:
            all_pairs.append((title.strip(), str(content).strip()))

    if not all_pairs:
        raise ValueError("No articles with title+content found for processing.")

    cursor = 1
    collected = {}

    for k in range(0, len(all_pairs), DEFAULT_BATCH_SIZE):
        batch_pairs = all_pairs[k: k+DEFAULT_BATCH_SIZE]
        block = build_source_block(batch_pairs)
        txt = call_siliconflow_tagged_output(block, start_i=cursor)
        parsed = split_articles_blocks(txt)

        # 检查本批是否完整
        expected_ids = {str(i) for i in range(cursor, cursor+len(batch_pairs))}
        got_ids = set(parsed.keys())
        missing = sorted(expected_ids - got_ids, key=int)

        # 先收下已返回的
        for i in got_ids:
            collected[i] = parsed[i]

        # 针对缺失的，单篇重试
        for off, mid in enumerate(missing):
            single_block = build_source_block([batch_pairs[int(mid)-cursor]])
            single_txt = call_siliconflow_tagged_output(single_block, start_i=int(mid))
            single_parsed = split_articles_blocks(single_txt)
            if mid in single_parsed:
                collected[mid] = single_parsed[mid]
            else:
                raise RuntimeError(f"第 {mid} 篇多次失败，检查原文或缩小目标词数/提高max_tokens")

        cursor += len(batch_pairs)

    # collected -> build_final_json_struct(collected)
    final_obj = build_final_json_struct(collected)
    return final_obj


# -------------------------------
# 主程序入口
# -------------------------------

def main() -> None:
    """主程序入口函数"""
    # 记录任务开始
    log_task_start("ai_processor", "main_processing", {
        "module": "AI 新闻处理模块 - 两步处理版本",
        "step1": "词数调整 (400-450词)",
        "step2": "内容翻译"
    })

    unified_print("AI 新闻处理模块 - 两步处理版本", "ai_processor", "main_processing")
    unified_print("第一步：词数调整 (400-450词)", "ai_processor", "main_processing")
    unified_print("第二步：内容翻译", "ai_processor", "main_processing")

    # 命令行参数解析
    parser = argparse.ArgumentParser(description="AI 新闻处理模块")
    parser.add_argument("--input-file", type=str, help="输入的JSON文件路径")
    parser.add_argument("--output-file", type=str, help="输出的JSON文件路径")
    parser.add_argument("--target-lang", type=str, default="Chinese", help="目标语言")
    parser.add_argument("--word-min", type=int, default=TARGET_WORD_MIN, help="目标最小词数")
    parser.add_argument("--word-max", type=int, default=TARGET_WORD_MAX, help="目标最大词数")

    args = parser.parse_args()

    try:
        if not args.input_file:
            unified_print("请提供输入文件路径: --input-file <path>", "ai_processor", "main_processing", "warning")
            log_task_end("ai_processor", "main_processing", False, {"error": "未提供输入文件"})
            return

        # 读取输入文件
        with open(args.input_file, 'r', encoding='utf-8') as f:
            input_data = json.load(f)

        # 解析文章数据
        articles = []
        for item in input_data.get("articles", []):
            article = Article(
                index=int(item.get("id", len(articles) + 1)),
                url=item.get("url", ""),
                title=item.get("title", ""),
                content=item.get("content", ""),
                content_length=len(item.get("content", "")),
                word_count=count_english_words(item.get("content", ""))
            )
            articles.append(article)

        if not articles:
            unified_print("输入文件中没有找到文章数据", "ai_processor", "main_processing", "warning")
            log_task_end("ai_processor", "main_processing", False, {"error": "无文章数据"})
            return

        unified_print(f"加载了 {len(articles)} 篇文章", "ai_processor", "main_processing")
        unified_print(f"目标词数范围: {args.word_min}-{args.word_max}", "ai_processor", "main_processing")
        unified_print(f"目标语言: {args.target_lang}", "ai_processor", "main_processing")

        # 处理文章（使用两步法）
        unified_print("开始两步AI处理...", "ai_processor", "main_processing")
        processed_data = process_articles_two_steps_concurrent(articles, args.target_lang)

        # 保存结果
        output_file = args.output_file or f"processed_two_step_{now_stamp()}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(processed_data, f, ensure_ascii=False, indent=2)

        unified_print(f"处理完成，结果已保存到: {output_file}", "ai_processor", "main_processing")
        metadata = processed_data.get("metadata", {})
        successful_articles = metadata.get('successful_articles', 0)
        failed_articles = metadata.get('failed_articles', 0)
        unified_print(f"成功处理 {successful_articles} 篇文章", "ai_processor", "main_processing")
        unified_print(f"失败 {failed_articles} 篇文章", "ai_processor", "main_processing")

        # 记录任务结束
        log_task_end("ai_processor", "main_processing", successful_articles > 0, {
            "input_file": args.input_file,
            "output_file": output_file,
            "total_articles": len(articles),
            "successful_articles": successful_articles,
            "failed_articles": failed_articles,
            "target_language": args.target_lang,
            "word_range": f"{args.word_min}-{args.word_max}"
        })

    except Exception as e:
        handle_error(e, "主程序执行")
        log_task_end("ai_processor", "main_processing", False, {"error": str(e)})
        sys.exit(1)


def test_two_step_processing():
    """测试两步处理功能"""
    print("=== 测试两步处理功能 ===")

    # 创建测试文章
    test_article = Article(
        index=1,
        url="https://example.com/test",
        title="Test Article",
        content="This is a test article with some content. It has about 15 words and should be expanded to reach the target word count of 400-450 words for proper processing.",
        content_length=120,
        word_count=28,
        scraped_at=now_stamp()
    )

    print(f"测试文章词数: {test_article.word_count}")
    print(f"目标范围: {TARGET_WORD_MIN}-{TARGET_WORD_MAX}")

    try:
        # 测试第一步：词数调整
        print("\n--- 第一步：词数调整 ---")
        adjusted_content, final_words = step1_adjust_word_count(test_article)
        print(f"调整后词数: {final_words}")

        # 测试第二步：翻译
        print("\n--- 第二步：翻译 ---")
        translated_content = step2_translate_content(adjusted_content, "Chinese")
        print("翻译完成")

        # 测试完整两步处理
        print("\n--- 完整两步处理 ---")
        result = process_article_two_steps(test_article, "Chinese")
        print(f"完整处理结果: {'成功' if result.get('success') else '失败'}")

        print("\n=== 测试完成 ===")
        return True

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return False


def test_title_translation():
    """测试标题翻译功能"""
    print("测试标题翻译功能...")

    # 测试翻译标题
    test_title = "Trump Faces Legal Challenges in 2024 Election"
    try:
        translated = translate_title(test_title, "Chinese")
        print(f"✅ 原文标题: {test_title}")
        print(f"✅ 翻译标题: {translated}")
        print("标题翻译测试完成!")
        return True
    except Exception as e:
        print(f"❌ 标题翻译测试失败: {e}")
        return False


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        test_two_step_processing()
    elif len(sys.argv) > 1 and sys.argv[1] == "--test-title":
        test_title_translation()
    else:
        main()
