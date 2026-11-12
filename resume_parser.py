"""Extract and sort resume text locally without sending it to a model."""

import io
import re
import zipfile


SECTIONS = {
    "summary": ("个人简介", "个人概况", "自我评价", "自我介绍", "职业概况", "Summary", "Profile"),
    "education": ("教育背景", "教育经历", "教育信息", "Education"),
    "experience": ("实习经历", "工作经历", "工作经验", "实习经验", "工作与实习经历", "实习/工作经历", "Experience", "Work Experience", "Internship Experience", "Internship"),
    "projects": ("项目经历", "项目经验", "项目实践", "个人项目", "科研项目", "Projects", "Project Experience"),
    "skills": ("专业技能", "技能特长", "技能清单", "技术能力", "技术栈", "Skills", "Technical Skills"),
}
FIELD_LIMITS = {"name": 60, "role": 100, "phone": 40, "email": 120, "city": 80, "summary": 3000, "education": 6000, "experience": 10000, "projects": 10000, "skills": 5000}
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
MONTH = r"20\d{2}(?:[./-]\d{1,2}(?:[./-]\d{1,2})?|年\d{1,2}月)"
PERIOD_RE = re.compile(rf"{MONTH}\s*(?:[—–\-~～至]|\bto\b)\s*(?:{MONTH}|至今|现在|present|current)", re.I)
EMPLOYER_RE = re.compile(r"^(.{2,60}?(?:有限责任公司|股份有限公司|有限公司|公司|集团|工作室|实验室|\bInc\.?|\bLtd\.?))(?=$|[\s｜|·/—–-])\s*[｜|·/—–-]*\s*(.*)$", re.I)
ROLE_RE = re.compile(r"实习|工程师|开发|设计师|产品经理|运营|助理|分析师|测试|研究员|intern|engineer|developer|designer|analyst", re.I)
BODY_PREFIX_RE = re.compile(r"^(?:[•●▪]|[-*]\s|\d{1,2}[.)、]\s*|项目介绍|项目背景|项目结果|主要负责|核心设计|工作内容|主要职责|负责|参与|完成|支持|使用|为.+(?:公司|集团))")


def clean_header(value):
    return value.strip(" \t｜|·—–-()（）")


def looks_like_role(value):
    value = clean_header(value)
    if not value or len(value) > 45 or not ROLE_RE.search(value):
        return False
    # A company website/system name is still a project, even if it ends in 开发.
    return not re.search(r"项目|系统|平台|官网|网站|工具|改造|重构", value) or bool(re.search(r"工程师|实习生|intern|engineer", value, re.I))


def entry_header(lines, index):
    """Read a short title/date/role header, never infer an employer from body text."""
    first = lines[index]
    if len(first) > 180 or BODY_PREFIX_RE.search(first):
        return None
    period = PERIOD_RE.search(first)
    title = clean_header(first[:period.start()] + " " + first[period.end():]) if period else first
    consumed = 1
    when = period.group(0) if period else ""
    if period and not title:
        if index + consumed >= len(lines):
            return None
        title = lines[index + consumed]
        consumed += 1
    if BODY_PREFIX_RE.search(title) or re.search(r"[。；;！？]", title):
        return None
    # Dates and job titles are often separate rows in PDF and DOCX tables.
    for _ in range(2):
        if index + consumed >= len(lines):
            break
        following = lines[index + consumed]
        if not when and PERIOD_RE.fullmatch(following.strip(" ()（）｜|")):
            when = following.strip(" ()（）｜|")
            consumed += 1
        elif EMPLOYER_RE.fullmatch(title) and not EMPLOYER_RE.fullmatch(title).group(2) and looks_like_role(following):
            title += "｜" + following
            consumed += 1
        else:
            break
    employer = EMPLOYER_RE.fullmatch(title)
    if employer and (not employer.group(2) or looks_like_role(employer.group(2))):
        name, role = employer.groups()
        if when or "实习" in role or re.search(r"\bintern\b", role, re.I):
            return {"title": name, "role": role, "period": when, "size": consumed, "employer": True, "certain": bool(role)}
    named_project = re.match(r"^(?:项目名称|项目[一二三四五六七八九十\d]+)\s*[:：]\s*(.+)$", title)
    if not when and not named_project:
        return None
    title = named_project.group(1) if named_project else title
    parts = re.split(r"\s*[｜|]\s*|\s+[—–]\s+", title, maxsplit=1)
    role = parts[1] if len(parts) > 1 else ""
    title = parts[0]
    if not role:
        match = re.match(r"^(.+?)\s+((?:AI\s*)?(?:应用开发|全栈开发|软件开发|后端开发|前端开发)(?:工程师|实习生)?)$", title)
        if match:
            title, role = match.groups()
    return {"title": title, "role": role, "period": when, "size": consumed, "employer": False, "certain": True}


