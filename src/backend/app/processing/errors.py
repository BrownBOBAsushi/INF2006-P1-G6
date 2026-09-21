"""Processing errors. Codes are the contract's error codes (DATA_API_CONTRACT.md "Error envelope").

Messages here are fixed strings. They never contain parser exception text, file names or resume content, so a
caught ProcessingError can be logged and returned to the client safely.
"""
from __future__ import annotations

# code -> (HTTP status, fixed message). The API layer maps a ProcessingError onto its own error envelope.
CONTRACT_ERRORS: dict[str, tuple[int, str]] = {
    "FILE_TOO_LARGE": (413, "The file is larger than the 5 MiB limit."),
    "PDF_REQUIRED": (415, "Please upload a PDF file."),
    "PDF_ENCRYPTED": (422, "This PDF is password protected. Please upload an unprotected text PDF."),
    "PDF_UNREADABLE": (422, "This PDF could not be read. Please upload a valid text PDF of at most 10 pages."),
    "TEXT_REQUIRED": (422, "No text could be extracted. Scanned or image-only PDFs are not supported."),
    "INVALID_CONTENT": (422, "The resume content is not valid."),
    "REVIEW_REQUIRED": (422, "Privacy cleanup changed your resume. Please review the cleaned version and confirm again."),
    "INSUFFICIENT_RESUME_INFORMATION": (422, "Add at least one project or experience entry to get recommendations."),
    # Processing slot / child process (ARCHITECTURE.md "Processing topology and timeout"; contract "Error envelope")
    "PROCESSING_BUSY": (503, "Resume processing is busy. Please retry shortly."),
    "PROCESSING_TIMEOUT": (504, "Processing took too long and was stopped. Please try again."),
    "SERVICE_UNAVAILABLE": (503, "Processing is temporarily unavailable. Please try again later."),
    "INTERNAL_ERROR": (500, "Something went wrong while processing. Please try again."),
}

# Which codes the contract treats as retryable ("true for busy and transient infrastructure"). PROCESSING_TIMEOUT is
# treated as retryable here as transient infrastructure; the API owner may change this default.
RETRYABLE_CODES = frozenset({"PROCESSING_BUSY", "PROCESSING_TIMEOUT", "SERVICE_UNAVAILABLE"})
BUSY_RETRY_AFTER_SECONDS = 3            # contract: "Busy 503 PROCESSING_BUSY/Retry-After:3"


class ProcessingError(Exception):
    """A deterministic, safe-to-expose processing failure.

    `reason` is an internal enum-like string for tests and diagnostics (for example "page_limit"); it is never
    derived from input text.
    """

    def __init__(self, code: str, reason: str = ""):
        if code not in CONTRACT_ERRORS:
            raise ValueError(f"unknown error code {code!r}")
        self.code = code
        self.reason = reason
        self.status_code, self.message = CONTRACT_ERRORS[code]
        self.retryable = code in RETRYABLE_CODES
        self.retry_after_seconds = BUSY_RETRY_AFTER_SECONDS if code == "PROCESSING_BUSY" else None
        super().__init__(f"{code}:{reason}" if reason else code)


class TokenLimitError(ValueError):
    """Text would exceed the 240-token embedding input limit. Raised instead of truncating."""


class EmptyTextError(ValueError):
    """Empty or whitespace-only text cannot be embedded."""
