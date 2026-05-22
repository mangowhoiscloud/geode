"""Text-processing primitives shared across plugins (CSP-6, 2026-05-22).

Reusable building blocks (Jaccard similarity, n-gram shingles, …) that
multiple agents need to share. Hoisting them into ``core/`` removes the
plugin-to-plugin dependency that would otherwise let one plugin import a
helper out of a sibling plugin's internals.
"""
