"""
目录可视化渲染。

把 final_outline (层级树) 渲染成几种格式:
- Markdown: 给人看的(模拟 Word 目录效果)
- 缩进文本: 终端展示用
- 简化 JSON: 给后续阶段用

这样你不用等 Word 文档生成就能直观看到目录效果。
"""
def render_outline_markdown(outline: list[dict], title: str = "") -> str:
    """渲染成 Markdown 格式,模拟真实投标书目录页效果。

    输出示例:
        # 某服务外包项目投标文件

        ## 目  录

        1. 报价函及应答函
            1.1. 报价函
            1.2. 应答函
        2. 授权委托书
        3. 资格证明文件
            3.1. 营业执照
            3.2. 一般纳税人资格证明
        ...
    """
    lines = []
    if title:
        lines.append(f"# {title}\n")
    lines.append("## 目  录\n")

    # 非递归渲染，避免递归深度错误
    stack = []
    # 倒序入栈，保证出栈顺序正确
    for node in reversed(outline):
        stack.append((node, 0))

    while stack:
        node, depth = stack.pop()
        indent = "    " * depth
        name = node.get("name", "")
        node_id = node.get("id", "")

        # 用 "1.", "1.1." 之类的格式
        display_id = node_id if node_id else ""
        prefix = f"{display_id}. " if display_id else "• "

        lines.append(f"{indent}{prefix}{name}")

        # 子节点倒序入栈
        for child in reversed(node.get("children", [])):
            stack.append((child, depth + 1))

    return "\n".join(lines)


def render_outline_tree(outline: list[dict]) -> str:
    """终端友好的树形展示,带颜色标记。"""
    lines = []
    # 非递归渲染
    stack = []
    for node in reversed(outline):
        stack.append((node, 0))

    while stack:
        node, depth = stack.pop()
        indent = "  " * depth
        icon = "📌" if depth == 0 else "•"
        name = node.get("name", "")
        template = " [范本]" if node.get("has_template") else ""
        optional = " [可选]" if not node.get("required", True) else ""
        lines.append(f"{indent}{icon} {name}{template}{optional}")

        # 子节点倒序入栈
        for child in reversed(node.get("children", [])):
            stack.append((child, depth + 1))

    return "\n".join(lines)


def count_nodes(outline: list[dict]) -> dict:
    """统计目录节点数量。"""
    stats = {"total": 0, "by_level": {}, "with_template": 0, "required": 0}

    # 非递归遍历
    stack = []
    for node in outline:
        stack.append(node)

    while stack:
        node = stack.pop()
        stats["total"] += 1
        level = node.get("level", 1)
        stats["by_level"][level] = stats["by_level"].get(level, 0) + 1
        if node.get("has_template"):
            stats["with_template"] += 1
        if node.get("required", True):
            stats["required"] += 1

        # 子节点入栈
        for child in reversed(node.get("children", [])):
            stack.append(child)

    return stats
