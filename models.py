from typing import List, Optional, Dict, Any, Union
from pydantic import BaseModel

class Chunk(BaseModel):
    content: str
    lang: str = "es"
    metadata: Optional[Dict[str, Any]] = None

class Source(BaseModel):
    title: str
    content: str
    content_type: str
    source_id: Union[str, int]
    metadata: Optional[Dict[str, Any]] = None