def organize_entries(lines, source, destinations, recognition):
    """Classify complete entries, keeping all their original body lines together."""
    index = 0
    while index < len(lines):
        header = entry_header(lines, index)
        if not header:
            destinations[source].append(lines[index])
            index += 1
            continue
        end = index + header["size"]
        while end < len(lines) and not entry_header(lines, end):
            end += 1
        target = source
        if header["employer"] and header["certain"]:
            target = "experience"
        elif not source:
            # Without section titles, only unmistakable dated project titles are classified.
            target = "projects" if not header["employer"] and re.search(r"项目|系统|平台|工具|Agent|RAG", header["title"], re.I) else ""
        if header["employer"] and not header["certain"] and source != "experience":
            recognition["notes"].append("“%s”缺少明确岗位，已保留原分类，请核对。" % header["title"])
        title_line = header["title"] + ("｜" + header["role"] if header["role"] else "")
        if not header["employer"] and not header["period"]:
            title_line = "项目名称：" + title_line
        destinations[target].extend([title_line] + ([header["period"]] if header["period"] else []) + lines[index + header["size"]:end])
        if target:
            recognition["entries"].append({key: header[key] for key in ("title", "role", "period")} | {"kind": target})
        if target and source and target != source:
            recognition["notes"].append("已将“%s”按公司、岗位和时间归入实习 / 工作经历。" % header["title"])
        index = end


def extract_text(data, file_format):
    if not data or len(data) > 8_000_000:
        raise ValueError("简历文件需小于 8 MB")
    if file_format == "pdf":
        if not data.startswith(b"%PDF"):
            raise ValueError("文件不是有效的 PDF")
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            if len(reader.pages) > 20:
                raise ValueError("简历 PDF 最多支持 20 页")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("无法读取 PDF，请确认文件未加密或损坏") from exc
    elif file_format == "docx":
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise ValueError("文件不是有效的 DOCX")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if sum(item.file_size for item in archive.infolist()) > 30_000_000 or "word/document.xml" not in archive.namelist():
                raise ValueError("DOCX 内容过大或格式不正确")
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        try:
            document = Document(io.BytesIO(data))
            lines = []
            for child in document.element.body.iterchildren():
                if child.tag.endswith("}p"):
                    lines.append(Paragraph(child, document).text)
                elif child.tag.endswith("}tbl"):
                    table = Table(child, document)
                    for row in table.rows:
                        seen = set()
                        for cell in row.cells:
                            if cell._tc not in seen:
                                lines.extend(cell.text.splitlines())
                                seen.add(cell._tc)
            text = "\n".join(lines)
        except Exception as exc:
            raise ValueError("无法读取 DOCX，请确认文件未损坏") from exc
    elif file_format == "txt":
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = data.decode("gb18030")
            except UnicodeDecodeError as exc:
                raise ValueError("文本文件编码不受支持") from exc
    else:
        raise ValueError("仅支持 PDF、DOCX 和 TXT 简历")
    text = text.replace("\x00", "").strip()
    if len(text) < 20:
        raise ValueError("没有提取到足够的文字；扫描版 PDF 请先转换为可选中文字的文件")
    return text[:50_000]


