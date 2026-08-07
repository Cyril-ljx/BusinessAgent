"""文档渲染层:把 outline JSON + 母版 → 投标书 docx。"""


def render_blank_bid(*args, **kwargs):
    """Lazy-load the DOCX renderer only when a Word file is actually rendered."""
    from .docx_renderer import render_blank_bid as _render_blank_bid

    return _render_blank_bid(*args, **kwargs)


__all__ = ["render_blank_bid"]
