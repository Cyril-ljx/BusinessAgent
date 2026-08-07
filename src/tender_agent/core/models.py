"""核心数据模型(Pydantic)。"""
from pydantic import BaseModel, Field


class TitleInfo(BaseModel):
    """招标书标题信息"""
    title: str = Field(description="投标书完整标题,如'XX项目投标文件'")
    project_name: str = Field(default="", description="项目名称(去掉投标文件后缀)")
    tender_no: str = Field(default="", description="招标编号(如有)")
    purchaser: str = Field(default="", description="采购方/招标方完整名称")
