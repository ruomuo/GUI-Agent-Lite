"""
GUI Agent Memory System
结合 Generative Agents（三信号检索）、Voyager（技能库）、Reflexion（反思）的记忆系统
"""

import json
import time
import math
import os
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional


@dataclass
class TaskMemory:
    memory_id: str
    task_description: str
    action_sequence: List[Dict]
    success: bool
    timestamp: float
    last_accessed: float = 0.0
    poignancy: float = 5.0
    keywords: List[str] = field(default_factory=list)
    reflection: str = ""
    shortcut_actions: List[str] = field(default_factory=list)
    step_count: int = 0

    def age_hours(self) -> float:
        return (time.time() - self.timestamp) / 3600


class MemoryStore:
    def __init__(self, storage_path: str = "gui_agent_memory.json",
                 max_memories: int = 500):
        self.storage_path = storage_path
        self.max_memories = max_memories
        self.memories: Dict[str, TaskMemory] = {}
        self.seq: List[str] = []
        self.keyword_index: Dict[str, List[str]] = {}
        self.recency_decay = 0.995
        self._load()

    def add(self, memory: TaskMemory) -> str:
        self.memories[memory.memory_id] = memory
        self.seq.insert(0, memory.memory_id)
        for kw in memory.keywords:
            kl = kw.lower()
            if kl not in self.keyword_index:
                self.keyword_index[kl] = []
            self.keyword_index[kl].insert(0, memory.memory_id)
        if len(self.memories) > self.max_memories:
            self._evict()
        self._save()
        return memory.memory_id

    def retrieve(self, task_description: str, top_k: int = 5) -> List[TaskMemory]:
        candidates = set(self.memories.keys())
        if not candidates:
            return []

        query_words = set(self._extract_keywords(task_description))

        recency = {}
        for idx, mid in enumerate(self.seq):
            if mid in candidates:
                recency[mid] = self.recency_decay ** idx

        importance = {mid: self.memories[mid].poignancy for mid in candidates}

        relevance = {}
        for mid in candidates:
            mem = self.memories[mid]
            mem_words = set(kw.lower() for kw in mem.keywords)
            mem_words.update(mem.task_description.lower().split())
            overlap = len(query_words & mem_words)
            relevance[mid] = overlap / max(len(query_words), 1)

        recency = self._normalize(recency)
        importance = self._normalize(importance)
        relevance = self._normalize(relevance)

        scores = {}
        for mid in candidates:
            scores[mid] = (
                0.5 * recency.get(mid, 0)
                + 2.0 * relevance.get(mid, 0)
                + 1.5 * importance.get(mid, 0)
            )

        sorted_ids = sorted(scores, key=scores.get, reverse=True)[:top_k]
        now = time.time()
        for mid in sorted_ids:
            self.memories[mid].last_accessed = now
        return [self.memories[mid] for mid in sorted_ids]

    def get_context_for_task(self, task_description: str, max_chars: int = 1500) -> str:
        memories = self.retrieve(task_description, top_k=5)
        if not memories:
            return ""

        parts = ["[Past Experiences - 过去的经验]"]
        for mem in memories:
            if not mem.success and not mem.reflection:
                continue
            line = f"Task: {mem.task_description}"
            if mem.success and mem.shortcut_actions:
                line += f"\n  ✅ Shortcut: {' → '.join(mem.shortcut_actions[:6])}"
                line += f"\n  Steps: {mem.step_count}"
            elif mem.reflection:
                line += f"\n  ❌ Lesson: {mem.reflection[:200]}"
            parts.append(line)

            if len("\n".join(parts)) > max_chars:
                break

        result = "\n".join(parts)
        if len(result) < 50:
            return ""
        return result

    def add_reflection(self, memory_id: str, reflection: str):
        if memory_id in self.memories:
            self.memories[memory_id].reflection = reflection
            self._save()

    def learn_shortcut(self, memory_id: str, shortcut: List[str]):
        if memory_id in self.memories:
            self.memories[memory_id].shortcut_actions = shortcut
            self._save()

    def _extract_keywords(self, text: str) -> List[str]:
        stop_words = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人',
                      '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去',
                      '你', '会', '着', '没有', '看', '好', '自己', '这', '他', '她',
                      'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                      'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                      'would', 'could', 'should', 'may', 'might', 'can', 'shall',
                      'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him',
                      'her', 'us', 'them', 'my', 'your', 'his', 'its', 'our', 'their',
                      'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with',
                      'by', 'from', 'as', 'into', 'through', 'during', 'before', 'after',
                      '帮我', '请', '一下', '然后', '并且', '打开'}
        words = set()
        for w in text.lower().split():
            w = w.strip('.,!?;:()[]{}\"\'')
            if w and w not in stop_words and len(w) > 1:
                words.add(w)
        return list(words)

    def _normalize(self, d: Dict[str, float]) -> Dict[str, float]:
        if not d:
            return d
        min_v = min(d.values())
        max_v = max(d.values())
        r = max_v - min_v
        if r == 0:
            return {k: 0.5 for k in d}
        return {k: (v - min_v) / r for k, v in d.items()}

    def _evict(self):
        scored = []
        for idx, mid in enumerate(reversed(self.seq)):
            scored.append((mid, self.memories[mid].poignancy * (self.recency_decay ** idx)))
        scored.sort(key=lambda x: x[1])
        to_remove = scored[:len(self.memories) - self.max_memories]
        for mid, _ in to_remove:
            if mid in self.memories:
                del self.memories[mid]
            if mid in self.seq:
                self.seq.remove(mid)
            for kw in list(self.keyword_index.keys()):
                if mid in self.keyword_index[kw]:
                    self.keyword_index[kw].remove(mid)

    def _save(self):
        try:
            data = {
                "memories": {mid: asdict(mem) for mid, mem in self.memories.items()},
                "seq": self.seq,
                "keyword_index": self.keyword_index,
            }
            with open(self.storage_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _load(self):
        try:
            with open(self.storage_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for mid, mdata in data.get("memories", {}).items():
                self.memories[mid] = TaskMemory(**mdata)
            self.seq = data.get("seq", [])
            self.keyword_index = data.get("keyword_index", {})
        except (FileNotFoundError, json.JSONDecodeError):
            pass
