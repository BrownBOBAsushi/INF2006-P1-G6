# Fixtures tests

Owner: Chuying. Synthetic data only; every name, email, phone, address and ID in these files is fictional.

## Evaluation dataset (ranking)

30 jobs, 10 profiles and 300 labels live in `../../data/evaluation/`; their integrity is tested by
`../analytics/test_evaluate.py`. These profiles deliberately contain no personal details.

## Synthetic resume PDFs (extraction / privacy pipeline)

`pdf/` holds 15 generated PDFs described in `pdf_manifest.json` (with sha256):

- `resume_P01.pdf` .. `resume_P10.pdf`: one-to-two-page text resumes built from `data/evaluation/profiles.json`,
  each with a fictional PII header (name, `@example.com` email, `+65 9000 00NN` phone, address with postal code 000000,
  `S00000NNZ` ID-style number, `example.com` profile link). The manifest lists the PII strings a privacy step must
  remove and the project/experience titles that must survive.
- `edge_unfamiliar_headings.pdf`: non-standard section headings (expects `unassigned_text` + `SECTION_REVIEW_NEEDED`).
- `edge_scanned_image_only.pdf`: picture of text, no text layer (expects `TEXT_REQUIRED`).
- `edge_encrypted.pdf`: needs a password; the public test value is in the manifest (expects `PDF_ENCRYPTED`).
- `edge_11_pages.pdf`: exceeds the 10-page limit.
- `edge_not_a_pdf.pdf`: plain text with a `.pdf` name (expects `PDF_REQUIRED`).

The "expected" outcomes are design intent from `DATA_API_CONTRACT.md`, **not measured behaviour**: the PDF
extraction, Presidio privacy and `/api/resume/prepare` pipeline does not exist yet. What *is* verified today is the
fixtures themselves: `test_pdf_fixtures.py` (19 tests) checks with pdfplumber that the valid PDFs have a text layer
containing the fictional PII and content, the scanned one has none, the encrypted one refuses to open, the page count
is 11, and regeneration is byte-identical (except the encrypted file). An oversize (> 5,242,880 byte) PDF is not
committed; generate it inside the test that needs it.

```bash
python -m pip install -r analytics/requirements.txt -r tests/fixtures/requirements-pdf.txt
python tests/fixtures/generate_pdf_fixtures.py     # regenerates tests/fixtures/pdf/ and pdf_manifest.json
python -m pytest tests/fixtures tests/analytics
```

Not yet created: `synthetic_jobs.json` for the catalogue importer.
