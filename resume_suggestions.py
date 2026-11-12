"""Build reviewable resume drafts from recent work records locally."""

import re
from datetime import date


WORKSPACE_TARGET = {
    "agent": "projects",
    "inventory": "projects",
    "video": "projects",
    "skills": "skills",
    "listmonk": "projects",
    "personal": "projects",
    "pets": "projects",
}
WORKSPACE_LABEL = {
    "agent": "社交内容发布平台接入",
    "inventory": "库存风险工作台",
    "video": "视频生产",
    "skills": "业务技能整理",
    "listmonk": "邮件平台",
    "personal": "个人平台",
    "pets": "个人项目",
}
INTERNSHIP_WORKSPACES = {"agent", "inventory", "video", "skills", "listmonk"}
SECRET_RE = re.compile(
    r"sk-[A-Za-z0-9_-]{12,}|(?i:(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|密码|密钥)\s*[:=：]\s*)\S+"
)
URL_RE = re.compile(r"https?://[^\s，。；、)）]+", re.I)


def clean_text(value, limit):
    return URL_RE.sub("[链接已略]", SECRET_RE.sub("[已隐藏]", str(value or "").strip()))[:limit]


def prepare_request(body):
    if not isinstance(body, dict) or not isinstance(body.get("logs"), list):
        raise ValueError("请选择周历记录")
    if not 1 <= len(body["logs"]) <= 40:
        raise ValueError("每次请选择 1 到 40 条记录")
    if not isinstance(body.get("resume"), dict):
        raise ValueError("简历正文格式无效")
    logs = []
    seen = set()
    for item in body["logs"]:
        if not isinstance(item, dict):
            continue
        key = clean_text(item.get("id"), 100)
        try:
            day = date.fromisoformat(str(item.get("date") or ""))
        except ValueError:
            continue
        title = clean_text(item.get("title"), 120)
        if not key or not title or key in seen:
            continue
        seen.add(key)
        logs.append({
            "id": key,
            "date": str(day),
            "workspace": clean_text(item.get("workspace"), 40),
            "title": title,
            "body": clean_text(item.get("body"), 1400),
        })
    if not logs:
        raise ValueError("没有可用的周历记录")
    resume = {key: clean_text(body["resume"].get(key), 5000) for key in ("summary", "experience", "projects", "skills")}
    template = body.get("template", "")
    if template not in ("", "current-a4-v1"):
        raise ValueError("不支持的简历模板")
    return {"logs": logs, "resume": resume, "template": template}


def draft_suggestions(material):
    resume_text = re.sub(r"\s+", "", "\n".join(material["resume"].values()))
    grouped = {}
    seen = set()
    for item in sorted(material["logs"], key=lambda entry: entry["date"], reverse=True):
        title = item["title"].rstrip("。；:： ")
        detail = re.split(r"[。；\n]", item["body"], maxsplit=1)[0].strip("。；:： ")
        content = title if not detail or detail in title else title + "：" + detail
        content = clean_text(content, 220)
        signature = re.sub(r"\s+", "", content).casefold()
        if len(content) < 8 or signature in seen or signature in resume_text.casefold():
            continue
        seen.add(signature)
        grouped.setdefault(item["workspace"], []).append((item, title, detail, content))

    suggestions = []
    company_groups = {key: value for key, value in grouped.items() if key in INTERNSHIP_WORKSPACES}
    if company_groups:
        sections = ["北京四方小仓科技有限公司 Linker｜实习生", "2026.09 — 至今｜北京"]
        sources = []
        for workspace, entries in company_groups.items():
            entries = entries[:4]
            months = sorted({entry[0]["date"][:7].replace("-", ".") for entry in entries})
            when = months[0] if len(months) == 1 else months[0] + " — " + months[-1]
            sections.append(WORKSPACE_LABEL.get(workspace, "项目工作") + "（" + when + " 记录）")
            for record, _title, _detail, content in entries:
                sections.append("- " + content)
                sources.append(record["id"])
        suggestions.append({"target": "experience", "text": "\n".join(sections), "source_ids": sources, "structured": True})
        grouped = {key: value for key, value in grouped.items() if key not in INTERNSHIP_WORKSPACES}
    while grouped and len(suggestions) < 5:
        for workspace in list(grouped):
            entries = grouped[workspace][:3]
            grouped[workspace] = grouped[workspace][3:]
            if not grouped[workspace]:
                del grouped[workspace]
            target = WORKSPACE_TARGET.get(workspace, "experience")
            structured = material.get("template") == "current-a4-v1" and target in {"projects", "skills"}
            if structured:
                months = sorted({entry[0]["date"][:7].replace("-", ".") for entry in entries})
                when = months[0] if len(months) == 1 else months[0] + " — " + months[-1]
                lines = ["- " + entry[3] for entry in entries]
                text = "\n".join(["项目名称：" + WORKSPACE_LABEL.get(workspace, "项目工作"), when, "工作内容：", *lines]) if target == "projects" else "\n".join(lines)
            elif len(entries) == 1:
                text = entries[0][3]
            else:
                titles = list(dict.fromkeys(entry[1] for entry in entries))
                text = WORKSPACE_LABEL.get(workspace, "项目工作") + "：" + "、".join(titles)
                detail = next((entry[2] for entry in entries if entry[2] and entry[2] not in text), "")
                if detail:
                    text += "；" + detail[:70]
                text = clean_text(text, 220)
            if re.sub(r"\s+", "", text).casefold() not in resume_text.casefold():
                suggestion = {
                    "target": target,
                    "text": text,
                    "source_ids": [entry[0]["id"] for entry in entries],
                }
                if structured:
                    suggestion["structured"] = True
                suggestions.append(suggestion)
            if len(suggestions) == 5:
                break
    return suggestions
