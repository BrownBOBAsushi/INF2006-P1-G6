"""Small fixed vocabularies used by privacy cleanup and section parsing."""
from __future__ import annotations

import re

# Technical terms that privacy cleanup must never redact (NER and URL recognizers can mistake these for
# names, organisations or domains: "Node.js", "ASP.NET"). Lower-case. Extend deliberately; not exhaustive.
TECH_TERMS: frozenset[str] = frozenset("""
python java javascript typescript sql nosql postgresql postgres mysql sqlite mongodb redis docker kubernetes aws azure gcp
linux bash shell git github gitlab react angular vue node.js nodejs vue.js next.js express flask fastapi django spring
boot rest restful api apis html css sass c c++ c# go golang rust kotlin swift ruby php scala r matlab pandas numpy scipy
scikit-learn sklearn pytorch tensorflow keras opencv nlp cnn rnn tableau power bi excel figma photoshop illustrator
adobe terraform jenkins ci/cd cicd actions airflow spark hadoop kafka jest pytest junit playwright selenium unity
unreal godot wireshark nmap tcp/ip dns dhcp firewall asp.net .net dotnet oauth jwt json xml yaml graphql grpc
raspberry pi arduino stm32 esp32 freertos rtos i2c spi uart pwm micropython nginx apache bigquery snowflake databricks
matplotlib seaborn huggingface analytics google salesforce hubspot notion slack trello
android ios macos windows firebase retrofit room jetpack compose xcode swiftui websocket websockets
microservices devops agile scrum jira confluence sap erp crm latex jupyter tf-idf k-means f1 mnist
""".split())

# Capitalised generic words that a small NER model sometimes tags as people ("Volunteer developer ...").
# A PERSON span made only of these and technical terms is not redacted. Lower-case. Conservative on purpose:
# unfamiliar words are still treated as possible names (privacy over recall of wording).
COMMON_WORDS: frozenset[str] = frozenset("""
volunteer volunteering teaching assistant developer engineer engineering intern internship software data research
student club committee member freelance website builder mentor hackathon open source contributor commuter team
design designer analyst analytics project projects experience education skills technical support helpdesk stock
retail sales customer service web mobile app application systems system network security cloud machine learning
email e-mail phone mobile tel telephone address contact nric fin profile linkedin github portfolio
""".split())

# Recognised section headings (normalised). Section key -> synonyms.
SECTION_HEADINGS: dict[str, frozenset[str]] = {
    "skills": frozenset({"skills", "technical skills", "core skills", "key skills", "skills and tools", "skills & tools",
                         "technologies", "tech stack"}),
    "projects": frozenset({"projects", "project", "personal projects", "academic projects", "selected projects",
                           "project experience"}),
    "experience": frozenset({"experience", "work experience", "professional experience", "internships",
                             "internship experience", "employment", "work history"}),
    "education": frozenset({"education", "academic background", "qualifications", "academic qualifications"}),
}
# Recognised but not part of ResumeContent: their text goes to unassigned_text for the student to place or omit.
UNSUPPORTED_HEADINGS: frozenset[str] = frozenset({
    "certifications", "certificates", "awards", "achievements", "interests", "hobbies", "summary", "profile",
    "objective", "languages", "references", "volunteering", "activities", "publications",
})

_HEADING_CLEAN = re.compile(r"[^a-z0-9&\s]")
_TOKEN = re.compile(r"[a-z0-9][a-z0-9+#./\-]*")


def normalise_heading(line: str) -> str:
    return " ".join(_HEADING_CLEAN.sub(" ", line.casefold()).split())


def heading_key(line: str) -> str | None:
    """'skills' | 'projects' | 'experience' | 'education' | 'unsupported' | None for a plain (unformatted) line."""
    norm = normalise_heading(line)
    for key, names in SECTION_HEADINGS.items():
        if norm in names:
            return key
    return "unsupported" if norm in UNSUPPORTED_HEADINGS else None


def is_generic_phrase(text: str) -> bool:
    """True if every word of the text is a technical term or a common resume word (so it is not a person's name)."""
    words = [w for w in _TOKEN.findall(text.casefold().strip()) if w.strip(".,;:")]
    return bool(words) and all(w.strip(".,;:") in TECH_TERMS or w.strip(".,;:") in COMMON_WORDS for w in words)


def contains_tech_term(text: str) -> bool:
    """True if the whole text or any of its tokens is a known technical term."""
    low = text.casefold().strip().strip(".,;:()[]")
    if low in TECH_TERMS:
        return True
    return any(tok.strip(".,;:") in TECH_TERMS for tok in _TOKEN.findall(low))
