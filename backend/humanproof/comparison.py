"""Document comparison engine for Mr Money AI."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class DiffSegment:
    change_type: str  # "equal", "insert", "delete", "replace"
    old_text: str
    new_text: str
    old_start: int = 0
    new_start: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "type": self.change_type,
            "old": self.old_text,
            "new": self.new_text,
            "oldStart": self.old_start,
            "newStart": self.new_start,
        }


@dataclass
class ComparisonResult:
    similarity_score: float
    old_word_count: int
    new_word_count: int
    insertions: int
    deletions: int
    replacements: int
    segments: List[DiffSegment]
    summary: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "similarityScore": self.similarity_score,
            "oldWordCount": self.old_word_count,
            "newWordCount": self.new_word_count,
            "insertions": self.insertions,
            "deletions": self.deletions,
            "replacements": self.replacements,
            "segments": [s.to_dict() for s in self.segments],
            "summary": self.summary,
        }


def compare_documents(old_text: str, new_text: str) -> ComparisonResult:
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)

    differ = difflib.unified_diff(old_lines, new_lines, lineterm="")
    segments: List[DiffSegment] = []
    insertions = 0
    deletions = 0
    replacements = 0

    old_pos = 0
    new_pos = 0

    for line in differ:
        if line.startswith("---") or line.startswith("+++") or line.startswith("@@"):
            continue
        if line.startswith("+"):
            text = line[1:]
            segments.append(DiffSegment("insert", "", text, old_pos, new_pos))
            new_pos += len(text)
            insertions += 1
        elif line.startswith("-"):
            text = line[1:]
            segments.append(DiffSegment("delete", text, "", old_pos, new_pos))
            old_pos += len(text)
            deletions += 1
        else:
            text = line
            segments.append(DiffSegment("equal", text, text, old_pos, new_pos))
            old_pos += len(text)
            new_pos += len(text)

    merged_segments = _merge_segments(segments)

    old_words = _word_count(old_text)
    new_words = _word_count(new_text)
    similarity = _calculate_similarity(old_text, new_text)

    total_changes = insertions + deletions
    if insertions > 0 and deletions > 0:
        replacements = min(insertions, deletions)

    summary = _generate_summary(similarity, old_words, new_words, insertions, deletions, replacements)

    return ComparisonResult(
        similarity_score=similarity,
        old_word_count=old_words,
        new_word_count=new_words,
        insertions=insertions,
        deletions=deletions,
        replacements=replacements,
        segments=merged_segments,
        summary=summary,
    )


def _merge_segments(segments: List[DiffSegment]) -> List[DiffSegment]:
    if not segments:
        return []
    merged: List[DiffSegment] = [segments[0]]
    for seg in segments[1:]:
        last = merged[-1]
        if last.change_type == seg.change_type:
            if seg.change_type == "insert":
                merged[-1] = DiffSegment("insert", "", last.new_text + seg.new_text, last.old_start, last.new_start)
            elif seg.change_type == "delete":
                merged[-1] = DiffSegment("delete", last.old_text + seg.old_text, "", last.old_start, last.new_start)
            else:
                merged[-1] = DiffSegment("equal", last.old_text + seg.old_text, last.new_text + seg.new_text, last.old_start, last.new_start)
        else:
            merged.append(seg)
    return merged


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _calculate_similarity(text1: str, text2: str) -> float:
    words1 = re.findall(r"\b\w+\b", text1.lower())
    words2 = re.findall(r"\b\w+\b", text2.lower())
    if not words1 and not words2:
        return 100.0
    if not words1 or not words2:
        return 0.0
    set1 = set(words1)
    set2 = set(words2)
    intersection = set1 & set2
    union = set1 | set2
    jaccard = len(intersection) / len(union) if union else 0
    ratio = difflib.SequenceMatcher(None, " ".join(words1), " ".join(words2)).ratio()
    return round((jaccard * 40 + ratio * 60), 1)


def _generate_summary(
    similarity: float,
    old_words: int,
    new_words: int,
    insertions: int,
    deletions: int,
    replacements: int,
) -> str:
    change_pct = 100 - similarity
    if change_pct < 5:
        desc = "nearly identical"
    elif change_pct < 20:
        desc = "mostly similar with minor changes"
    elif change_pct < 50:
        desc = "moderately different"
    else:
        desc = "significantly different"
    word_change = new_words - old_words
    word_desc = f"{'gained' if word_change > 0 else 'lost'} {abs(word_change)} words"
    return (
        f"The documents are {desc} ({similarity:.1f}% similar). "
        f"The newer version has {word_desc} with {insertions} insertion(s), "
        f"{deletions} deletion(s), and approximately {replacements} replacement(s)."
    )


def highlight_changes(old_text: str, new_text: str) -> str:
    old_words = old_text.split()
    new_words = new_text.split()
    sm = difflib.SequenceMatcher(None, old_words, new_words)
    parts = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            parts.append(" ".join(old_words[i1:i2]))
        elif tag == "replace":
            parts.append(f"<del>{' '.join(old_words[i1:i2])}</del>")
            parts.append(f"<ins>{' '.join(new_words[j1:j2])}</ins>")
        elif tag == "delete":
            parts.append(f"<del>{' '.join(old_words[i1:i2])}</del>")
        elif tag == "insert":
            parts.append(f"<ins>{' '.join(new_words[j1:j2])}</ins>")
    return " ".join(parts)
