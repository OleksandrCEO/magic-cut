"""magic-cut core — transcript and region detection.

transcribe.py  media          -> *.words.json   (expensive, GPU, once per video)
regions.py     *.words.json   -> region list    (cheap, stdlib, re-run freely)

Regions are "<start> <end>" seconds per line — the interchange format every consumer reads.
"""
