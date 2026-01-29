"""
Lumina Studio - Statistics Module
使用统计功能
"""

import os
import tempfile


class Stats:
    """Usage statistics (local counter)"""
    _file = os.path.join(tempfile.gettempdir(), "lumina_stats.txt")

    @staticmethod
    def increment(key: str) -> int:
        data = Stats._load()
        data[key] = data.get(key, 0) + 1
        Stats._save(data)
        return data[key]

    @staticmethod
    def get_all() -> dict:
        return Stats._load()

    @staticmethod
    def reset_all():
        """Reset all statistics to zero."""
        empty_data = {"calibrations": 0, "extractions": 0, "conversions": 0}
        Stats._save(empty_data)
        return empty_data

    @staticmethod
    def _load() -> dict:
        try:
            with open(Stats._file, 'r') as f:
                lines = f.readlines()
                return {l.split(':')[0]: int(l.split(':')[1]) for l in lines if ':' in l}
        except:
            return {"calibrations": 0, "extractions": 0, "conversions": 0}

    @staticmethod
    def _save(data: dict):
        try:
            with open(Stats._file, 'w') as f:
                for k, v in data.items():
                    f.write(f"{k}:{v}\n")
        except:
            pass
