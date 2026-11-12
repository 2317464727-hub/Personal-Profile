import io
import unittest

from docx import Document
from pypdf import PdfWriter

from resume_parser import parse_resume_bytes, parse_resume_text


class ResumeParserTests(unittest.TestCase):
    def test_recognizes_contact_and_sections_without_inventing_missing_fields(self):
        text = """个人简历
张三
电话：13800138000  邮箱：zhang@example.com
求职意向：软件开发实习生
教育经历
某大学 计算机科学
工作经历
某公司 开发实习
完成接口联调
项目经历
库存工具
支持 CSV 导入
专业技能
Python、Docker
"""
        result = parse_resume_text(text)["fields"]
        self.assertEqual(result["name"], "张三")
        self.assertEqual(result["email"], "zhang@example.com")
        self.assertEqual(result["phone"], "13800138000")
        self.assertEqual(result["role"], "软件开发实习生")
        self.assertIn("某公司 开发实习", result["experience"])
        self.assertIn("支持 CSV 导入", result["projects"])
        self.assertEqual(result["city"], "")

    def test_docx_paragraphs_and_tables_are_extracted(self):
        document = Document()
        document.add_paragraph("姓名：李四")
        document.add_paragraph("教育背景")
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "某大学"
        table.cell(0, 1).text = "软件工程"
        document.add_paragraph("项目经历")
        document.add_paragraph("完成库存数据清洗与风险检查")
        output = io.BytesIO()
        document.save(output)
        fields = parse_resume_bytes(output.getvalue(), "docx")["fields"]
        self.assertEqual(fields["name"], "李四")
        self.assertIn("某大学", fields["education"])
        self.assertIn("库存数据清洗", fields["projects"])

    def test_inline_heading_and_table_style_name(self):
        text = "姓名 张三 电话 13800138000\n项目经历：库存工具\n完成 CSV 导入与风险诊断\n"
        fields = parse_resume_text(text)["fields"]
        self.assertEqual(fields["name"], "张三")
        self.assertIn("库存工具", fields["projects"])
        self.assertIn("风险诊断", fields["projects"])

    def test_english_section_heading(self):
        fields = parse_resume_text("Name: Alice Example\nPROJECTS: Inventory tool\nCSV import and validation\nSKILLS\nPython and Docker")["fields"]
        self.assertEqual(fields["name"], "Alice Example")
        self.assertIn("Inventory tool", fields["projects"])
        self.assertIn("Docker", fields["skills"])

    def test_image_only_pdf_has_clear_error(self):
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        output = io.BytesIO()
        writer.write(output)
        with self.assertRaisesRegex(ValueError, "扫描版 PDF"):
            parse_resume_bytes(output.getvalue(), "pdf")

    def test_rejects_unsupported_format(self):
        with self.assertRaisesRegex(ValueError, "仅支持 PDF"):
            parse_resume_bytes(b"this is a resume document", "doc")

    def test_company_with_role_under_projects_is_moved_as_a_complete_entry(self):
        text = """项目经历
2026.05-至今 RIOT Claude — 本地 AI Agent 系统 AI 应用开发
项目介绍：独立实现 Agent 执行循环。
2026.03 - 2026.05 金融保险 RAG 智能问答系统 AI 应用开发
核心设计：混合检索与重排。
2025.12 – 2026.03 山西滕浩科技有限公司 全栈开发
项目背景：参与智能求职 SaaS 平台开发。
主要负责：
 完成身份认证和 Redis 缓存优化；
 实现 2000+ 岗位数据入库；
项目结果：沉淀开发经验。
专业技能
熟悉 Python。
"""
        result = parse_resume_text(text)
        fields = result["fields"]
        self.assertIn("山西滕浩科技有限公司｜全栈开发\n2025.12 – 2026.03", fields["experience"])
        self.assertNotIn("山西滕浩", fields["projects"])
        for line in ("项目背景：参与智能求职 SaaS 平台开发。", " 完成身份认证和 Redis 缓存优化；", " 实现 2000+ 岗位数据入库；", "项目结果：沉淀开发经验。"):
            self.assertIn(line, fields["experience"])
        self.assertIn("RIOT Claude", fields["projects"])
        self.assertIn("金融保险 RAG 智能问答系统｜AI 应用开发", fields["projects"])
        self.assertEqual([entry["kind"] for entry in result["recognition"]["entries"]], ["projects", "projects", "experience"])
        self.assertIn("归入实习", result["recognition"]["notes"][0])

    def test_split_header_rows_and_company_followed_by_another_project(self):
        text = """项 目 经 历 / Projects
2025年12月～2026年3月
示例科技有限公司
后端开发实习生
完成接口联调。
库存风险系统
2026/04 至 2026/06
完成 CSV 导入。
"""
        fields = parse_resume_text(text)["fields"]
        self.assertIn("示例科技有限公司｜后端开发实习生", fields["experience"])
        self.assertNotIn("CSV", fields["experience"])
        self.assertIn("库存风险系统\n2026/04 至 2026/06\n完成 CSV 导入。", fields["projects"])

    def test_company_mentioned_in_project_body_is_not_an_employer_header(self):
        text = """项目经历
库存工具｜独立开发
2026.03—2026.05
项目介绍：为示例科技有限公司提供库存分析。
- 2026.04—2026.05 为示例科技有限公司完成接口联调。
2026.06—2026.08 示例科技有限公司｜官网重构项目
负责前端页面重构。
"""
        fields = parse_resume_text(text)["fields"]
        self.assertEqual(fields["experience"], "")
        self.assertIn("库存工具｜独立开发", fields["projects"])
        self.assertIn("官网重构项目", fields["projects"])
        self.assertIn("- 2026.04—2026.05", fields["projects"])

    def test_uncertain_company_keeps_its_source_and_requests_review(self):
        result = parse_resume_text("项目经历\n示例科技有限公司\n2026.01—2026.03\n需求调研与原型制作。")
        self.assertEqual(result["fields"]["experience"], "")
        self.assertIn("示例科技有限公司", result["fields"]["projects"])
        self.assertIn("缺少明确岗位", result["recognition"]["notes"][0])

    def test_company_without_section_title_and_no_guessed_role(self):
        fields = parse_resume_text("张三\n2026.01—2026.03 示例科技有限公司｜开发实习生\n完成服务端接口。\n其他备注")["fields"]
        self.assertIn("示例科技有限公司｜开发实习生", fields["experience"])
        self.assertEqual(fields["role"], "")

    def test_personal_sections_do_not_become_part_of_last_project(self):
        fields = parse_resume_text("项目经历\n项目名称：库存工具\n完成风险分析。\n荣誉奖项\n数学建模二等奖\n个人优势\n学习上：自学能力强。")["fields"]
        self.assertNotIn("奖", fields["projects"])
        self.assertIn("荣誉奖项\n数学建模二等奖", fields["skills"])
        self.assertIn("个人优势", fields["summary"])

    def test_multiline_docx_cells_preserve_header_boundaries(self):
        document = Document()
        document.add_paragraph("项目经历")
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).text = "示例科技有限公司\n后端开发实习生"
        table.cell(0, 1).text = "2026.01—2026.03"
        table.cell(1, 0).merge(table.cell(1, 1)).text = "主要负责：\n- 完成身份认证；\n- 完成接口联调。"
        output = io.BytesIO()
        document.save(output)
        result = parse_resume_bytes(output.getvalue(), "docx")
        self.assertIn("示例科技有限公司｜后端开发实习生", result["fields"]["experience"])
        self.assertEqual(result["fields"]["experience"].count("完成接口联调"), 1)


if __name__ == "__main__":
    unittest.main()