def section_heading(line):
    candidate = re.sub(r"^[\s#\d一二三四五六七八九十.、)（）-]+", "", line).strip(" :：｜|—-\t【】[]")
    candidate = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", candidate)
    for key, aliases in SECTIONS.items():
        for alias in aliases:
            if candidate.casefold() == alias.casefold() or (candidate.casefold().startswith(alias.casefold() + " ") and len(candidate) < 35):
                return key, ""
            match = re.match(r"^" + re.escape(alias) + r"\s*[:：]\s*(.+)$", candidate, re.I)
            if match:
                return key, match.group(1).strip()
            if re.fullmatch(re.escape(alias) + r"\s*(?:[/|｜]\s*[A-Za-z ]+|[（(][A-Za-z ]+[）)])", candidate, re.I):
                return key, ""
    return "", ""


def parse_resume_text(text):
    lines = [re.sub(r"[\t ]+", " ", line).strip(" \t•●") for line in text.splitlines()]
    lines = [line for line in lines if line]
    fields = {key: "" for key in FIELD_LIMITS}
    sections = {key: [] for key in SECTIONS}
    unclassified = []
    current = ""

    explicit_name = re.search(r"(?:^|\n)\s*(?:姓名|Name)\s*[:：]\s*([^\n]{2,60})", text, re.I)
    if explicit_name:
        fields["name"] = re.split(r"\s+(?=电话|邮箱|性别|年龄|Phone|Email)", explicit_name.group(1).strip(), maxsplit=1, flags=re.I)[0]
    if not fields["name"]:
        table_name = re.search(r"(?:^|\n)\s*姓名\s+([\u4e00-\u9fff]{2,4})(?=\s|$)", text)
        if table_name:
            fields["name"] = table_name.group(1)
    role = re.search(r"(?:^|\n)\s*(?:求职意向|应聘岗位|目标职位|求职岗位)\s*[:：]\s*([^\n]{2,100})", text)
    if role:
        fields["role"] = role.group(1).strip()
    city = re.search(r"(?:^|\n)\s*(?:所在城市|现居地|现居城市|城市)\s*[:：]\s*([^\n]{2,80})", text)
    if city:
        fields["city"] = city.group(1).strip()
    email = EMAIL_RE.search(text)
    phone = PHONE_RE.search(text)
    fields["email"] = email.group(0) if email else ""
    fields["phone"] = phone.group(0) if phone else ""

    for line in lines:
        personal_heading = re.sub(r"\s+", "", line).strip(" :：#【】[]")
        if personal_heading in ("个人优势", "技能证书", "资格证书", "能力证书", "荣誉奖项", "获奖经历", "荣誉奖励"):
            current = "summary" if personal_heading == "个人优势" else "skills"
            sections[current].append(personal_heading)
            continue
        heading, inline = section_heading(line)
        if heading:
            current = heading
            if inline:
                sections[current].append(inline)
            continue
        if re.match(r"^(?:姓名|Name|求职意向|应聘岗位|目标职位|求职岗位|所在城市|现居地|现居城市|城市)\s*[:：]", line, re.I):
            continue
        if current:
            sections[current].append(line)
        else:
            unclassified.append(line)

    if not fields["name"]:
        for line in unclassified[:8]:
            if re.fullmatch(r"[\u4e00-\u9fff]{2,4}", line) and not section_heading(line)[0] and line not in ("个人简历", "求职简历"):
                fields["name"] = line
                break
    recognition = {"entries": [], "notes": []}
    destinations = {key: [] for key in SECTIONS}
    destinations[""] = []
    for source, entries in sections.items():
        if source in ("experience", "projects"):
            organize_entries(entries, source, destinations, recognition)
        else:
            destinations[source].extend(entries)
    organize_entries(unclassified, "", destinations, recognition)
    for key, entries in destinations.items():
        if key:
            fields[key] = "\n".join(entries)[:FIELD_LIMITS[key]]
    fields = {key: value[:FIELD_LIMITS[key]] for key, value in fields.items()}
    return {"fields": fields, "unclassified": "\n".join(destinations[""])[:6000], "line_count": len(lines), "recognition": recognition}


def parse_resume_bytes(data, file_format):
    return parse_resume_text(extract_text(data, file_format))
