"""Fixed processing parameters. Values come from docs/handoff (MVP_PRD.md, ARCHITECTURE.md, DATA_API_CONTRACT.md)."""

# Embedding model: MVP_PRD.md "Initial model", pinned revision (verified 2026-09-20 on the Hugging Face Hub).
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_MODEL_REVISION = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
EMBEDDING_DIM = 384                      # vector(384) in resume_chunks / requirement_embeddings
CHUNKER_VERSION = "chunker-v1"           # bump when heading format or splitting rules change (invalidates vectors)

# Stored in resume_profiles.embedding_version / *.embedding_version. The API's ACTIVE_EMBEDDING_VERSION should equal this.
EMBEDDING_VERSION = f"{EMBEDDING_MODEL_NAME}@{EMBEDDING_MODEL_REVISION}/{CHUNKER_VERSION}"

# ARCHITECTURE.md / PRD: 240 tokenizer tokens including heading and special tokens.
MAX_INPUT_TOKENS = 240
MAX_CHUNKS_PER_PROFILE = 100             # DATA_API_CONTRACT resume_chunks safety cap

# ARCHITECTURE.md upload limits.
MAX_PDF_BYTES = 5_242_880
MAX_PDF_PAGES = 10
MIN_TEXT_CHARS = 40                      # non-whitespace characters below which a PDF counts as having no usable text
