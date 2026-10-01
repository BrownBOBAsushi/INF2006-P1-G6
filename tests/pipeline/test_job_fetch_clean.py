"""Offline regressions for the live-job fetcher and cleaner."""
from __future__ import annotations

import json
import io
import os
import runpy
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src/backend"))

# requests is a runtime dependency for live fetching. These tests never make a
# request, so provide only the import surface needed to exercise offline paths.
try:
    import requests  # noqa: F401
except ImportError:
    requests_stub = types.ModuleType("requests")
    class RequestException(Exception):
        pass
    requests_stub.RequestException = RequestException
    requests_stub.Session = type("Session", (), {"__init__": lambda self: setattr(self, "headers", {})})
    requests_stub.exceptions = types.SimpleNamespace(
        SSLError=RequestException, ConnectionError=RequestException, Timeout=RequestException,
        RequestException=RequestException,
    )
    sys.modules["requests"] = requests_stub

from app.catalogue import fetch_live_jobs as fetch
from app.catalogue import fetch_jsearch


class JobFetchCleanTests(unittest.TestCase):
    def setUp(self):
        fetch.SKIPS.clear()


    def test_optional_plus_is_preferred_and_html_is_removed(self):
        description = (
            "Requirements:\n"
            "Experience with Python or Java, plus but not a must.\n"
            "<script>Requirements: leaked JavaScript</script>"
            "<style>.requirements { color: red }</style>"
        )
        plain = fetch.strip_html(description)
        requirements = fetch.extract_requirements(plain)

        self.assertEqual(len(requirements), 1)
        self.assertEqual(requirements[0].importance, "PREFERRED")
        self.assertNotIn("leaked JavaScript", plain)
        self.assertNotIn("color: red", plain)
        self.assertNotIn("<script>", plain)


    def test_or_and_skill_clauses_preserve_requirement_semantics(self):
        description = (
        "Requirements:\n"
        "Experience building services with Python or Java for backend work.\n"
        "Experience querying data with Python and SQL.\n"
    )

        requirements = fetch.extract_requirements(description)

        self.assertEqual(len(requirements), 3)
        optional = requirements[0]
        self.assertEqual(optional.importance, "REQUIRED")
        self.assertEqual(optional.evidence_skills, ["Python", "Java"])
        self.assertEqual(len(optional.alternatives), 2)
        self.assertTrue(all("backend work" in alternative for alternative in optional.alternatives))
        both = requirements[1:]
        self.assertEqual([item.evidence_skills for item in both], [["Python"], ["SQL"]])
        self.assertEqual([item.source_quote for item in both], [
            "Experience querying data with Python and SQL.",
            "Experience querying data with Python and SQL.",
        ])


    def test_ambiguous_compound_skill_clause_is_skipped_for_review(self):
        description = "Requirements:\nExperience with Python, Java, or SQL in production.\n"

        self.assertEqual(fetch.extract_requirements(description), [])


    def test_keyword_regex_treats_cli_string_as_one_keyword(self):
        matcher = fetch.build_keyword_regex("intern")

        self.assertTrue(matcher.search("Software Internship"))
        self.assertFalse(matcher.search("International programme"))

    def test_provider_job_type_uses_explicit_categories_not_incidental_text(self):
        raw = {
            "title": "Senior Director INTERNSHIP", "company_name": "Example", "slug": "role-1",
            "description": "Requirements:\nExperience with Python.",
            "job_types": ["Senior Director INTERNSHIP"], "location": "Singapore",
            "url": "https://example.test/jobs/role-1",
        }

        job = fetch.transform_arbeitnow(raw, fetch.datetime.now(fetch.timezone.utc))

        self.assertIsNotNone(job)
        self.assertEqual(job["job_type"], "OTHER")

    def test_fetcher_drops_whole_record_when_clause_needs_manual_review(self):
        raw = {
            "title": "Analyst", "company_name": "Example", "slug": "ambiguous-1",
            "description": "Requirements:\nExperience with Python, Java, or SQL in production.",
            "job_types": [], "location": "Singapore", "url": "https://example.test/jobs/ambiguous-1",
        }
        job = fetch.transform_arbeitnow(raw, fetch.datetime.now(fetch.timezone.utc))
        self.assertIsNone(job)
        self.assertEqual(fetch.SKIPS["manual_review_ambiguous_requirements"], 1)


    def test_fetcher_cli_keyword_path_runs_without_network(self):
        raw = {"title": "Software Internship"}

        def fetch_listings(_pages, keyword, _session):
            matcher = fetch.build_keyword_regex(keyword)
            return [raw] if matcher.search(raw["title"]) else []

        def transform(_raw, _when, _allow_non_english):
            return {
            "source": "SYNTHETIC", "source_job_id": "cli-1", "title": "Software Internship",
            "company_name": "Example", "country_code": "SG", "location": "Singapore",
            "description": "Requirements:\nExperience with Python.",
            "apply_url": "https://example.test/apply", "source_url": "https://example.test/job",
            "job_type": "UNKNOWN", "employment_time": "UNKNOWN", "work_arrangement": "UNKNOWN",
            "eligibility_notes": [], "posted_at": None, "is_active": True,
            "requirements": [{"requirement_text": "Experience with Python.", "importance": "REQUIRED",
                              "source_quote": "Experience with Python.", "evidence_skills": ["Python"]}],
            }

        old_adapter = fetch.ADAPTERS["arbeitnow"]
        fetch.ADAPTERS["arbeitnow"] = (fetch_listings, transform)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / "cli-batch.json"
                self.assertEqual(fetch.main(["--source", "arbeitnow", "--keyword", "intern", "--out", str(out)]), 0)
                self.assertEqual(json.loads(out.read_text("utf-8"))["jobs"][0]["source_job_id"], "cli-1")
                provenance = json.loads(out.with_suffix(".provenance.json").read_text("utf-8"))
                self.assertEqual(provenance["review_status"], "PENDING_HUMAN_PROVENANCE_REVIEW")
        finally:
            fetch.ADAPTERS["arbeitnow"] = old_adapter


    def test_cleaner_module_invocation_preserves_source_quote(self):
        batch = {
        "schema_version": 1,
        "jobs": [{
            "source": "SYNTHETIC", "source_job_id": "clean-1", "title": "Analyst",
            "company_name": "Example", "country_code": "ZZ", "location": "Unknown",
            "description": "Requirements:\nExperience with Python and SQL.",
            "apply_url": "https://example.test/apply", "source_url": "https://example.test/job",
            "job_type": "UNKNOWN", "employment_time": "UNKNOWN", "work_arrangement": "UNKNOWN",
            "eligibility_notes": [], "requirements": [],
        }],
    }
        with tempfile.TemporaryDirectory() as tmp:
            temp = Path(tmp)
            source = temp / "input.json"
            output = temp / "output.json"
            source.write_text(json.dumps(batch), "utf-8")
            # The source checkout's Python environment does not have requests;
            # the module invocation stays fully offline with this import shim.
            shim_dir = temp / "shim"
            shim_dir.mkdir()
            (shim_dir / "requests.py").write_text(
                "class RequestException(Exception): pass\n"
                "class Session: pass\n"
                "class Exceptions: SSLError = ConnectionError = Timeout = RequestException\n"
                "exceptions = Exceptions()\n", "utf-8")
            env = dict(os.environ, PYTHONPATH=str(shim_dir))
            result = subprocess.run(
                [sys.executable, "-m", "app.catalogue.clean_batch", "--in", str(source), "--out", str(output)],
                cwd=ROOT / "src/backend", env=env, text=True, capture_output=True, check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            cleaned = json.loads(output.read_text("utf-8"))["jobs"][0]
            requirements = cleaned["requirements"]
            self.assertEqual([r["evidence_skills"] for r in requirements], [["Python"], ["SQL"]])
            self.assertTrue(all(r["source_quote"] in cleaned["description"] for r in requirements))
            from app.catalogue.schema import validate_import
            validated, issues = validate_import({"schema_version": 1, "jobs": [cleaned]})
            self.assertEqual(issues, [])
            self.assertEqual(len(validated), 1)
            provenance = json.loads(output.with_suffix(".provenance.json").read_text("utf-8"))
            self.assertEqual(provenance["review_status"], "PENDING_HUMAN_PROVENANCE_REVIEW")


    def test_cleaner_does_not_infer_internship_from_incidental_description_mention(self):
        from app.catalogue.clean_batch import clean_job

        job = {
        "source": "SYNTHETIC", "source_job_id": "type-1", "title": "Senior Director INTERNSHIP",
        "company_name": "Example", "country_code": "ZZ", "location": "Unknown",
        "description": "Requirements:\nExperience with Python.\nOur internship programme starts later.",
        "apply_url": "https://example.test/apply", "source_url": "https://example.test/job",
        "job_type": "INTERNSHIP", "employment_time": "UNKNOWN", "work_arrangement": "UNKNOWN",
        "eligibility_notes": [], "requirements": [],
        }

        cleaned, _ = clean_job(job, allow_non_english=True)

        self.assertEqual(cleaned["job_type"], "UNKNOWN")

    def test_explicit_internship_statements_are_recognized_but_negated_or_incidental_ones_are_not(self):
        classify = fetch.classify_description_job_type
        self.assertEqual(classify("This is an internship."), "INTERNSHIP")
        self.assertEqual(classify("This is a full-time internship."), "INTERNSHIP")
        self.assertEqual(classify("This is not an internship."), "UNKNOWN")
        self.assertEqual(classify("This is not an internship role."), "UNKNOWN")
        self.assertEqual(classify("Previous internship experience is preferred."), "UNKNOWN")
        self.assertEqual(classify("Previous internship role experience is preferred."), "UNKNOWN")

    def test_every_implemented_adapter_skips_records_with_ambiguous_skill_clauses(self):
        ambiguous = "Requirements:\nExperience with Python, Java, or SQL in production."
        base = {
            "title": "Analyst", "company_name": "Example", "description": ambiguous,
            "location": "Singapore", "url": "https://example.test/job/1",
            "apply_url": "https://example.test/apply/1",
        }
        cases = [
            ("arbeitnow", lambda: fetch.transform_arbeitnow({**base, "slug": "a1", "job_types": []}, fetch.datetime.now(fetch.timezone.utc))),
            ("ai_jobs_co", lambda: fetch.transform_ai_jobs_co(
                {**base, "company": "Example", "level": "", "category": "Technology"},
                fetch.datetime.now(fetch.timezone.utc), enrich=True, session=object())),
            ("aidevboard", lambda: fetch.transform_ai_dev_jobs(
                {**base, "id": "d1", "company_name": "Example"}, fetch.datetime.now(fetch.timezone.utc))),
            ("remoteok", lambda: fetch.transform_remoteok(
                {**base, "position": "Analyst", "id": "r1", "company": "Example"}, fetch.datetime.now(fetch.timezone.utc), True)),
            ("remotive", lambda: fetch.transform_remotive(
                {**base, "id": "m1"}, fetch.datetime.now(fetch.timezone.utc), True)),
        ]

        with mock.patch.object(fetch, "fetch_full_description", return_value=ambiguous), \
                mock.patch.object(fetch.time, "sleep", return_value=None):
            for name, transform in cases:
                with self.subTest(adapter=name):
                    fetch.SKIPS.clear()
                    self.assertIsNone(transform())
                    self.assertEqual(fetch.SKIPS["manual_review_ambiguous_requirements"], 1)


class JSearchTests(unittest.TestCase):
    def setUp(self):
        fetch.SKIPS.clear()
        self.now = fetch.datetime(2026, 10, 1, 12, tzinfo=fetch.timezone.utc)

    def listing(self, **changes):
        base = {
            "job_id": "provider-id-1",
            "job_title": "Software Engineering Intern",
            "employer_name": "Example Pte Ltd",
            "job_description": (
                "Qualifications:\nExperience building services with Python or Java.\n"
                "Applicants must be a student currently enrolled in a university programme."
            ),
            "job_location": "Singapore",
            "job_city": "Singapore",
            "job_state": "Singapore",
            "job_country": "Singapore",
            "job_employment_type": "INTERN",
            "job_employment_types": ["INTERN"],
            "job_apply_link": "https://jobs.example.test/apply/1",
            "job_google_link": "https://www.google.com/search?job=provider-id-1",
            "job_is_remote": False,
            "job_posted_at_datetime_utc": "2026-09-28T08:00:00Z",
            "job_posted_at_timestamp": 1790582400,
            "job_highlights": {
                "Qualifications": ["Experience building services with Python or Java."]
            },
        }
        return {**base, **changes}

    def test_jsearch_transform_preserves_only_source_supported_schema_fields(self):
        job = fetch_jsearch.transform_listing(self.listing(), self.now)

        self.assertEqual(job["source"], "JSEARCH")
        self.assertEqual(job["source_job_id"], "provider-id-1")
        self.assertEqual(job["country_code"], "SG")
        self.assertEqual(job["job_type"], "INTERNSHIP")
        self.assertEqual(job["employment_time"], "UNKNOWN")
        self.assertEqual(job["posted_at"], "2026-09-28T08:00:00+00:00")
        self.assertEqual(job["source_url"], "https://www.google.com/search?job=provider-id-1")
        self.assertEqual(job["requirements"][0]["alternatives"], [
            "Experience building services with Python.",
            "Experience building services with Java.",
        ])
        self.assertEqual(job["requirements"][0]["source_quote"],
                         "Experience building services with Python or Java.")
        self.assertEqual(job["requirements"][0]["evidence_skills"], ["Python", "Java"])
        self.assertEqual(job["eligibility_notes"][0]["source_quote"],
                         "Applicants must be a student currently enrolled in a university programme.")
        from app.catalogue.schema import validate_import
        validated, issues = validate_import({"schema_version": 1, "jobs": [job]}, ("JSEARCH",))
        self.assertEqual(issues, [])
        self.assertEqual(len(validated), 1)

    def test_jsearch_filters_actual_country_freshness_and_explicit_employment_type(self):
        cases = [
            ({"job_country": "India"}, "non_singapore"),
            ({"job_posted_at_datetime_utc": "2026-09-23T11:59:59Z"}, "outside_recent_window"),
            ({"job_employment_type": "FULLTIME", "job_employment_types": ["FULLTIME"]},
             "not_internship"),
            ({"job_posted_at_datetime_utc": "2026-10-01T12:00:01Z"}, "future_posting_date"),
        ]
        for updates, reason in cases:
            with self.subTest(reason=reason):
                self.assertIsNone(fetch_jsearch.transform_listing(self.listing(**updates), self.now))
                self.assertEqual(fetch.SKIPS[reason], 1)

    def test_jsearch_full_time_internship_uses_description_for_role_and_provider_for_hours(self):
        description = (
            "This is a full-time internship.\nQualifications:\n"
            "Experience building services with Python."
        )
        job = fetch_jsearch.transform_listing(self.listing(
            job_title="Software Engineering Intern",
            job_employment_type="Full–time",
            job_employment_types=["FULLTIME"],
            job_description=description,
        ), self.now)
        self.assertEqual(job["job_type"], "INTERNSHIP")
        self.assertEqual(job["employment_time"], "FULL_TIME")

    def test_jsearch_title_alone_does_not_turn_full_time_role_into_internship(self):
        job = self.listing(
            job_title="Software Engineering Intern",
            job_employment_type="Full-time",
            job_employment_types=["FULLTIME"],
        )
        self.assertIsNone(fetch_jsearch.transform_listing(job, self.now))
        self.assertEqual(fetch.SKIPS["not_internship"], 1)

    def test_jsearch_part_time_employment_label_normalizes_unicode_dash(self):
        job = fetch_jsearch.transform_listing(self.listing(
            job_employment_type="Part–time",
            job_employment_types=["INTERN", "PARTTIME"],
        ), self.now)
        self.assertEqual(job["job_type"], "INTERNSHIP")
        self.assertEqual(job["employment_time"], "PART_TIME")

    def test_jsearch_long_provider_ids_use_collision_safe_schema_ids(self):
        prefix = "provider-" + "x" * 240
        first = fetch_jsearch.transform_listing(self.listing(job_id=prefix + "A"), self.now)
        second = fetch_jsearch.transform_listing(self.listing(job_id=prefix + "B"), self.now)
        self.assertNotEqual(first["source_job_id"], second["source_job_id"])
        self.assertTrue(first["source_job_id"].startswith("sha256:"))
        self.assertLessEqual(len(first["source_job_id"]), 200)
        from app.catalogue.schema import validate_import
        validated, issues = validate_import({"schema_version": 1, "jobs": [first, second]}, ("JSEARCH",))
        self.assertEqual(issues, [])
        self.assertEqual(len(validated), 2)

    def test_jsearch_requires_location_to_corroborate_singapore_country(self):
        conflicting = self.listing(
            job_location="New York, NY, United States", job_city="New York", job_state="NY",
        )
        self.assertIsNone(fetch_jsearch.transform_listing(conflicting, self.now))
        self.assertEqual(fetch.SKIPS["location_not_singapore"], 1)

        exact = fetch_jsearch.transform_listing(self.listing(job_location="Singapore"), self.now)
        self.assertEqual(exact["country_code"], "SG")

        locality = fetch_jsearch.transform_listing(
            self.listing(job_location="Jurong East, Singapore", job_city="Jurong East"), self.now,
        )
        self.assertEqual(locality["country_code"], "SG")

        missing_ambiguous = self.listing(
            job_location="", job_city="New York", job_state="NY",
        )
        self.assertIsNone(fetch_jsearch.transform_listing(missing_ambiguous, self.now))
        self.assertEqual(fetch.SKIPS["location_not_singapore"], 2)

        missing_exact = self.listing(job_location="", job_city="Singapore", job_state="")
        self.assertEqual(fetch_jsearch.transform_listing(missing_exact, self.now)["country_code"], "SG")

    def test_jsearch_skips_duplicate_provider_ids(self):
        listings = [self.listing(), self.listing()]
        jobs, skipped = fetch_jsearch.transform_listings(listings, self.now)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(skipped, 1)
        self.assertEqual(fetch.SKIPS["duplicate_id"], 1)

    def test_jsearch_does_not_invent_requirements_or_accept_unquoted_highlights(self):
        listing = self.listing(
            job_description="About this role. Apply today.",
            job_highlights={"Qualifications": ["Experience with Python."]},
        )
        self.assertIsNone(fetch_jsearch.transform_listing(listing, self.now))
        self.assertEqual(fetch.SKIPS["no_requirements_section"], 1)

    def test_jsearch_malformed_description_is_skipped_without_crashing(self):
        self.assertIsNone(fetch_jsearch.transform_listing(
            self.listing(job_description={"unexpected": "object"}), self.now))
        self.assertEqual(fetch.SKIPS["empty_description"], 1)

    def test_jsearch_request_uses_cursor_and_never_puts_key_in_url(self):
        class Response:
            def __init__(self, body):
                self.body = json.dumps(body).encode("utf-8")
            def read(self):
                return self.body
            def __enter__(self):
                return self
            def __exit__(self, *_args):
                return False

        responses = [
            Response({"status": "OK", "request_id": "r1", "data": {"jobs": [{"job_id": "1"}], "cursor": "next-page"}}),
            Response({"status": "OK", "request_id": "r2", "data": {"jobs": [{"job_id": "2"}], "cursor": None}}),
        ]
        with mock.patch.dict(os.environ, {"OPENWEBNINJA_API_KEY": "test-secret"}), \
                mock.patch.object(fetch_jsearch.urllib.request, "urlopen", side_effect=responses) as urlopen:
            result, pages_fetched = fetch_jsearch.fetch_listings("software internship in Singapore", 2)
        self.assertEqual([item["job_id"] for item in result], ["1", "2"])
        self.assertEqual(pages_fetched, 2)
        first_request, second_request = (call.args[0] for call in urlopen.call_args_list)
        self.assertNotIn("test-secret", first_request.full_url)
        self.assertNotIn("cursor=", first_request.full_url)
        self.assertIn("cursor=next-page", second_request.full_url)
        self.assertEqual(first_request.get_header("X-api-key"), "test-secret")

    def test_jsearch_quote_must_validate_against_description(self):
        job = fetch_jsearch.transform_listing(self.listing(), self.now)
        job["requirements"][0]["source_quote"] = "The provider highlight says Go is required."
        from app.catalogue.schema import validate_import
        validated, issues = validate_import({"schema_version": 1, "jobs": [job]}, ("JSEARCH",))
        self.assertEqual(validated, [])
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].code, "value_error")

    def test_jsearch_missing_key_and_api_errors_are_sanitized(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "OPENWEBNINJA_API_KEY is missing"):
                fetch_jsearch.api_key_from_environment()

        with mock.patch.dict(os.environ, {"OPENWEBNINJA_API_KEY": "test-secret"}), \
                mock.patch.object(fetch_jsearch.urllib.request, "urlopen", side_effect=RuntimeError("test-secret")):
            with self.assertRaises(RuntimeError) as raised:
                fetch_jsearch.fetch_listings("software internship in Singapore", 1)
        self.assertNotIn("test-secret", str(raised.exception))
        self.assertNotIn("credential echo", str(raised.exception))

    def test_provider_cursor_pages_are_bounded_and_sidecar_records_filters(self):
        with self.assertRaises(ValueError):
            fetch_jsearch.validate_page_count(6)
        sidecar = fetch_jsearch.build_provenance(
            output_file="jobs.json", query="software internship in Singapore", pages=1,
            collected_at=self.now, pages_fetched=1, job_count=1, skipped_counts={},
        )
        self.assertEqual(sidecar["collection_params"]["country"], "sg")
        self.assertEqual(sidecar["collection_params"]["employment_types"], "INTERN")
        self.assertEqual(sidecar["collection_params"]["date_posted"], "week")
        self.assertEqual(sidecar["review_status"], "PENDING_HUMAN_PROVENANCE_REVIEW")
        self.assertIn("provider permission is not implied", sidecar["authorization_note"])

    def test_jsearch_cli_rejects_schema_invalid_candidate_without_writing(self):
        invalid_job = {
            "source": "JSEARCH", "source_job_id": "bad", "title": "Intern",
            "company_name": "Example", "country_code": "SG", "location": "Singapore",
            "description": "Requirements: Experience with Python.",
            "apply_url": "https://jobs.example.test/apply", "source_url": "https://jobs.example.test/job",
            "job_type": "INTERNSHIP", "employment_time": "UNKNOWN", "work_arrangement": "UNKNOWN",
            "requirements": [{"requirement_text": "Python", "importance": "REQUIRED",
                               "source_quote": "This quote does not occur in the description."}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "invalid.json"
            with mock.patch.object(fetch_jsearch, "fetch_listings", return_value=([self.listing()], 1)), \
                    mock.patch.object(fetch_jsearch, "transform_listings", return_value=([invalid_job], 0)), \
                    mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                result = fetch_jsearch.main(["--out", str(output)])
            self.assertEqual(result, 1)
            self.assertFalse(output.exists())
            self.assertIn("jobs.0:value_error", stderr.getvalue())
            self.assertNotIn("This quote does not occur", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
