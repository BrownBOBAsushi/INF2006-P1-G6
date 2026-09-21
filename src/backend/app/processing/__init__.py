"""Resume processing: PDF extraction, privacy cleanup, section parsing, chunking and embeddings.

Owner: Chuying. Pure functions and small classes; no web framework, no database and no network access
at import time. API wiring (routes, auth, transactions) belongs to the API layer.
"""
import logging

# pdfminer logs raw document tokens (including resume text) at DEBUG, and presidio/pdfplumber are chatty. Cap them
# so that turning on root DEBUG logging can never write resume content to logs. Do not lower these levels.
for _name in ("pdfminer", "pdfplumber", "presidio-analyzer"):
    logging.getLogger(_name).setLevel(logging.WARNING)
