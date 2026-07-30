"""One thin client per discovery source.

Each module exposes ``search(query, ...) -> Iterator[SourceRecord]`` and nothing
else. Sources disagree about everything — field names, date semantics, whether an
abstract is included, what a "type" is — so each client's only job is to turn its
own dialect into the common ``SourceRecord``. Reconciling the results is
``canonicalize.py``'s job, and judging them is ``relevance.py``'s.
"""
