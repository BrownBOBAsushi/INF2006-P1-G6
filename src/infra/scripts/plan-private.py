#!/usr/bin/env python3
"""Offline-only structural and parameter preflight for the private target."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_DIR = ROOT / "src/infra/cloudformation"
TEMPLATES = ("private-base.yaml", "ingress-http-api.yaml", "private-app.yaml")
SECRET_ARN = re.compile(r"^arn:aws(-[a-z]+)?:secretsmanager:[a-z0-9-]+:[0-9]{12}:secret:.+$")


class CloudFormationLoader(yaml.SafeLoader):
    pass


def _intrinsic(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    else:
        value = loader.construct_mapping(node)
    return {tag_suffix: value}


CloudFormationLoader.add_multi_constructor("!", _intrinsic)


def load_templates() -> dict[str, dict]:
    parsed = {}
    for name in TEMPLATES:
        document = yaml.load((TEMPLATE_DIR / name).read_text(), Loader=CloudFormationLoader)
        if not isinstance(document, dict) or document.get("AWSTemplateFormatVersion") != "2010-09-09":
            raise ValueError(f"{name} is not a CloudFormation YAML document")
        if not isinstance(document.get("Resources"), dict) or not document["Resources"]:
            raise ValueError(f"{name} has no CloudFormation resources")
        parsed[name] = document
    return parsed


def validate_parameter_file(path: Path, templates: dict[str, dict]) -> None:
    if path.name == ".env" or path.name.startswith(".env."):
        raise ValueError("parameter input must be a reviewed JSON plan file, not an environment file")
    content = json.loads(path.read_text())
    if not isinstance(content, dict) or set(content) != set(TEMPLATES):
        raise ValueError("parameter JSON must have exactly the three private template names as keys")
    for template_name, definitions in ((name, templates[name]["Parameters"]) for name in TEMPLATES):
        values = content[template_name]
        if not isinstance(values, dict):
            raise ValueError(f"{template_name} parameters must be an object")
        unknown = set(values) - set(definitions)
        missing = {key for key, definition in definitions.items() if "Default" not in definition} - set(values)
        if unknown or missing:
            raise ValueError(f"{template_name} parameter names do not match its template (missing/unknown fields)")
        for key, value in values.items():
            if not isinstance(value, (str, int, float, bool)):
                raise ValueError(f"{template_name}.{key} must be a scalar")
            if "SecretArn" in key and not SECRET_ARN.fullmatch(str(value)):
                raise ValueError(f"{template_name}.{key} must contain a Secrets Manager ARN, never a secret value")
            if any(term in key.lower() for term in ("password", "token", "signingkey")) and "arn" not in key.lower():
                raise ValueError(f"{template_name}.{key} is a secret value field and is not accepted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", action="store_true", help="print the offline deployment order (default)")
    parser.add_argument("--parameters", type=Path, help="optional JSON containing parameter names and non-secret values/secret ARNs")
    args = parser.parse_args()
    try:
        templates = load_templates()
        if args.parameters:
            validate_parameter_file(args.parameters, templates)
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"Private preflight failed: {exc}", file=sys.stderr)
        return 2

    print("Private architecture preflight: local YAML and parameter-name checks passed.")
    print("1. private-base.yaml: isolated VPC, worker, data services and queues")
    print("2. certificate: operator-reviewed DNS-01 issue/import after base readiness")
    print("3. ingress-http-api.yaml: TargetRegistrationMode=asg; empty target group")
    print("4. private-app.yaml: two private instances consume API origin and target group outputs")
    print("5. acceptance and teardown: synthetic data; remove only tagged trial stacks/resources")
    print("No AWS API or credential lookup was performed; this command cannot apply changes.")
    if args.parameters:
        print("Parameter JSON validated; parameter values were not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
