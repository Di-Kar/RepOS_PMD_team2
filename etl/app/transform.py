"""Преобразование и валидация данных."""
import logging
import json
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

class DataTransformer:
    @staticmethod
    def _to_list(val: Any) -> List[str]:
        if isinstance(val, list): return [str(v) for v in val]
        if isinstance(val, str):
            try: return json.loads(val)
            except: return [val]
        return []

    @staticmethod
    def _to_obj_list(val: Any) -> List[Dict]:
        if isinstance(val, list): return val
        if isinstance(val, str):
            try: return json.loads(val)
            except: return []
        return []

    def transform(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        docs = []
        for row in rows:
            doc_id = str(row.get("id", ""))
            if not doc_id: continue

            doc = {
                "id": doc_id,
                "imdb_rating": float(row["imdb_rating"]) if row.get("imdb_rating") is not None else None,
                "genres": self._to_list(row.get("genres", [])),
                "title": str(row.get("title", "")),
                "description": str(row.get("description", "")),
                "actors_names": self._to_list(row.get("actors_names", [])),
                "actors": self._to_obj_list(row.get("actors", [])),
                "writers_names": self._to_list(row.get("writers_names", [])),
                "writers": self._to_obj_list(row.get("writers", [])),
                "directors_names": self._to_list(row.get("directors_names", [])),
                "directors": self._to_obj_list(row.get("directors", []))
            }
            docs.append({"_id": doc_id, **doc})
        logger.info(f"✅ Преобразовано {len(docs)} документов.")
        return docs
    