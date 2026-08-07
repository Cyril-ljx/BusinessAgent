"""LLM Prompt 模板。"""

TITLE_EXTRACTION_PROMPT = """从招标类文件的开头几页中,提取项目标题信息。

提取以下字段:
1. title: 完整标题(如"XX项目响应文件"、"XX磋商响应文件"、"XX比选申请书")
2. project_name: 项目名称(去掉"投标文件"、"响应文件"、"磋商文件"等后缀,只保留项目本身)
3. purchaser: 采购方/招标方完整名称

【内容】
{content}
"""
