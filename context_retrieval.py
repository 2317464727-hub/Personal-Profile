"""Bounded, read-only retrieval of authorized local text files."""

import re

from file_tools import ROOTS, SKIP_DIRS, TEXT_SUFFIX, allowed, is_sensitive_name, os_walk, read_file
from project_tools import PROJECT_ROOT


STOP_WORDS = {"帮我", "看看", "一下", "这个", "那个", "什么", "怎么", "现在", "最近", "文件", "项目", "资料", "相关", "内容", "我的"}


def query_terms(query):
    words = re.findall(r"[\u3400-\u9fff]{2,}|[A-Za-z][A-Za-z0-9_-]{1,}", str(query or "")[:300])
    terms = []
    for word in words:
        if re.fullmatch(r"[\u3400-\u9fff]+", word):
            parts = [word] if len(word) <= 4 else []
            parts.extend(word[index:index + 2] for index in range(len(word) - 1))
        else:
            parts = [word.lower()]
        terms.extend(part for part in parts if part not in STOP_WORDS and part not in terms)
    return terms[:24]


def retrieve_files(query, scope):
    if scope not in ("files", "project"):
        return []
    terms = query_terms(query)
    if not terms:
        return []
    roots = [PROJECT_ROOT] if scope == "project" else ROOTS
    matches = []
    inspected = 0
    for root in roots:
        if not root.exists():
            continue
        for folder, dirs, names in os_walk(root):
            dirs[:] = [name for name in dirs if name.lower() not in SKIP_DIRS and not is_sensitive_name(name)]
            for name in names:
                if inspected >= 2500:
                    break
                inspected += 1
                if is_sensitive_name(name) or not (folder / name).suffix.lower() in TEXT_SUFFIX | {".docx"}:
                    continue
                path = folder / name
                try:
                    target = allowed(path)
                    if target.stat().st_size > 250_000:
                        continue
                    content = read_file(str(target), 12000)
                except (OSError, ValueError, ImportError):
                    continue
                if not isinstance(content, str):
                    continue
                name_lower = name.lower()
                content_lower = content.lower()
                found = [term for term in terms if term in content_lower or term in name_lower]
                if not found:
                    continue
                score = sum((4 if term in name_lower else 1) for term in found)
                score += 3 if str(query).strip().lower() in content_lower else 0
                at = min((content_lower.find(term) for term in found if term in content_lower), default=0)
                excerpt = content[max(0, at - 120):at + 650].strip()
                matches.append((score, str(target), excerpt))
            if inspected >= 2500:
                break
        if inspected >= 2500:
            break
    matches.sort(key=lambda item: (-item[0], item[1]))
    return [{"source": path, "excerpt": excerpt} for _score, path, excerpt in matches[:5]]
